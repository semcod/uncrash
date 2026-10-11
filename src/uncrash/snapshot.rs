//! Linux snapshot worker: stable reads, OpenSSL SHA256/AES-GCM, zlib, COW/cached copies.
//! Private stdin protocol; stdout contains metadata only. No shell or network execution.
use std::{
    collections::{HashMap, HashSet, VecDeque},
    ffi::{c_int, c_ulong, c_void, CString},
    fs::{self, File, Metadata},
    io::{self, Read, Seek, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Component, Path, PathBuf},
    ptr,
    sync::{Arc, Mutex},
    thread,
};
#[link(name = "crypto")]
extern "C" {
    fn EVP_MD_CTX_new() -> *mut c_void;
    fn EVP_MD_CTX_free(p: *mut c_void);
    fn EVP_sha256() -> *const c_void;
    fn EVP_DigestInit_ex(p: *mut c_void, md: *const c_void, engine: *mut c_void) -> c_int;
    fn EVP_DigestUpdate(p: *mut c_void, data: *const c_void, len: usize) -> c_int;
    fn EVP_DigestFinal_ex(p: *mut c_void, data: *mut u8, len: *mut u32) -> c_int;
    fn EVP_CIPHER_CTX_new() -> *mut c_void;
    fn EVP_CIPHER_CTX_free(p: *mut c_void);
    fn EVP_aes_256_gcm() -> *const c_void;
    fn EVP_EncryptInit_ex(
        p: *mut c_void,
        cipher: *const c_void,
        engine: *mut c_void,
        key: *const u8,
        iv: *const u8,
    ) -> c_int;
    fn EVP_EncryptUpdate(
        p: *mut c_void,
        out: *mut u8,
        len: *mut c_int,
        data: *const u8,
        size: c_int,
    ) -> c_int;
    fn EVP_EncryptFinal_ex(p: *mut c_void, out: *mut u8, len: *mut c_int) -> c_int;
    fn EVP_CIPHER_CTX_ctrl(p: *mut c_void, command: c_int, arg: c_int, value: *mut c_void)
        -> c_int;
}
#[link(name = "z")]
extern "C" {
    fn compressBound(len: c_ulong) -> c_ulong;
    fn compress2(
        out: *mut u8,
        size: *mut c_ulong,
        data: *const u8,
        len: c_ulong,
        level: c_int,
    ) -> c_int;
}
extern "C" {
    fn openat(dir: c_int, path: *const i8, flags: c_int, ...) -> c_int;
    fn linkat(
        from_dir: c_int,
        from: *const i8,
        to_dir: c_int,
        to: *const i8,
        flags: c_int,
    ) -> c_int;
    fn ioctl(fd: c_int, request: c_ulong, ...) -> c_int;
    fn copy_file_range(
        from: c_int,
        off_from: *mut i64,
        to: c_int,
        off_to: *mut i64,
        len: usize,
        flags: u32,
    ) -> isize;
}
const NONBLOCK: c_int = 0o4000;
const NOFOLLOW: c_int = 0o400000;
const DIRECTORY: c_int = 0o200000;
const CLOEXEC: c_int = 0o2000000;
fn fail() -> io::Error {
    io::Error::other("snapshot worker refused operation")
}
fn ok(code: c_int) -> io::Result<()> {
    if code == 1 {
        Ok(())
    } else {
        Err(fail())
    }
}
fn unhex(s: &str) -> io::Result<Vec<u8>> {
    if s.len() % 2 != 0 {
        return Err(fail());
    }
    s.as_bytes()
        .chunks(2)
        .map(|x| {
            let a = (x[0] as char).to_digit(16).ok_or_else(fail)?;
            let b = (x[1] as char).to_digit(16).ok_or_else(fail)?;
            Ok((a * 16 + b) as u8)
        })
        .collect()
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn path(s: &str) -> io::Result<PathBuf> {
    use std::os::unix::ffi::OsStringExt;
    Ok(std::ffi::OsString::from_vec(unhex(s)?).into())
}
fn parent(path: &Path) -> io::Result<(File, CString)> {
    if !path.is_absolute() {
        return Err(fail());
    }
    let mut parts = Vec::new();
    for p in path.components() {
        match p {
            Component::RootDir => (),
            Component::Normal(s) => parts.push(CString::new(s.as_bytes()).map_err(|_| fail())?),
            _ => return Err(fail()),
        }
    }
    let name = parts.pop().ok_or_else(fail)?;
    let mut dir = File::open("/")?;
    for part in parts {
        let fd = unsafe {
            openat(
                dir.as_raw_fd(),
                part.as_ptr(),
                DIRECTORY | NOFOLLOW | CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        dir = unsafe { File::from_raw_fd(fd) }
    }
    Ok((dir, name))
}
fn open(path: &Path, flags: c_int) -> io::Result<File> {
    let (dir, name) = parent(path)?;
    let fd = unsafe {
        openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            flags | NOFOLLOW | CLOEXEC,
            0o600,
        )
    };
    if fd < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { File::from_raw_fd(fd) })
    }
}
fn link(from: &Path, to: &Path) -> io::Result<()> {
    let (a, b) = parent(from)?;
    let (c, d) = parent(to)?;
    if unsafe { linkat(a.as_raw_fd(), b.as_ptr(), c.as_raw_fd(), d.as_ptr(), 0) } != 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}
