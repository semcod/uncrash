//! Linux snapshot worker: stable reads, OpenSSL SHA256/AES-GCM, zlib, COW/cached copies.
//! Private stdin protocol; stdout contains metadata only. No shell or network execution.
use std::{
    collections::VecDeque,
    ffi::{c_int, c_ulong, c_void, CString},
    fs::{File, Metadata},
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
fn main() -> io::Result<()> {
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