fn mtime(m: &Metadata) -> i128 {
    m.mtime() as i128 * 1_000_000_000 + m.mtime_nsec() as i128
}
fn signature(m: &Metadata) -> Vec<i128> {
    vec![
        m.dev() as i128,
        m.ino() as i128,
        m.len() as i128,
        mtime(m),
        m.ctime() as i128 * 1_000_000_000 + m.ctime_nsec() as i128,
    ]
}
struct Digest(*mut c_void);
impl Digest {
    fn new() -> io::Result<Self> {
        let s = Self(unsafe { EVP_MD_CTX_new() });
        if s.0.is_null() {
            return Err(fail());
        }
        ok(unsafe { EVP_DigestInit_ex(s.0, EVP_sha256(), ptr::null_mut()) })?;
        Ok(s)
    }
    fn add(&mut self, data: &[u8]) -> io::Result<()> {
        ok(unsafe { EVP_DigestUpdate(self.0, data.as_ptr().cast(), data.len()) })
    }
    fn finish(self) -> io::Result<String> {
        let mut bytes = [0u8; 32];
        let mut len = 0;
        ok(unsafe { EVP_DigestFinal_ex(self.0, bytes.as_mut_ptr(), &mut len) })?;
        if len != 32 {
            return Err(fail());
        }
        Ok(hex(&bytes))
    }
}
impl Drop for Digest {
    fn drop(&mut self) {
        unsafe { EVP_MD_CTX_free(self.0) }
    }
}
struct Output {
    file: File,
    ctx: *mut c_void,
}
impl Output {
    fn new(file: File, key: &[u8], aad: &[u8]) -> io::Result<Self> {
        let mut s = Self {
            file,
            ctx: ptr::null_mut(),
        };
        if !key.is_empty() {
            if key.len() != 32 {
                return Err(fail());
            }
            let mut nonce = [0u8; 12];
            File::open("/dev/urandom")?.read_exact(&mut nonce)?;
            s.file.write_all(&nonce)?;
            s.ctx = unsafe { EVP_CIPHER_CTX_new() };
            if s.ctx.is_null() {
                return Err(fail());
            }
            ok(unsafe {
                EVP_EncryptInit_ex(
                    s.ctx,
                    EVP_aes_256_gcm(),
                    ptr::null_mut(),
                    key.as_ptr(),
                    nonce.as_ptr(),
                )
            })?;
            let mut n = 0;
            if aad.len() > i32::MAX as usize {
                return Err(fail());
            }
            ok(unsafe {
                EVP_EncryptUpdate(
                    s.ctx,
                    ptr::null_mut(),
                    &mut n,
                    aad.as_ptr(),
                    aad.len() as i32,
                )
            })?;
        }
        Ok(s)
    }
    fn write(&mut self, bytes: &[u8]) -> io::Result<()> {
        if self.ctx.is_null() {
            self.file.write_all(bytes)
        } else {
            for part in bytes.chunks(1024 * 1024) {
                let mut out = vec![0; part.len() + 16];
                let mut len = 0;
                ok(unsafe {
                    EVP_EncryptUpdate(
                        self.ctx,
                        out.as_mut_ptr(),
                        &mut len,
                        part.as_ptr(),
                        part.len() as i32,
                    )
                })?;
                if len < 0 || len as usize > out.len() {
                    return Err(fail());
                }
                self.file.write_all(&out[..len as usize])?;
            }
            Ok(())
        }
    }
    fn finish(&mut self) -> io::Result<()> {
        if !self.ctx.is_null() {
            let mut out = [0u8; 16];
            let mut len = 0;
            ok(unsafe { EVP_EncryptFinal_ex(self.ctx, out.as_mut_ptr(), &mut len) })?;
            if !(0..=16).contains(&len) {
                return Err(fail());
            }
            self.file.write_all(&out[..len as usize])?;
            ok(unsafe { EVP_CIPHER_CTX_ctrl(self.ctx, 0x10, 16, out.as_mut_ptr().cast()) })?;
            self.file.write_all(&out)?;
        }
        self.file.sync_all()
    }
}
impl Drop for Output {
    fn drop(&mut self) {
        if !self.ctx.is_null() {
            unsafe { EVP_CIPHER_CTX_free(self.ctx) }
        }
    }
}
fn digest(file: &mut File) -> io::Result<String> {
    file.rewind()?;
    let mut d = Digest::new()?;
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        d.add(&buffer[..n])?;
    }
    d.finish()
}
#[derive(Clone)]
struct Job {
    src: PathBuf,
    dst: PathBuf,
    limit: u64,
    aad: Vec<u8>,
    cache: Option<PathBuf>,
    old_sig: Vec<i128>,
    old_hash: String,
    cache_size: u64,
    cache_mtime: i128,
    cache_encoding: String,
}
fn result(
    index: usize,
    m: &Metadata,
    hash: &str,
    encoding: &str,
    method: &str,
    out: &Metadata,
    size: u64,
) -> String {
    format!("{{\"index\":{index},\"size\":{},\"sha256\":\"{hash}\",\"source_signature\":{:?},\"executable\":{},\"encoding\":\"{encoding}\",\"copy_method\":\"{method}\",\"blob_size\":{},\"blob_mtime_ns\":{}}}",size,signature(m),m.mode()&0o100!=0,out.len(),mtime(out))
}
fn run(index: usize, job: Job, key: &[u8], compress: bool) -> io::Result<String> {
    let mut input = open(&job.src, 0o4000)?;
    let before = input.metadata()?;
    if !before.is_file() || before.len() > job.limit {
        return Err(fail());
    }
    if key.is_empty()
        && signature(&before) == job.old_sig
        && job.old_hash.len() == 64
        && job.old_hash.bytes().all(|b| b.is_ascii_hexdigit())
        && ["raw", "zlib"].contains(&job.cache_encoding.as_str())
    {
        if let Some(ref cached) = job.cache {
            if let Ok(cache) = open(cached, 0) {
                let m = cache.metadata()?;
                if m.is_file() && m.len() == job.cache_size && mtime(&m) == job.cache_mtime {
                    link(cached, &job.dst)?;
                    let out = open(&job.dst, 0)?;
                    let after = out.metadata()?;
                    if after.dev() != m.dev()
                        || after.ino() != m.ino()
                        || after.len() != m.len()
                        || mtime(&after) != mtime(&m)
                        || signature(&input.metadata()?) != signature(&before)
                        || signature(&open(&job.src, 0o4000)?.metadata()?) != signature(&before)
                    {
                        return Err(fail());
                    }
                    return Ok(result(
                        index,
                        &before,
                        &job.old_hash,
                        &job.cache_encoding,
                        "cached-hardlink",
                        &after,
                        before.len(),
                    ));
                }
            }
        }
    }
    // O_RDWR|O_CREAT|O_EXCL, private output; copy never links the live source.
    let output = open(&job.dst, 2 | 0o100 | 0o200)?;
    let (hash, encoding, method);
    let jsonl = job.src.extension().is_some_and(|s| s == "jsonl");
    let mut logical_size = before.len();
    if compress || jsonl {
        let mut data = Vec::new();
        (&mut input).take(before.len()).read_to_end(&mut data)?;
        if data.len() as u64 != before.len() {
            return Err(fail());
        }
        if jsonl {
            let current = input.metadata()?;
            let named = open(&job.src, 0o4000)?.metadata()?;
            if named.dev() != before.dev()
                || named.ino() != before.ino()
                || current.len() < before.len()
            {
                return Err(fail());
            }
            if signature(&current) != signature(&before) {
                // A chat log may append while captured: verify the entire initial prefix.
                input.rewind()?;
                let mut verify = Vec::new();
                (&mut input).take(before.len()).read_to_end(&mut verify)?;
                if verify != data {
                    return Err(fail());
                }
                if current.len() > before.len() && data.last().is_some_and(|b| *b != b'\n') {
                    let end = data.iter().rposition(|b| *b == b'\n').map_or(0, |i| i + 1);
                    data.truncate(end);
                }
            }
            logical_size = data.len() as u64;
        }
        let mut d = Digest::new()?;
        d.add(&data)?;
        hash = d.finish()?;
        let mut encoded = Vec::new();
        if compress {
            let mut length = unsafe { compressBound(data.len() as c_ulong) };
            encoded.resize(length as usize, 0);
            if unsafe {
                compress2(
                    encoded.as_mut_ptr(),
                    &mut length,
                    data.as_ptr(),
                    data.len() as c_ulong,
                    1,
                )
            } != 0
            {
                return Err(fail());
            }
            encoded.truncate(length as usize);
        }
        encoding = if compress && encoded.len() < data.len() {
            "zlib"
        } else {
            "raw"
        };
        let mut out = Output::new(output, key, &job.aad)?;
        out.write(if encoding == "zlib" { &encoded } else { &data })?;
        out.finish()?;
        method = if jsonl {
            "jsonl-prefix"
        } else {
            "rust-compress"
        };
    } else if !key.is_empty() {
        let mut out = Output::new(output, key, &job.aad)?;
        let mut d = Digest::new()?;
        let mut bytes = vec![0u8; 1024 * 1024];
        let mut size = 0u64;
        loop {
            let n = input.read(&mut bytes)?;
            if n == 0 {
                break;
            }
            size += n as u64;
            if size > job.limit {
                return Err(fail());
            }
            d.add(&bytes[..n])?;
            out.write(&bytes[..n])?;
        }
        if size != before.len() {
            return Err(fail());
        }
        hash = d.finish()?;
        out.finish()?;
        encoding = "raw";
        method = "rust-aes-gcm";
    } else {
        let mut output = output;
        let cloned = unsafe {
            ioctl(
                output.as_raw_fd(),
                0x40049409u64 as c_ulong,
                input.as_raw_fd(),
            )
        } == 0;
        let mut count = 0u64;
        if !cloned {
            loop {
                let n = unsafe {
                    copy_file_range(
                        input.as_raw_fd(),
                        ptr::null_mut(),
                        output.as_raw_fd(),
                        ptr::null_mut(),
                        1024 * 1024,
                        0,
                    )
                };
                if n < 0 {
                    io::copy(
                        &mut std::io::Read::by_ref(&mut input)
                            .take(job.limit.saturating_sub(count).saturating_add(1)),
                        &mut output,
                    )
                    .map(|n| {
                        count += n;
                    })?;
                    break;
                }
                if n == 0 {
                    break;
                }
                count += n as u64;
                if count > job.limit {
                    return Err(fail());
                }
            }
            if count != before.len() {
                return Err(fail());
            }
        }
        hash = digest(&mut output)?;
        output.sync_all()?;
        encoding = "raw";
        method = if cloned { "reflink" } else { "kernel-copy" };
    }
    if !jsonl
        && (signature(&input.metadata()?) != signature(&before)
            || signature(&open(&job.src, 0o4000)?.metadata()?) != signature(&before))
    {
        return Err(fail());
    }
    let out = open(&job.dst, 0)?.metadata()?;
    Ok(result(
        index,
        &before,
        &hash,
        encoding,
        method,
        &out,
        logical_size,
    ))
}
fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 16);
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out
}
fn python_space(c: char) -> bool {
    c.is_ascii_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}
fn find_panic_in_content(content: &str) -> Option<(String, String)> {
    let lower = content.to_ascii_lowercase();
    for (prefix, required) in [
        ("caught panic:", ""),
        (
            "runtime error:",
            "invalid memory address or nil pointer dereference",
        ),
        (
            "failed to load conversation ",
            "database disk image is malformed",
        ),
        ("program was killed:", "program experienced a panic"),
    ] {
        for (pos, _) in lower.match_indices(prefix) {
            let rest = &content[pos + prefix.len()..];
            let (rest, id) = if prefix == "failed to load conversation " {
                let colon = match rest.find(':') {
                    Some(c) => c,
                    None => continue,
                };
                let id = &rest[..colon];
                if id.is_empty() || !id.chars().all(|c| c.is_ascii_hexdigit() || c == '-') {
                    continue;
                }
                (&rest[colon + 1..], Some(id))
            } else {
                (rest, None)
            };
            let rest = rest.trim_start_matches(python_space);
            let detail = &rest[..rest.find('\n').unwrap_or(rest.len())];
            let detail_lower = detail.to_ascii_lowercase();
            if if id.is_some() {
                !detail_lower.contains(required)
            } else {
                !detail_lower.starts_with(required)
            } {
                continue;
            }
            let end = content.len() - rest.len() + detail.len();
            return Some((
                content[pos..end].trim_matches(python_space).to_string(),
                id.unwrap_or(detail).trim_matches(python_space).to_string(),
            ));
        }
    }
    None
}
fn read_regular(path: &Path, limit: u64) -> io::Result<Vec<u8>> {
    let file = open(path, NONBLOCK)?;
    let meta = file.metadata()?;
    if !meta.is_file() || meta.len() > limit {
        return Err(fail());
    }
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(fail());
    }
    Ok(bytes)
}
fn scan_panics(args: &[String]) -> io::Result<()> {
    if args.is_empty() {
        println!("[]");
        return Ok(());
    }
    let log_dir = Path::new(&args[0]);
    let max_files: usize = if args.len() > 1 {
        match args[1].parse::<usize>() {
            Ok(n) if (1..=100).contains(&n) => n,
            _ => return Err(fail()),
        }
    } else {
        20
    };

    let _directory_guard = match open(log_dir, DIRECTORY) {
        Ok(f) => f,
        Err(_) => {
            println!("[]");
            return Ok(());
        }
    };
    let meta = match std::fs::symlink_metadata(log_dir) {
        Ok(m) => m,
        Err(_) => {
            println!("[]");
            return Ok(());
        }
    };
    if meta.file_type().is_symlink() || !meta.is_dir() {
        println!("[]");
        return Ok(());
    }

    let entries = match std::fs::read_dir(log_dir) {
        Ok(e) => e,
        Err(_) => {
            println!("[]");
            return Ok(());
        }
    };

    let mut candidates: Vec<(i128, PathBuf)> = Vec::new();
    for entry in entries {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        let p = entry.path();
        if p.extension().and_then(|s| s.to_str()) != Some("log") {
            continue;
        }
        let smeta = match std::fs::symlink_metadata(&p) {
            Ok(m) => m,
            Err(_) => continue,
        };
        if smeta.file_type().is_symlink() || !smeta.is_file() {
            continue;
        }
        let mtime_ns = (smeta.mtime() as i128) * 1_000_000_000 + (smeta.mtime_nsec() as i128);
        candidates.push((mtime_ns, p));
    }

    candidates.sort_by(|a, b| (b.0, &b.1).cmp(&(a.0, &a.1)));
    if candidates.len() > max_files {
        candidates.truncate(max_files);
    }

    let mut panics_json = Vec::new();
    for (_, log_path) in candidates {
        let file_name = match log_path.file_name().and_then(|s| s.to_str()) {
            Some(s) => s.to_string(),
            None => continue,
        };

        let mut file = match open(&log_path, NONBLOCK) {
            Ok(f) => f,
            Err(_) => continue,
        };
        let meta = match file.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        if !meta.is_file() {
            continue;
        }
        let file_size = meta.len();
        let chunk_size: u64 = 512 * 1024;
        let read_offset = if file_size > chunk_size {
            file_size - chunk_size
        } else {
            0
        };
        if file.seek(io::SeekFrom::Start(read_offset)).is_err() {
            continue;
        }
        let mut buf = Vec::new();
        if file.take(chunk_size).read_to_end(&mut buf).is_err() {
            continue;
        }
        if !buf.is_ascii() {
            return Err(fail());
        } // Python owns Unicode regex semantics.
        let content = String::from_utf8_lossy(&buf);

        if let Some((signature, matched_detail)) = find_panic_in_content(&content) {
            panics_json.push(format!(
                "{{\"log_path\":\"{}\",\"log_name\":\"{}\",\"signature\":\"{}\",\"matched_detail\":\"{}\"}}",
                json_escape(&log_path.to_string_lossy()),
                json_escape(&file_name),
                json_escape(&signature),
                json_escape(&matched_detail)
            ));
        }
    }

    println!("[{}]", panics_json.join(","));
    Ok(())
}

fn sha256_digest(data: &[u8]) -> Option<String> {
    unsafe {
        let ctx = EVP_MD_CTX_new();
        if ctx.is_null() {
            return None;
        }
        let md = EVP_sha256();
        if EVP_DigestInit_ex(ctx, md, ptr::null_mut()) != 1 {
            EVP_MD_CTX_free(ctx);
            return None;
        }
        if EVP_DigestUpdate(ctx, data.as_ptr() as *const c_void, data.len()) != 1 {
            EVP_MD_CTX_free(ctx);
            return None;
        }
        let mut out = [0u8; 32];
        let mut len = 0u32;
        if EVP_DigestFinal_ex(ctx, out.as_mut_ptr(), &mut len) != 1 || len != 32 {
            EVP_MD_CTX_free(ctx);
            return None;
        }
        EVP_MD_CTX_free(ctx);
        let mut hex = String::with_capacity(64);
        for b in out {
            use std::fmt::Write;
            let _ = write!(&mut hex, "{:02x}", b);
        }
        Some(hex)
    }
}

#[derive(Debug, Clone, PartialEq)]
enum JsonValue {
    Null,
    Bool(bool),
    Number(String),
    String(String),
    Array(Vec<JsonValue>),
    Object(Vec<(String, JsonValue)>),
}

impl JsonValue {
    fn get(&self, key: &str) -> Option<&JsonValue> {
        match self {
            JsonValue::Object(map) => {
                for (k, v) in map.iter().rev() {
                    if k == key {
                        return Some(v);
                    }
                }
                None
            }
            _ => None,
        }
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            JsonValue::String(s) => Some(s.as_str()),
            _ => None,
        }
    }

    fn as_i64(&self) -> Option<i64> {
        match self {
            JsonValue::Number(n) => n.parse::<i64>().ok(),

            _ => None,
        }
    }

    fn as_bool(&self) -> Option<bool> {
        match self {
            JsonValue::Bool(b) => Some(*b),
            _ => None,
        }
    }

    fn as_array(&self) -> Option<&[JsonValue]> {
        match self {
            JsonValue::Array(arr) => Some(arr.as_slice()),
            _ => None,
        }
    }
}

struct JsonParser<'a> {
    bytes: &'a [u8],
    pos: usize,
    depth: usize,
    unsupported: bool,
}

impl<'a> JsonParser<'a> {
    fn new(input: &'a str) -> Self {
        Self {
            bytes: input.as_bytes(),
            pos: 0,
            depth: 0,
            unsupported: false,
        }
    }

    fn peek(&self) -> Option<u8> {
        if self.pos < self.bytes.len() {
            Some(self.bytes[self.pos])
        } else {
            None
        }
    }

    fn bump(&mut self) -> Option<u8> {
        if self.pos < self.bytes.len() {
            let b = self.bytes[self.pos];
            self.pos += 1;
            Some(b)
        } else {
            None
        }
    }

    fn skip_whitespace(&mut self) {
        while let Some(b) = self.peek() {
            if b == b' ' || b == b'\t' || b == b'\n' || b == b'\r' {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn parse(&mut self) -> Option<JsonValue> {
        if self.depth >= 128 {
            self.unsupported = true;
            return None;
        }
        self.depth += 1;
        self.skip_whitespace();
        let value = match self.peek() {
            Some(b'n') => self.parse_null(),
            Some(b't' | b'f') => self.parse_bool(),
            Some(b'"') => self.parse_string().map(JsonValue::String),
            Some(b'[') => self.parse_array(false),
            Some(b'{') => self.parse_object(false, false),
            Some(b'-' | b'0'..=b'9') => self.parse_number(),
            Some(b'N' | b'I') => {
                self.unsupported = true;
                None
            }
            _ => None,
        };
        self.depth -= 1;
        self.skip_whitespace();
        value
    }
    fn manifest(&mut self, preview: bool) -> Option<JsonValue> {
        self.skip_whitespace();
        if self.peek()? != b'{' {
            return None;
        }
        let value = self.parse_object(true, preview)?;
        self.skip_whitespace();
        if self.pos != self.bytes.len() {
            return None;
        }
        Some(value)
    }
    fn parse_manifest_health(&mut self) -> Option<JsonValue> {
        self.manifest(false)
    }
    fn parse_manifest_preview(&mut self) -> Option<JsonValue> {
        self.manifest(true)
    }
    fn parse_json(&mut self) -> Option<JsonValue> {
        self.skip_whitespace();
        let value = self.parse()?;
        self.skip_whitespace();
        if self.pos != self.bytes.len() {
            return None;
        }
        Some(value)
    }
    fn skip_value(&mut self) -> bool {
        // Strict streaming validation without materializing large discarded arrays.
        if self.depth >= 128 {
            self.unsupported = true;
            return false;
        }
        self.depth += 1;
        self.skip_whitespace();
        let result = (|| -> Option<()> {
            match self.peek()? {
                b'[' | b'{' => {
                    let object = self.bump()? == b'{';
                    let closing = if object { b'}' } else { b']' };
                    self.skip_whitespace();
                    if self.peek() == Some(closing) {
                        self.bump();
                        return Some(());
                    }
                    loop {
                        if object {
                            self.parse_string()?;
                            self.skip_whitespace();
                            if self.bump()? != b':' {
                                return None;
                            }
                        }
                        if !self.skip_value() {
                            return None;
                        }
                        self.skip_whitespace();
                        match self.bump()? {
                            b',' => self.skip_whitespace(),
                            c if c == closing => break,
                            _ => return None,
                        }
                    }
                }
                b'"' => {
                    self.parse_string()?;
                }
                b'n' => {
                    self.parse_null()?;
                }
                b't' | b'f' => {
                    self.parse_bool()?;
                }
                b'-' | b'0'..=b'9' => {
                    self.parse_number()?;
                }
                b'N' | b'I' => {
                    self.unsupported = true;
                    return None;
                }
                _ => return None,
            }
            Some(())
        })();
        self.depth -= 1;
        result.is_some()
    }
    fn parse_null(&mut self) -> Option<JsonValue> {
        if self.pos + 4 <= self.bytes.len() && &self.bytes[self.pos..self.pos + 4] == b"null" {
            self.pos += 4;
            Some(JsonValue::Null)
        } else {
            None
        }
    }

    fn parse_bool(&mut self) -> Option<JsonValue> {
        if self.peek()? == b't' {
            if self.pos + 4 <= self.bytes.len() && &self.bytes[self.pos..self.pos + 4] == b"true" {
                self.pos += 4;
                Some(JsonValue::Bool(true))
            } else {
                None
            }
        } else {
            if self.pos + 5 <= self.bytes.len() && &self.bytes[self.pos..self.pos + 5] == b"false" {
                self.pos += 5;
                Some(JsonValue::Bool(false))
            } else {
                None
            }
        }
    }

    fn parse_string(&mut self) -> Option<String> {
        if self.bump()? != b'"' {
            return None;
        }
        let start = self.pos;
        let mut has_escapes = false;
        while self.pos < self.bytes.len() {
            let b = self.bytes[self.pos];
            if b == b'"' {
                break;
            }
            if b < 0x20 {
                return None;
            }
            if b == b'\\' {
                has_escapes = true;
                self.pos += 2;
            } else {
                self.pos += 1;
            }
        }
        if self.pos >= self.bytes.len() {
            return None;
        }
        let end = self.pos;
        self.pos += 1;

        if !has_escapes {
            return std::str::from_utf8(&self.bytes[start..end])
                .ok()
                .map(|s| s.to_string());
        }

        let mut s = String::with_capacity(end - start);
        let mut i = start;
        while i < end {
            if self.bytes[i] == b'\\' {
                i += 1;
                if i >= end {
                    return None;
                }
                match self.bytes[i] {
                    b'"' => s.push('"'),
                    b'\\' => s.push('\\'),
                    b'/' => s.push('/'),
                    b'b' => s.push('\x08'),
                    b'f' => s.push('\x0c'),
                    b'n' => s.push('\n'),
                    b'r' => s.push('\r'),
                    b't' => s.push('\t'),
                    b'u' => {
                        i += 1;
                        if i + 4 > end {
                            return None;
                        }
                        let hex_str = std::str::from_utf8(&self.bytes[i..i + 4]).ok()?;
                        let code = u32::from_str_radix(hex_str, 16).ok()?;
                        let code = if (0xd800..=0xdbff).contains(&code) {
                            if i + 10 > end || &self.bytes[i + 4..i + 6] != b"\\u" {
                                self.unsupported = true;
                                return None;
                            }
                            let low = u32::from_str_radix(
                                std::str::from_utf8(&self.bytes[i + 6..i + 10]).ok()?,
                                16,
                            )
                            .ok()?;
                            if !(0xdc00..=0xdfff).contains(&low) {
                                self.unsupported = true;
                                return None;
                            }
                            i += 6;
                            0x10000 + ((code - 0xd800) << 10) + low - 0xdc00
                        } else {
                            code
                        };
                        // Python accepts lone surrogates; delegate rather than substituting bytes.
                        let ch = match char::from_u32(code) {
                            Some(c) => c,
                            None => {
                                self.unsupported = true;
                                return None;
                            }
                        };
                        s.push(ch);
                        i += 3;
                    }
                    _ => return None,
                }
            } else {
                let start_run = i;
                while i < end && self.bytes[i] != b'\\' {
                    i += 1;
                }
                let slice = std::str::from_utf8(&self.bytes[start_run..i]).ok()?;
                s.push_str(slice);
                continue;
            }
            i += 1;
        }
        Some(s)
    }

    fn parse_number(&mut self) -> Option<JsonValue> {
        let start = self.pos;
        if self.bytes[start..].starts_with(b"-Infinity") {
            self.unsupported = true;
            return None;
        }
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        match self.peek()? {
            b'0' => self.pos += 1,
            b'1'..=b'9' => {
                while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                    self.pos += 1;
                }
            }
            _ => return None,
        }
        if self.peek() == Some(b'.') {
            self.pos += 1;
            let before = self.pos;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.pos += 1;
            }
            if before == self.pos {
                return None;
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            let before = self.pos;
            while self.peek().is_some_and(|b| b.is_ascii_digit()) {
                self.pos += 1;
            }
            if before == self.pos {
                return None;
            }
        }
        let token = &self.bytes[start..self.pos];
        if token.len() > 4300 {
            self.unsupported = true;
            return None;
        }
        Some(JsonValue::Number(
            std::str::from_utf8(token).ok()?.to_string(),
        ))
    }
    fn parse_array(&mut self, is_profiles: bool) -> Option<JsonValue> {
        if self.bump()? != b'[' {
            return None;
        }
        let mut items = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b']') {
            self.bump();
            return Some(JsonValue::Array(items));
        }
        loop {
            let item = if is_profiles {
                self.parse()?
            } else {
                self.parse()?
            };
            items.push(item);
            self.skip_whitespace();
            match self.peek()? {
                b',' => {
                    self.bump();
                    self.skip_whitespace();
                }
                b']' => {
                    self.bump();
                    break;
                }
                _ => return None,
            }
        }
        Some(JsonValue::Array(items))
    }

    fn parse_object(&mut self, is_manifest_root: bool, is_preview: bool) -> Option<JsonValue> {
        if self.bump()? != b'{' {
            return None;
        }
        let mut entries = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b'}') {
            self.bump();
            return Some(JsonValue::Object(entries));
        }
        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            self.skip_whitespace();
            if self.bump()? != b':' {
                return None;
            }
            if is_manifest_root {
                if is_preview {
                    if key != "schema"
                        && key != "origin"
                        && key != "encryption"
                        && key != "id"
                        && key != "created_at"
                        && key != "profiles"
                        && key != "session_hosts"
                        && key != "jetbrains"
                    {
                        if !self.skip_value() {
                            return None;
                        }
                    } else if key == "profiles" {
                        self.skip_whitespace();
                        let val = self.parse_array(true)?;
                        entries.push((key, val));
                    } else {
                        let val = self.parse()?;
                        entries.push((key, val));
                    }
                } else {
                    if key != "schema"
                        && key != "id"
                        && key != "created_at"
                        && key != "origin"
                        && key != "jetbrains"
                    {
                        if !self.skip_value() {
                            return None;
                        }
                    } else {
                        let val = self.parse()?;
                        entries.push((key, val));
                    }
                }
            } else if is_preview && key == "files" {
                if !self.skip_value() {
                    return None;
                }
            } else {
                let val = self.parse()?;
                entries.push((key, val));
            }
            self.skip_whitespace();
            match self.peek()? {
                b',' => {
                    self.bump();
                    self.skip_whitespace();
                }
                b'}' => {
                    self.bump();
                    break;
                }
                _ => return None,
            }
        }
        Some(JsonValue::Object(entries))
    }
}

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = y - if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = (y - era * 400) as u32;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy as u32;
    era * 146097 + doe as i64 - 719468
}

fn parse_iso_datetime(s: &str) -> Option<f64> {
    if s.len() < 19 {
        return None;
    }
    let parts: Vec<&str> = s.split('T').collect();
    if parts.len() != 2 {
        return None;
    }
    let date_parts: Vec<&str> = parts[0].split('-').collect();
    if date_parts.len() != 3 {
        return None;
    }
    let year: i64 = date_parts[0].parse().ok()?;
    let month: i64 = date_parts[1].parse().ok()?;
    let day: i64 = date_parts[2].parse().ok()?;

    if !(1..=9999).contains(&year) || !(1..=12).contains(&month) {
        return None;
    }
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let max_day = match month {
        2 => {
            if leap {
                29
            } else {
                28
            }
        }
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    };
    if !(1..=max_day).contains(&day) {
        return None;
    }
    let time_str = parts[1];
    let (time_main, tz_offset) = if time_str.ends_with('Z') {
        (&time_str[..time_str.len() - 1], 0i64)
    } else if let Some(idx) = time_str.rfind('+') {
        let (tm, tz) = time_str.split_at(idx);
        let tz_parts: Vec<&str> = tz[1..].split(':').collect();
        if tz_parts.len() != 2 {
            return None;
        }
        let h: i64 = tz_parts[0].parse().ok()?;
        let m: i64 = tz_parts[1].parse().ok()?;
        if h > 23 || m > 59 || h < 0 || m < 0 {
            return None;
        }
        (tm, h * 3600 + m * 60)
    } else if let Some(idx) = time_str.rfind('-') {
        let (tm, tz) = time_str.split_at(idx);
        if tm.contains(':') {
            let tz_parts: Vec<&str> = tz[1..].split(':').collect();
            if tz_parts.len() != 2 {
                return None;
            }
            let h: i64 = tz_parts[0].parse().ok()?;
            let m: i64 = tz_parts[1].parse().ok()?;
            if h > 23 || m > 59 || h < 0 || m < 0 {
                return None;
            }
            (tm, -(h * 3600 + m * 60))
        } else {
            return None;
        }
    } else {
        return None;
    };

    let tm_parts: Vec<&str> = time_main.split(':').collect();
    if tm_parts.len() != 3 {
        return None;
    }
    let hour: i64 = tm_parts[0].parse().ok()?;
    let min: i64 = tm_parts[1].parse().ok()?;
    let (sec, frac) = if let Some(dot_idx) = tm_parts[2].find('.') {
        let s: i64 = tm_parts[2][..dot_idx].parse().ok()?;
        let frac_str = &tm_parts[2][dot_idx + 1..];
        let mut frac_val = 0.0f64;
        let mut div = 10.0f64;
        if frac_str.len() > 6 {
            return None;
        }
        if frac_str.is_empty() || !frac_str.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        for c in frac_str.chars() {
            if let Some(d) = c.to_digit(10) {
                frac_val += (d as f64) / div;
                div *= 10.0;
            }
        }
        (s, frac_val)
    } else {
        let s: i64 = tm_parts[2].parse().ok()?;
        (s, 0.0f64)
    };

    if !(0..=23).contains(&hour) || !(0..=59).contains(&min) || !(0..=59).contains(&sec) {
        return None;
    }
    let days = days_from_civil(year, month, day);
    let epoch_secs = days * 86400 + hour * 3600 + min * 60 + sec - tz_offset;
    Some(epoch_secs as f64 + frac)
}

#[derive(Debug, Clone)]
struct HistoricalRecord {
    provider: String,
    pid: i64,
    start_ticks: String,
    ide_pid: i64,
    cwd: Option<String>,
    terminal: Option<String>,
    first_snapshot: String,
    last_snapshot: String,
    observations: usize,
}

struct ProcessHealthResult {
    dir_name: String,
    created_ts: f64,
    obs: Vec<((Option<String>, i64, String, i64), HistoricalRecord)>,
}

fn process_health_dir(
    root: &Path,
    dir_name: &str,
    now_ts: f64,
) -> Result<ProcessHealthResult, bool> {
    let dir_path = root.join(dir_name);
    let manifest_path = dir_path.join("manifest.json");
    let sha_path = dir_path.join("manifest.sha256");

    let raw = read_regular(&manifest_path, 32 * 1024 * 1024).map_err(|_| false)?;
    let calc_hash = sha256_digest(&raw).ok_or(false)?;
    let hash_bytes = read_regular(&sha_path, 4096).map_err(|_| false)?;
    let expected_hash = std::str::from_utf8(&hash_bytes).map_err(|_| false)?.trim();
    if calc_hash != expected_hash {
        return Err(false);
    }

    let raw_str = std::str::from_utf8(&raw).map_err(|_| false)?;
    let raw_str = raw_str.strip_prefix('\u{feff}').unwrap_or(raw_str);
    let mut parser = JsonParser::new(raw_str);
    let data = parser.parse_manifest_health().ok_or(parser.unsupported)?;

    if data.get("schema").and_then(|v| v.as_str()) != Some("uncrash.snapshot/v1") {
        return Err(false);
    }
    if data.get("id").and_then(|v| v.as_str()) != Some(dir_name) {
        return Err(false);
    }

    let created_str = data
        .get("created_at")
        .and_then(|v| v.as_str())
        .ok_or(false)?;
    let created_ts = parse_iso_datetime(created_str).ok_or(true)?;
    if created_ts > now_ts {
        return Err(false);
    }

    let mut obs = Vec::new();
    let providers: HashSet<&'static str> = HashSet::from(["codex", "claude", "agy"]);

    if let Some(origin) = data.get("origin") {
        if !matches!(origin, JsonValue::String(_) | JsonValue::Null) {
            return Err(true);
        }
    }
    if let Some(jb) = data.get("jetbrains") {
        if !matches!(jb, JsonValue::Object(_)) {
            return Err(true);
        }
        for key in ["processes", "descendants"] {
            if let Some(rows) = jb.get(key) {
                let rows = rows.as_array().ok_or(true)?;
                for row in rows {
                    if !matches!(row, JsonValue::Object(_))
                        || row.get("pid").and_then(|v| v.as_i64()).is_none()
                    {
                        return Err(true);
                    }
                    if key == "descendants" && row.get("ppid").and_then(|v| v.as_i64()).is_none() {
                        return Err(true);
                    }
                    if key == "processes" {
                        if row
                            .get("root_ide_candidate")
                            .is_some_and(|v| !matches!(v, JsonValue::Bool(_)))
                        {
                            return Err(true);
                        }
                    } else if row
                        .get("name")
                        .and_then(|v| v.as_str())
                        .is_some_and(|n| providers.contains(n))
                    {
                        if row.get("ppid").and_then(|v| v.as_i64()).is_none()
                            || row.get("start_ticks").and_then(|v| v.as_str()).is_none()
                        {
                            return Err(true);
                        }
                        for field in ["cwd", "terminal"] {
                            if row.get(field).is_some_and(|v| {
                                !matches!(v, JsonValue::Null | JsonValue::String(_))
                            }) {
                                return Err(true);
                            }
                        }
                    }
                }
            }
        }
        let mut roots = HashSet::new();
        if let Some(procs) = jb.get("processes").and_then(|v| v.as_array()) {
            for proc in procs {
                if proc.get("root_ide_candidate").and_then(|v| v.as_bool()) == Some(true) {
                    if let Some(pid) = proc.get("pid").and_then(|v| v.as_i64()) {
                        roots.insert(pid);
                    }
                }
            }
        }

        let mut descendant_order = Vec::new();
        let mut descendants_map: HashMap<
            i64,
            (i64, String, String, Option<String>, Option<String>),
        > = HashMap::new();
        if let Some(descendants) = jb.get("descendants").and_then(|v| v.as_array()) {
            for row in descendants {
                let pid = match row.get("pid").and_then(|v| v.as_i64()) {
                    Some(p) => p,
                    None => continue,
                };
                let ppid = match row.get("ppid").and_then(|v| v.as_i64()) {
                    Some(p) => p,
                    None => continue,
                };
                let name = row
                    .get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let start_ticks = match row.get("start_ticks").and_then(|v| v.as_str()) {
                    Some(s) => s.to_string(),
                    None if providers.contains(name.as_str()) => return Err(true),
                    None => String::new(),
                };
                let cwd = row
                    .get("cwd")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                let terminal = row
                    .get("terminal")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                if !descendants_map.contains_key(&pid) {
                    descendant_order.push(pid);
                }
                descendants_map.insert(pid, (ppid, name, start_ticks, cwd, terminal));
            }

            let origin = data
                .get("origin")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            for pid in descendant_order {
                let (ppid, name, start_ticks, cwd, terminal) = &descendants_map[&pid];
                if !providers.contains(name.as_str()) {
                    continue;
                }
                let mut cursor = *ppid;
                let mut seen = HashSet::new();
                seen.insert(pid);
                while let Some(parent) = descendants_map.get(&cursor) {
                    if seen.contains(&cursor) {
                        break;
                    }
                    seen.insert(cursor);
                    if roots.contains(&cursor) {
                        break;
                    }
                    cursor = parent.0;
                }
                if !roots.contains(&cursor) {
                    continue;
                }
                let ide_pid = cursor;
                let key = (origin.clone(), pid, start_ticks.clone(), ide_pid);
                obs.push((
                    key,
                    HistoricalRecord {
                        provider: name.clone(),
                        pid,
                        start_ticks: start_ticks.clone(),
                        ide_pid,
                        cwd: cwd.clone(),
                        terminal: terminal.clone(),
                        first_snapshot: dir_name.to_string(),
                        last_snapshot: dir_name.to_string(),
                        observations: 1,
                    },
                ));
            }
        }
    }

    Ok(ProcessHealthResult {
        dir_name: dir_name.to_string(),
        created_ts,
        obs,
    })
}

fn snapshot_health(state_dir: &Path, interval: u64, now_ts: f64) -> Result<String, ()> {
    let root = state_dir.join("snapshots");
    let _root_guard = match open(&root, DIRECTORY) {
        Ok(f) => Some(f),
        Err(e) if e.kind() == io::ErrorKind::NotFound => None,
        Err(_) => return Err(()),
    };
    let entries = fs::read_dir(&root).ok();
    let mut dir_names: Vec<String> = Vec::new();
    let mut encrypted = Vec::new();

    for entry in entries.into_iter().flatten() {
        if let Ok(e) = entry {
            let name = e.file_name().to_string_lossy().to_string();
            if !name.starts_with('.') {
                let dir_p = root.join(&name);
                if !dir_p.join("manifest.json").exists() {
                    if dir_p.join("manifest.enc").is_file() {
                        encrypted.push(name);
                    }
                } else {
                    dir_names.push(name);
                }
            }
        }
    }
    dir_names.sort();

    let num_threads = 8.min(dir_names.len().max(1));
    let chunk_size = dir_names.len().div_ceil(num_threads).max(1);

    let root_arc = Arc::new(root);
    let mut handles = Vec::new();

    for chunk in dir_names.chunks(chunk_size) {
        let chunk_vec = chunk.to_vec();
        let r_arc = root_arc.clone();
        handles.push(thread::spawn(move || {
            let mut results = Vec::new();
            for name in chunk_vec {
                let res = process_health_dir(&r_arc, &name, now_ts);
                results.push((name, res));
            }
            results
        }));
    }

    let mut snapshots: Vec<(f64, String)> = Vec::new();
    let mut invalid = 0usize;
    let mut historical_order = Vec::new();
    let mut historical: HashMap<(Option<String>, i64, String, i64), HistoricalRecord> =
        HashMap::new();

    for handle in handles {
        let results = handle.join().map_err(|_| ())?;
        {
            for (_name, res) in results {
                match res {
                    Ok(p) => {
                        snapshots.push((p.created_ts, p.dir_name));
                        for (key, rec) in p.obs {
                            if !historical.contains_key(&key) {
                                historical_order.push(key.clone());
                            }
                            let entry = historical.entry(key).or_insert_with(|| HistoricalRecord {
                                provider: rec.provider,
                                pid: rec.pid,
                                start_ticks: rec.start_ticks,
                                ide_pid: rec.ide_pid,
                                cwd: rec.cwd,
                                terminal: rec.terminal,
                                first_snapshot: rec.first_snapshot.clone(),
                                last_snapshot: rec.last_snapshot.clone(),
                                observations: 0,
                            });
                            entry.last_snapshot = rec.last_snapshot;
                            entry.observations += 1;
                        }
                    }
                    Err(true) => return Err(()),
                    Err(false) => {
                        invalid += 1;
                    }
                }
            }
        }
    }

    let newest = snapshots.iter().max_by(|a, b| {
        a.0.partial_cmp(&b.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.1.cmp(&b.1))
    });
    let age = newest.map(|n| now_ts - n.0);
    if age.is_some_and(|a| ((a * 10.0).fract().abs() - 0.5).abs() < 0.000005) {
        return Err(()); // Python owns decimal rounding at binary floating-point ties.
    }
    let max_encrypted = encrypted.iter().max();
    let newer_encrypted = !encrypted.is_empty()
        && match (max_encrypted, newest) {
            (Some(_e), None) => true,
            (Some(e), Some(n)) => e.as_str() > n.1.as_str(),
            _ => false,
        };
    let stale = if newer_encrypted {
        "null".to_string()
    } else if let Some(a) = age {
        (a > (2 * interval) as f64).to_string()
    } else {
        "true".to_string()
    };

    let freshness = if newer_encrypted {
        "\"unknown-encrypted\""
    } else {
        "\"verified-plaintext-manifest\""
    };

    let latest_snapshot_str = match newest {
        Some(n) => format!("\"{}\"", json_escape(&n.1)),
        None => "null".to_string(),
    };
    let age_str = match age {
        Some(a) => format!("{:.1}", (a * 10.0).round() / 10.0),
        None => "null".to_string(),
    };

    let mut hist_list = Vec::new();
    for key in historical_order {
        let rec = &historical[&key];
        let cwd_str = match &rec.cwd {
            Some(c) => format!("\"{}\"", json_escape(c)),
            None => "null".to_string(),
        };
        let term_str = match &rec.terminal {
            Some(t) => format!("\"{}\"", json_escape(t)),
            None => "null".to_string(),
        };
        hist_list.push(format!(
            "{{\"provider\":\"{}\",\"pid\":{},\"start_ticks\":\"{}\",\"ide_pid\":{},\"cwd\":{},\"terminal\":{},\"first_snapshot\":\"{}\",\"conversation_id\":null,\"boot_id\":null,\"observations\":{},\"last_snapshot\":\"{}\"}}",
            json_escape(&rec.provider),
            rec.pid,
            json_escape(&rec.start_ticks),
            rec.ide_pid,
            cwd_str,
            term_str,
            json_escape(&rec.first_snapshot),
            rec.observations,
            json_escape(&rec.last_snapshot)
        ));
    }

    Ok(format!(
        "{{\"verified_plain_manifests\":{},\"invalid_manifests\":{},\"latest_snapshot\":{},\"age_seconds\":{},\"stale\":{},\"freshness\":{},\"stale_threshold_seconds\":{},\"payload_hashes_verified\":false,\"encrypted_manifests\":\"not-inspected\",\"encrypted_manifest_count\":{},\"historical_ide_provider_observations\":[{}]}}",
        snapshots.len(),
        invalid,
        latest_snapshot_str,
        age_str,
        stale,
        freshness,
        2 * interval,
        encrypted.len(),
        hist_list.join(",")
    ))
}

#[derive(Debug, Clone)]
struct SnapshotSummary {
    id: String,
    created_at: Option<String>,
    profiles: Vec<String>,
    terminal_tabs_count: usize,
    gui_projects_count: usize,
    error: Option<String>,
}

fn process_preview_dir(root: &Path, dir_name: &str, origin: &str) -> SnapshotSummary {
    let dir_path = root.join(dir_name);
    let manifest_path = dir_path.join("manifest.json");
    let sha_path = dir_path.join("manifest.sha256");

    let err_unreadable = || SnapshotSummary {
        id: dir_name.to_string(),
        created_at: None,
        profiles: Vec::new(),
        terminal_tabs_count: 0,
        gui_projects_count: 0,
        error: Some("unreadable".to_string()),
    };

    let raw = match read_regular(&manifest_path, 32 * 1024 * 1024) {
        Ok(v) => v,
        Err(_) => return err_unreadable(),
    };
    let calc_hash = match sha256_digest(&raw) {
        Some(h) => h,
        None => return err_unreadable(),
    };
    let hash_bytes = match read_regular(&sha_path, 4096) {
        Ok(v) => v,
        Err(_) => return err_unreadable(),
    };
    let expected_hash = match std::str::from_utf8(&hash_bytes) {
        Ok(v) => v,
        Err(_) => return err_unreadable(),
    };
    if calc_hash != expected_hash {
        return err_unreadable();
    }

    let raw_str = match std::str::from_utf8(&raw) {
        Ok(s) => s.strip_prefix('\u{feff}').unwrap_or(s),
        Err(_) => return err_unreadable(),
    };
    let mut parser = JsonParser::new(raw_str);
    let data = match parser.parse_manifest_preview() {
        Some(d) => d,
        None if parser.unsupported => {
            let mut e = err_unreadable();
            e.error = Some("fallback".to_string());
            return e;
        }
        None => return err_unreadable(),
    };
    let mut fallback = err_unreadable();
    fallback.error = Some("fallback".to_string());
    // Delegate shapes outside the captured metadata contract to Python.
    if let Some(profiles) = data.get("profiles") {
        let profiles = match profiles.as_array() {
            Some(v) => v,
            None => return fallback,
        };
        if profiles.iter().any(|p| {
            matches!(p, JsonValue::Object(_)) && p.get("id").and_then(|v| v.as_str()).is_none()
        }) {
            return fallback;
        }
    }
    for (container, array) in [("session_hosts", "processes"), ("jetbrains", "descendants")] {
        if let Some(parent) = data.get(container) {
            if !matches!(parent, JsonValue::Object(_)) {
                return fallback;
            }
            if let Some(rows) = parent.get(array) {
                let rows = match rows.as_array() {
                    Some(r) => r,
                    None => return fallback,
                };
                for row in rows {
                    if !matches!(row, JsonValue::Object(_)) {
                        continue;
                    }
                    for field in ["provider", "terminal", "cwd"] {
                        if row
                            .get(field)
                            .is_some_and(|v| !matches!(v, JsonValue::Null | JsonValue::String(_)))
                        {
                            return fallback;
                        }
                    }
                    for field in ["role", "name"] {
                        if row
                            .get(field)
                            .is_some_and(|v| !matches!(v, JsonValue::String(_)))
                        {
                            return fallback;
                        }
                    }
                }
            }
        }
    }
    if let Some(jb) = data.get("jetbrains") {
        for field in ["open_projects", "closed_projects"] {
            if let Some(projects) = jb.get(field) {
                let projects = match projects.as_array() {
                    Some(p) => p,
                    None => return fallback,
                };
                if projects.iter().any(|v| !matches!(v, JsonValue::String(_))) {
                    return fallback;
                }
            }
        }
    }
    if std::env::var("HOME").is_err() {
        return fallback;
    }
    let bytes = dir_name.as_bytes();
    if bytes.len() != 34
        || bytes[8] != b'T'
        || bytes[21] != b'-'
        || !bytes[..8]
            .iter()
            .chain(bytes[9..21].iter())
            .all(|b| b.is_ascii_digit())
        || !bytes[22..]
            .iter()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(b))
    {
        return err_unreadable();
    }
    if data.get("schema").and_then(|v| v.as_str()) != Some("uncrash.snapshot/v1")
        || data.get("id").and_then(|v| v.as_str()) != Some(dir_name)
    {
        return err_unreadable();
    }
    if let Some(enc) = data.get("encryption").and_then(|v| v.as_str()) {
        if enc != "none" {
            return err_unreadable();
        }
    }
    if let Some(o) = data.get("origin").and_then(|v| v.as_str()) {
        if !origin.is_empty() && o != origin {
            return err_unreadable();
        }
    }
    let id = data
        .get("id")
        .and_then(|v| v.as_str())
        .unwrap_or(dir_name)
        .to_string();
    let created_at = data
        .get("created_at")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string());

    let mut profiles = Vec::new();
    if let Some(profs) = data.get("profiles").and_then(|v| v.as_array()) {
        for p in profs {
            if let Some(pid) = p.get("id").and_then(|v| v.as_str()) {
                profiles.push(pid.to_string());
            }
        }
    }

    let mut seen_tabs = HashSet::new();
    if let Some(sh) = data.get("session_hosts") {
        if let Some(processes) = sh.get("processes").and_then(|v| v.as_array()) {
            for p in processes {
                let role = p.get("role").and_then(|v| v.as_str()).unwrap_or("unknown");
                let provider = p.get("provider").and_then(|v| v.as_str());
                let terminal = p.get("terminal").and_then(|v| v.as_str());
                let home = std::env::var("HOME").unwrap_or_default();
                let cwd = p
                    .get("cwd")
                    .and_then(|v| v.as_str())
                    .filter(|v| !v.is_empty())
                    .unwrap_or(&home);
                let name = p.get("name").and_then(|v| v.as_str()).unwrap_or("terminal");

                let is_client = (role == "client" || role == "unknown")
                    && (terminal.is_some_and(|s| !s.is_empty())
                        || matches!(provider, Some("codex") | Some("agy") | Some("claude")));
                if is_client {
                    let tab_key = (
                        provider
                            .filter(|v| !v.is_empty())
                            .unwrap_or(name)
                            .to_string(),
                        cwd.to_string(),
                        terminal.map(|s| s.to_string()),
                    );
                    seen_tabs.insert(tab_key);
                }
            }
        }
    }

    if let Some(jb) = data.get("jetbrains") {
        if let Some(descendants) = jb.get("descendants").and_then(|v| v.as_array()) {
            for d in descendants {
                let term = d
                    .get("terminal")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                let cwd = d
                    .get("cwd")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                if let (Some(term), Some(cwd)) = (term, cwd) {
                    let tab_key = (
                        "jetbrains-terminal".to_string(),
                        cwd.to_string(),
                        Some(term.to_string()),
                    );
                    seen_tabs.insert(tab_key);
                }
            }
        }
    }
    let terminal_tabs_count = seen_tabs.len();

    let mut projects = HashSet::new();
    if let Some(jb) = data.get("jetbrains") {
        if let Some(open) = jb.get("open_projects").and_then(|v| v.as_array()) {
            for p in open {
                if let Some(s) = p.as_str() {
                    projects.insert(s.to_string());
                }
            }
        }
        if let Some(closed) = jb.get("closed_projects").and_then(|v| v.as_array()) {
            for p in closed {
                if let Some(s) = p.as_str() {
                    projects.insert(s.to_string());
                }
            }
        }
    }
    let gui_projects_count = projects.len();

    SnapshotSummary {
        id,
        created_at,
        profiles,
        terminal_tabs_count,
        gui_projects_count,
        error: None,
    }
}

fn list_snapshots(state_dir: &Path, origin: &str) -> Result<String, ()> {
    let root = state_dir.join("snapshots");
    let _root_guard = match open(&root, DIRECTORY) {
        Ok(f) => f,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok("[]".to_string()),
        Err(_) => return Err(()),
    };
    let entries = match fs::read_dir(&root) {
        Ok(e) => e,
        Err(_) => return Ok("[]".to_string()),
    };

    let mut valid_dirs = Vec::new();
    for entry in entries {
        if let Ok(e) = entry {
            let name = e.file_name().to_string_lossy().to_string();
            if !name.starts_with('.') {
                let dir_p = root.join(&name);
                if dir_p.is_dir() {
                    let has_enc = dir_p.join("manifest.enc").is_file();
                    let has_json = dir_p.join("manifest.json").is_file()
                        && dir_p.join("manifest.sha256").is_file();
                    if has_enc {
                        return Err(());
                    } // Python owns authenticated decryption.
                    if has_json {
                        valid_dirs.push(name);
                    }
                }
            }
        }
    }
    valid_dirs.sort();
    valid_dirs.reverse();

    let num_threads = 8.min(valid_dirs.len().max(1));
    let chunk_size = valid_dirs.len().div_ceil(num_threads).max(1);

    let root_arc = Arc::new(root);
    let mut handles = Vec::new();

    for chunk in valid_dirs.chunks(chunk_size) {
        let chunk_vec = chunk.to_vec();
        let r_arc = root_arc.clone();
        let origin = origin.to_string();
        handles.push(thread::spawn(move || {
            let mut results = Vec::new();
            for name in chunk_vec {
                let dir_p = r_arc.join(&name);
                if dir_p.join("manifest.enc").is_file() && !dir_p.join("manifest.json").is_file() {
                    results.push(SnapshotSummary {
                        id: name,
                        created_at: None,
                        profiles: Vec::new(),
                        terminal_tabs_count: 0,
                        gui_projects_count: 0,
                        error: Some("unreadable".to_string()),
                    });
                } else {
                    results.push(process_preview_dir(&r_arc, &name, &origin));
                }
            }
            results
        }));
    }

    let mut all_summaries = Vec::new();
    for handle in handles {
        let results = handle.join().map_err(|_| ())?;
        {
            all_summaries.extend(results);
        }
    }

    let mut json_items = Vec::new();
    for s in all_summaries {
        if let Some(err) = s.error {
            if err == "fallback" {
                return Err(());
            }
            json_items.push(format!(
                "{{\"id\":\"{}\",\"error\":\"{}\"}}",
                json_escape(&s.id),
                json_escape(&err)
            ));
        } else {
            let prof_json: Vec<String> = s
                .profiles
                .iter()
                .map(|p| format!("\"{}\"", json_escape(p)))
                .collect();
            let created_json = match &s.created_at {
                Some(c) => format!("\"{}\"", json_escape(c)),
                None => "null".to_string(),
            };
            json_items.push(format!(
                "{{\"id\":\"{}\",\"created_at\":{},\"profiles\":[{}],\"terminal_tabs_count\":{},\"gui_projects_count\":{}}}",
                json_escape(&s.id),
                created_json,
                prof_json.join(","),
                s.terminal_tabs_count,
                s.gui_projects_count
            ));
        }
    }

    Ok(format!("[{}]", json_items.join(",")))
}

fn run_snapshot_health(args: &[String]) -> io::Result<()> {
    if args.is_empty() {
        return Err(fail());
    }
    let state_dir = Path::new(&args[0]);
    let interval: u64 = if args.len() > 1 {
        args[1].parse().map_err(|_| fail())?
    } else {
        300
    };
    interval.checked_mul(2).ok_or_else(fail)?;
    let now_ts = if args.len() > 2 {
        parse_iso_datetime(&args[2]).ok_or_else(fail)?
    } else {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs_f64()
    };
    match snapshot_health(state_dir, interval, now_ts) {
        Ok(json) => {
            println!("{json}");
            Ok(())
        }
        Err(_) => Err(fail()),
    }
}

fn run_list_snapshots(args: &[String]) -> io::Result<()> {
    if args.is_empty() {
        return Err(fail());
    }
    let state_dir = Path::new(&args[0]);
    let origin = args.get(1).ok_or_else(fail)?;
    match list_snapshots(state_dir, origin) {
        Ok(json) => {
            println!("{json}");
            Ok(())
        }
        Err(_) => Err(fail()),
    }
}

fn collect_regular_files(dir: &Path, ext: &str, depth: usize, out: &mut Vec<PathBuf>) {
    if depth == 0 {
        return;
    }
    let entries = match fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return,
    };
    for entry in entries.flatten() {
        let p = entry.path();
        let smeta = match fs::symlink_metadata(&p) {
            Ok(m) => m,
            Err(_) => continue,
        };
        if smeta.file_type().is_symlink() {
            continue;
        }
        if smeta.is_dir() {
            collect_regular_files(&p, ext, depth - 1, out);
        } else if smeta.is_file() && p.extension().and_then(|s| s.to_str()) == Some(ext) {
            out.push(p);
        }
    }
}

fn read_first_line(path: &Path, max_len: usize) -> io::Result<Option<Vec<u8>>> {
    let mut file = open(path, NONBLOCK)?;
    let meta = file.metadata()?;
    if !meta.is_file() {
        return Err(fail());
    }
    let mut chunk = [0u8; 8192];
    let mut buf = Vec::new();
    loop {
        let to_read = chunk.len().min(max_len + 1 - buf.len());
        if to_read == 0 {
            return Ok(None);
        }
        let n = match file.read(&mut chunk[..to_read]) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        if let Some(pos) = chunk[..n].iter().position(|&b| b == b'\n') {
            buf.extend_from_slice(&chunk[..pos]);
            break;
        }
        buf.extend_from_slice(&chunk[..n]);
        if buf.len() > max_len {
            return Ok(None);
        }
    }
    Ok(Some(buf))
}

fn run_provider_inventory(args: &[String]) -> io::Result<()> {
    if args.is_empty() {
        return Err(fail());
    }
    let home = Path::new(&args[0]);
    let _home_guard = match open(home, DIRECTORY) {
        Ok(g) => g,
        Err(_) => return Err(fail()),
    };
    let meta = match fs::symlink_metadata(home) {
        Ok(m) => m,
        Err(_) => return Err(fail()),
    };
    if meta.file_type().is_symlink() || !meta.is_dir() {
        return Err(fail());
    }

    let home_arc = Arc::new(home.to_path_buf());

    // 1. Claude scan in background thread
    let home_claude = home_arc.clone();
    let claude_handle = thread::spawn(move || {
        let claude_root = home_claude.join(".claude/projects");
        let mut claude_files = Vec::new();
        if let Ok(_guard) = open(&claude_root, DIRECTORY) {
            if let Ok(meta) = fs::symlink_metadata(&claude_root) {
                if !meta.file_type().is_symlink() && meta.is_dir() {
                    collect_regular_files(&claude_root, "jsonl", 16, &mut claude_files);
                }
            }
        }
        claude_files.len()
    });

    // 2. Antigravity DB files in background thread
    let home_agy = home_arc.clone();
    let agy_handle = thread::spawn(move || {
        let agy_conv = home_agy.join(".gemini/antigravity-cli/conversations");
        let mut agy_db_stems = Vec::new();
        if let Ok(_guard) = open(&agy_conv, DIRECTORY) {
            if let Ok(meta) = fs::symlink_metadata(&agy_conv) {
                if !meta.file_type().is_symlink() && meta.is_dir() {
                    if let Ok(entries) = fs::read_dir(&agy_conv) {
                        for entry in entries.flatten() {
                            let p = entry.path();
                            if let Ok(smeta) = fs::symlink_metadata(&p) {
                                if !smeta.file_type().is_symlink() && smeta.is_file() {
                                    if p.extension().and_then(|s| s.to_str()) == Some("db") {
                                        if let Some(stem) = p.file_stem().and_then(|s| s.to_str()) {
                                            agy_db_stems.push(stem.to_string());
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        agy_db_stems
    });

    // 3. Codex sessions scan
    let codex_root = home_arc.join(".codex/sessions");
    let mut codex_files: Vec<PathBuf> = Vec::new();
    if let Ok(_guard) = open(&codex_root, DIRECTORY) {
        if let Ok(meta) = fs::symlink_metadata(&codex_root) {
            if !meta.file_type().is_symlink() && meta.is_dir() {
                collect_regular_files(&codex_root, "jsonl", 16, &mut codex_files);
            }
        }
    }

    let num_threads = 4.min(codex_files.len().max(1));
    let chunk_size = codex_files.len().div_ceil(num_threads).max(1);
    let mut worker_handles = Vec::new();

    for chunk in codex_files.chunks(chunk_size) {
        let chunk_vec = chunk.to_vec();
        worker_handles.push(thread::spawn(move || {
            let mut records = 0usize;
            let mut ids = HashSet::new();
            let mut invalid = 0usize;
            let mut labels = HashMap::new();
            for path in chunk_vec {
                let line_opt = match read_first_line(&path, 1024 * 1024) {
                    Ok(opt) => opt,
                    Err(_) => {
                        invalid += 1;
                        continue;
                    }
                };
                let line_bytes = match line_opt {
                    Some(b) => b,
                    None => {
                        invalid += 1;
                        continue;
                    }
                };
                let line_str = match std::str::from_utf8(&line_bytes) {
                    Ok(s) => s,
                    Err(_) => {
                        invalid += 1;
                        continue;
                    }
                };
                let mut parser = JsonParser::new(line_str);
                let val = match parser.parse_json() {
                    Some(v) => v,
                    None => {
                        invalid += 1;
                        continue;
                    }
                };
                if val.get("type").and_then(|v| v.as_str()) != Some("session_meta") {
                    invalid += 1;
                    continue;
                }
                let payload = match val.get("payload") {
                    Some(p) => p,
                    None => {
                        invalid += 1;
                        continue;
                    }
                };
                let sid = match payload.get("id").and_then(|v| v.as_str()) {
                    Some(s) => s,
                    None => {
                        invalid += 1;
                        continue;
                    }
                };
                records += 1;
                ids.insert(sid.to_string());
                let label = match payload.get("source").and_then(|v| v.as_str()) {
                    Some(s) => s.to_string(),
                    None => "structured-source".to_string(),
                };
                *labels.entry(label).or_insert(0usize) += 1;
            }
            (records, ids, invalid, labels)
        }));
    }

    let mut metadata_records = 0usize;
    let mut unique_ids: HashSet<String> = HashSet::new();
    let mut invalid_metadata = 0usize;
    let mut source_labels: HashMap<String, usize> = HashMap::new();

    for h in worker_handles {
        if let Ok((recs, ids, inv, lbls)) = h.join() {
            metadata_records += recs;
            unique_ids.extend(ids);
            invalid_metadata += inv;
            for (k, v) in lbls {
                *source_labels.entry(k).or_insert(0usize) += v;
            }
        }
    }

    let claude_files_count = claude_handle.join().map_err(|_| fail())?;
    let mut agy_db_stems = agy_handle.join().map_err(|_| fail())?;

    let mut labels_vec: Vec<(&String, &usize)> = source_labels.iter().collect();
    labels_vec.sort_by_key(|(k, _)| *k);
    let labels_json: Vec<String> = labels_vec
        .into_iter()
        .map(|(k, v)| format!("\"{}\":{}", json_escape(k), v))
        .collect();

    agy_db_stems.sort();
    let agy_stems_json: Vec<String> = agy_db_stems
        .iter()
        .map(|s| format!("\"{}\"", json_escape(s)))
        .collect();

    println!(
        "{{\"codex\":{{\"files\":{},\"metadata_records\":{},\"unique_ids\":{},\"invalid_metadata\":{},\"source_labels\":{{{}}},\"host_binding\":\"not-present\"}},\"claude\":{{\"jsonl_files\":{},\"conversation_ids\":\"not-enumerated\",\"host_binding\":\"not-verified\"}},\"agy_db_stems\":[{}]}}",
        codex_files.len(),
        metadata_records,
        unique_ids.len(),
        invalid_metadata,
        labels_json.join(","),
        claude_files_count,
        agy_stems_json.join(",")
    );
    Ok(())
}

fn main() -> io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 && args[1] == "--scan-panics" {
        return scan_panics(&args[2..]);
    }
    if args.len() > 1 && args[1] == "--snapshot-health" {
        return run_snapshot_health(&args[2..]);
    }
    if args.len() > 1 && args[1] == "--list-snapshots" {
        return run_list_snapshots(&args[2..]);
    }
    if args.len() > 1 && args[1] == "--provider-inventory" {
        return run_provider_inventory(&args[2..]);
    }
    let mut input = String::new();
    io::stdin()
        .take(16 * 1024 * 1024 + 1)
        .read_to_string(&mut input)?;
    if input.len() > 16 * 1024 * 1024 {
        return Err(fail());
    }
    let mut lines = input.lines();
    let header: Vec<_> = lines.next().ok_or_else(fail)?.split('\t').collect();
    if header.len() != 3 {
        return Err(fail());
    }
    let threads: usize = header[0].parse().map_err(|_| fail())?;
    if !(1..=16).contains(&threads) {
        return Err(fail());
    }
    let key = if header[1] == "-" {
        Vec::new()
    } else {
        unhex(header[1])?
    };
    if !key.is_empty() && key.len() != 32 {
        return Err(fail());
    }
    let compress = match header[2] {
        "0" => false,
        "1" => true,
        _ => return Err(fail()),
    };
    let mut jobs = VecDeque::new();
    for (index, line) in lines.enumerate() {
        if index >= 20000 {
            return Err(fail());
        }
        let f: Vec<_> = line.split('\t').collect();
        if f.len() != 10 {
            return Err(fail());
        }
        jobs.push_back((
            index,
            Job {
                src: path(f[0])?,
                dst: path(f[1])?,
                limit: f[2].parse().map_err(|_| fail())?,
                aad: unhex(f[3])?,
                cache: if f[4] == "-" { None } else { Some(path(f[4])?) },
                old_sig: if f[5] == "-" {
                    Vec::new()
                } else {
                    f[5].split(',')
                        .map(|x| x.parse().map_err(|_| fail()))
                        .collect::<io::Result<Vec<_>>>()?
                },
                old_hash: f[6].to_owned(),
                cache_size: f[7].parse().map_err(|_| fail())?,
                cache_mtime: f[8].parse().map_err(|_| fail())?,
                cache_encoding: f[9].to_owned(),
            },
        ));
    }
    let jobs = Arc::new(Mutex::new(jobs));
    let results = Arc::new(Mutex::new(Vec::new()));
    let mut workers = Vec::new();
    for _ in 0..threads {
        let q = jobs.clone();
        let r = results.clone();
        let k = key.clone();
        workers.push(thread::spawn(move || loop {
            let job = q.lock().unwrap().pop_front();
            match job {
                Some((i, j)) => {
                    let result = run(i, j, &k, compress);
                    r.lock().unwrap().push((i, result));
                }
                None => break,
            }
        }));
    }
    for w in workers {
        w.join().map_err(|_| fail())?;
    }
    let mut results = results.lock().unwrap();
    results.sort_by_key(|x| x.0);
    for (_, r) in results.iter() {
        match r {
            Ok(line) => println!("{line}"),
            Err(_) => return Err(fail()),
        }
    }
    Ok(())
}
