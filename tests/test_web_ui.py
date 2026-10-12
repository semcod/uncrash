"""Execute the shipped dashboard script without starting browsers or applications."""
import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from uncrash.web_ui import DASHBOARD_HTML


HARNESS = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map();
const element = () => ({innerHTML: '', textContent: '', value: '', children: [],
  addEventListener() {}, appendChild(child) { this.children.push(child); },
  classList: {add() {}, remove() {}}});
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
};
const calls = [], copied = [], requests = [], callbackErrors = [], boundIds = [];
const context = vm.createContext({
  document: {getElementById, createElement: element, readyState: 'loading',
    addEventListener() {}},
  window: {addEventListener() {}, location: new URL('http://localhost/'),
    history: {replaceState() {}}},
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {},
  navigator: {clipboard: {writeText: text => copied.push(text)}},
  btoa: text => {
    if ([...text].some(c => c.charCodeAt(0) > 255)) throw Error('InvalidCharacterError');
    return Buffer.from(text, 'latin1').toString('base64');
  },
  atob: text => Buffer.from(text, 'base64').toString('latin1'),
  fetch: async url => {
    requests.push(url);
    if (input.error) throw Error(input.error);
    return {json: async () => input.data};
  },
});
vm.runInContext(input.script, context, {timeout: 1000});
for (const name of ['launchNovnc', 'captureScreenshot', 'launchTabs',
                    'launchWorkspace', 'promptNewWorkspace']) {
  context[name] = (...args) => calls.push([name, ...args]);
}
(async () => {
  let error = null;
  try {
    if (input.mode === 'list') {
      context.inputSnapshots = input.data;
      vm.runInContext('snapshots = inputSnapshots; renderSnapshotList();', context);
    } else if (input.mode === 'error') {
      await context.selectSnapshot(input.data.snapshot);
    } else {
      context.renderSnapshotDetails(input.data);
      if (input.click) {
        // Exercise the actual generated inline handlers (old code) or bound closures.
        const html = getElementById('contentPane').innerHTML;
        for (const match of html.matchAll(/<button\b[^>]*\bonclick="([^"]*)"/g)) {
          if (!/^(launch|capture|prompt|copy)/.test(match[1])) continue;
          try { vm.runInContext(match[1], context, {timeout: 1000}); }
          catch (err) { callbackErrors.push(err.message); }
        }
        for (const [id, node] of nodes) {
          if (typeof node.onclick === 'function') {
            boundIds.push(id);
            node.onclick();
          }
        }
      }
    }
  } catch (err) { error = err.message; }
  process.stdout.write(JSON.stringify({error, callbackErrors, calls, copied, requests, boundIds,
    injected: !!context.injected,
    html: input.mode === 'list'
      ? getElementById('snapshotList').children.map(n => n.innerHTML).join('')
      : getElementById('contentPane').innerHTML}));
})();
"""


def execute(data, *, mode="details", click=False, error=None):
    node = shutil.which("node")
    assert node, "Dashboard execution tests require Node, present in the local CI executor"
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    run = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps(dict(script=script, data=data, mode=mode, click=click, error=error)),
        capture_output=True, text=True, timeout=10, check=True,
    )
    result = json.loads(run.stdout)
    assert result["error"] is None, result
    ids = {attrs.get("id") for _, attrs in ParsedHTML(result["html"]).tags}
    assert set(result["boundIds"]) <= ids, "Callbacks must bind existing DOM elements"
    return result


class ParsedHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


@pytest.fixture
def snapshot():
    return dict(
        snapshot="session-123", profiles=["pycharm"],
        terminal_tabs=[dict(provider="codex", terminal="pts/1", title="Terminal",
                            cwd="/home/project", resume_command="exec bash")],
        gui_projects=[dict(path="/home/project", state="open")],
        launch_script="printf 'hello'", recorded_gui_apps=[dict(name="PyCharm", pid=42, cmd="pycharm")],
        system_gpu=dict(present=True, name="GPU", driver_version="1", cuda_version="2",
                        memory_used_mb=10, memory_total_mb=20, temperature_c=30),
    )


FIELDS = [
    ("snapshot",), ("profiles", 0),
    *(("terminal_tabs", 0, name) for name in ("provider", "terminal", "title", "cwd", "resume_command")),
    *(("gui_projects", 0, name) for name in ("path", "state")),
    ("launch_script",),
    *(("recorded_gui_apps", 0, name) for name in ("name", "pid", "cmd")),
    *(("system_gpu", name) for name in ("name", "driver_version", "cuda_version", "memory_used_mb", "memory_total_mb", "temperature_c")),
]


@pytest.mark.parametrize("field", FIELDS)
def test_snapshot_fields_are_inert_text(snapshot, field):
    payload = '\"><img src=x onerror="globalThis.injected=true"><script>bad()</script>&\''
    data = copy.deepcopy(snapshot)
    target = data
    for part in field[:-1]:
        target = target[part]
    target[field[-1]] = payload
    result = execute(data)
    parsed = ParsedHTML(result["html"])
    assert not any(tag in {"img", "script"} for tag, _ in parsed.tags), field
    assert not any("onerror" in attrs for _, attrs in parsed.tags), field
    assert payload.lower() in "".join(parsed.text).lower(), field


@pytest.mark.parametrize("identifier", ["session-123", "'); globalThis.injected=true; //", '"<&\' zażółć 🐧'])
def test_snapshot_buttons_preserve_exact_identifier(snapshot, identifier):
    snapshot["snapshot"] = identifier
    result = execute(snapshot, click=True)
    assert not result["callbackErrors"]
    assert not result["injected"]
    assert result["calls"] == [
        ["launchNovnc", identifier], ["captureScreenshot", identifier],
        ["launchTabs", identifier],
        *(["launchWorkspace", identifier, False, engine]
          for engine in ("native", "kasm", "clonebox", "clonebox-container", "pelorus")),
        ["promptNewWorkspace", identifier],
    ]
    assert result["copied"] == [snapshot["launch_script"]]


def test_unicode_script_is_displayed_and_copied_exactly(snapshot):
    text = "cd '/tmp/zażółć 🐧'\nprintf '<tekst> & %s'\n"
    snapshot["launch_script"] = text
    result = execute(snapshot, click=True)
    assert text in "".join(ParsedHTML(result["html"]).text)
    assert result["copied"] == [text]


@pytest.mark.parametrize("field", ["id", "terminal_tabs_count", "gui_projects_count"])
def test_snapshot_list_fields_are_inert(field):
    payload = '<img src=x onerror="bad()">&'
    data = dict(id="session", terminal_tabs_count=2, gui_projects_count=1)
    data[field] = payload
    parsed = ParsedHTML(execute([data], mode="list")["html"])
    assert not any(tag == "img" for tag, _ in parsed.tags)
    assert payload in "".join(parsed.text)


def test_snapshot_loading_error_is_inert_and_id_is_one_url_segment(snapshot):
    from urllib.parse import quote
    snapshot["snapshot"] = "../a/b?x#y &ż"
    payload = '<img src=x onerror="bad()">'
    result = execute(snapshot, mode="error", error=payload)
    parsed = ParsedHTML(result["html"])
    assert not any(tag == "img" for tag, _ in parsed.tags)
    assert payload in "".join(parsed.text)
    assert result["requests"] == ["/api/v1/snapshots/" + quote(snapshot["snapshot"], safe="")]


def test_normal_snapshot_details_and_provider_styles(snapshot):
    result = execute(snapshot)
    parsed = ParsedHTML(result["html"])
    text = "".join(parsed.text)
    assert all(value in text for value in ["session-123", "pycharm", "CODEX", "Terminal", "/home/project", "exec bash", "PyCharm", "GPU"])
    assert any(attrs.get("class") == "tab-provider provider-codex" for _, attrs in parsed.tags)


def test_empty_snapshot_keeps_actions_and_copy_available():
    result = execute(dict(snapshot="empty"), click=True)
    text = "".join(ParsedHTML(result["html"]).text)
    assert "Brak zapisanych interaktywnych kart terminala" in text
    assert "Brak zapisanych projektów IDE" in text
    assert "# Brak zdefiniowanych tabów" in text
    assert len(result["calls"]) == 9
    assert result["copied"] == [""]


@pytest.mark.parametrize("provider", ["agy", "claude", None, "unknown"])
def test_provider_label_and_safe_style(snapshot, provider):
    snapshot["terminal_tabs"][0]["provider"] = provider
    parsed = ParsedHTML(execute(snapshot)["html"])
    style = provider if provider in {"agy", "claude"} else "shell"
    assert any(attrs.get("class") == "tab-provider provider-" + style for _, attrs in parsed.tags)
    assert (provider.upper() if provider else "SHELL") in "".join(parsed.text)


def test_testwins_ux_styles_and_shortcuts_bar():
    assert ":focus-visible" in DASHBOARD_HTML
    assert "prefers-reduced-motion" in DASHBOARD_HTML
    assert "status-pulse" in DASHBOARD_HTML
    assert "shortcutsBar" in DASHBOARD_HTML
    assert "novnc-container.fullscreen" in DASHBOARD_HTML
    assert "workspace-search-input" in DASHBOARD_HTML
    assert "workspace-filter-pills" in DASHBOARD_HTML
    assert "workspace-details-disclosure" in DASHBOARD_HTML
    assert "novnc-loader" in DASHBOARD_HTML


def test_testwins_ux_workspaces_bar_rendering():
    node = shutil.which("node")
    assert node
    test_script = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
const element = () => ({innerHTML: '', textContent: '', value: '', style: {}, children: [],
  addEventListener() {}, appendChild(child) { this.children.push(child); },
  classList: {add() {}, remove() {}, toggle() {}},
  querySelectorAll() { return []; }});
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
};
const context = vm.createContext({
  document: {getElementById, querySelectorAll: () => [], createElement: element, readyState: 'loading', addEventListener() {}},
  window: {addEventListener() {}, location: new URL('http://localhost/'), history: {replaceState() {}}},
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {}, navigator: {clipboard: {writeText() {}}}
});
const script = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(script, context);
vm.runInContext('activeWorkspaces = [{workspace_id: "ws-uncrash", name: "Uncrash", engine: "native", tabs_count: 3, terminal_tabs: [{name: "codex", provider: "codex"}]}, {workspace_id: "ws-twinerd", name: "Twinerd", engine: "native", tabs_count: 2, terminal_tabs: [{name: "shell", provider: "shell"}]}]; renderWorkspacesBar();', context);
const chipsHtml = getElementById('workspacesChips').innerHTML;
const barDisplay = getElementById('workspacesBar').style.display;
const shortcutsDisplay = getElementById('shortcutsBar').style.display;

// Test filter query
getElementById('workspaceSearchInput').value = 'Twinerd';
vm.runInContext('renderWorkspacesBar();', context);
const filteredChipsHtml = getElementById('workspacesChips').innerHTML;

// Test empty state
getElementById('workspaceSearchInput').value = 'nonexistent-project-xyz';
vm.runInContext('renderWorkspacesBar();', context);
const emptyChipsHtml = getElementById('workspacesChips').innerHTML;

process.stdout.write(JSON.stringify({chipsHtml, barDisplay, shortcutsDisplay, filteredChipsHtml, emptyChipsHtml}));
"""
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        temp_js = f.name
    try:
        run = subprocess.run([node, "-e", test_script, temp_js], capture_output=True, text=True, check=True)
        out = json.loads(run.stdout)
        assert out["barDisplay"] == "flex"
        assert out["shortcutsDisplay"] == "flex"
        assert "kbd-hint" in out["chipsHtml"]
        assert "Uncrash" in out["chipsHtml"]
        assert "Twinerd" in out["chipsHtml"]
        assert "Twinerd" in out["filteredChipsHtml"]
        assert "Uncrash" not in out["filteredChipsHtml"]
        assert "workspaces-empty-hint" in out["emptyChipsHtml"]
    finally:
        os.unlink(temp_js)


def test_testwins_ux_progressive_disclosure_rendering():
    node = shutil.which("node")
    assert node
    test_script = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
const element = () => ({innerHTML: '', textContent: '', value: '', style: {}, children: [],
  addEventListener() {}, appendChild(child) { this.children.push(child); },
  classList: {add() {}, remove() {}, toggle() {}},
  querySelectorAll() { return []; }});
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
};
const context = vm.createContext({
  document: {getElementById, querySelectorAll: () => [], createElement: element, readyState: 'loading', addEventListener() {}},
  window: {addEventListener() {}, location: new URL('http://localhost/'), history: {replaceState() {}}},
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {}, navigator: {clipboard: {writeText() {}}}
});
const script = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(script, context);
vm.runInContext(`
  renderWorkspacePreview({
    workspace_id: "ws-uncrash",
    name: "Uncrash",
    display: ":183",
    ws_port: 6100,
    rfb_port: 5900,
    novnc_url: "http://127.0.0.1:6100/vnc.html",
    project_path: "/home/tom/github/semcod/uncrash",
    engine: "native",
    tabs_count: 2,
    terminal_tabs: [
      {name: "codex", provider: "codex", command: "codex resume 01a126f1"},
      {name: "shell", provider: "shell", command: "exec bash"}
    ]
  });
`, context);
const previewHtml = getElementById('previewArea').innerHTML;
process.stdout.write(JSON.stringify({previewHtml}));
"""
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        temp_js = f.name
    try:
        run = subprocess.run([node, "-e", test_script, temp_js], capture_output=True, text=True, check=True)
        out = json.loads(run.stdout)
        html = out["previewHtml"]
        assert "workspace-details-disclosure" in html
        assert "novncLoader" in html
        assert "codex resume 01a126f1" in html
        assert "exec bash" in html
        assert "/home/tom/github/semcod/uncrash" in html
    finally:
        os.unlink(temp_js)


WORKSPACE_PREVIEW_HARNESS = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map();
function element() {
  const classes = new Set();
  return {innerHTML:'',textContent:'',style:{},children:[],addEventListener(){},
    appendChild(child){this.children.push(child)},
    classList:{add(x){classes.add(x)},remove(x){classes.delete(x)},contains(x){return classes.has(x)},
      toggle(x){if(classes.has(x)){classes.delete(x);return false}classes.add(x);return true}}};
}
const getElementById = id => {if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)};
const callbacks = [];
const context = vm.createContext({
  document:{getElementById,createElement:element,readyState:'loading',addEventListener(){},
    querySelector(){return getElementById('container')}},
  window:{addEventListener(kind,callback){callbacks.push([kind,callback])},
    location:new URL('http://localhost/'),history:{replaceState(){}}},
  URL,URLSearchParams,console,setTimeout(){},setInterval(){},
  navigator:{clipboard:{writeText(){}}}
});
vm.runInContext(input.script,context);
context.workspace = input.workspace;
vm.runInContext('renderWorkspacePreview(workspace)',context);
process.stdout.write(JSON.stringify({html:getElementById('previewArea').innerHTML,
  fullscreenBefore:getElementById('container').classList.contains('fullscreen')}));
"""


@pytest.mark.parametrize('field', ['name', 'title', 'provider'])
@pytest.mark.parametrize('text', [
    'Ordinary terminal', '<img src=x onerror="window.reviewProbe=1">',
    'Terminal <one> & "two"', 'Zażółć 🧪',
    '</strong><svg onload="window.reviewProbe=1"></svg><strong>',
])
def test_workspace_preview_preserves_tab_title_as_text(field, text):
    node = shutil.which('node')
    assert node, 'Workspace preview regression requires Node'
    workspace = dict(workspace_id='owned-review', engine='native', display=':1',
                     ws_port=6080, rfb_port=5900,
                     novnc_url='http://127.0.0.1:6080/vnc.html',
                     terminal_tabs=[{field: text}])
    script = DASHBOARD_HTML.split('<script>', 1)[1].split('</script>', 1)[0]
    run = subprocess.run([node, '-e', WORKSPACE_PREVIEW_HARNESS],
        input=json.dumps({'script': script, 'workspace': workspace}),
        capture_output=True, text=True, timeout=10, check=True)
    parsed = ParsedHTML(json.loads(run.stdout)['html'])
    expected = text.upper() if field == 'provider' else text
    assert expected in ''.join(parsed.text)
    assert all(tag not in {'img', 'svg'} for tag, _ in parsed.tags)
    # Controls render only the fixed toolbar handlers, never tab-supplied ones.
    assert all('onerror' not in attrs and 'onload' not in attrs for _, attrs in parsed.tags)


def test_workspace_preview_copy_url_handler_raw_and_safe():
    node = shutil.which("node")
    assert node, "Test requires Node.js"
    test_script = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
const listeners = new Map();
const copied = [];
const element = id => {
  const classes = new Set();
  return {
    id, innerHTML: '', textContent: '', value: '', style: {}, children: [],
    addEventListener(kind, cb) {
      if (!listeners.has(id)) listeners.set(id, new Map());
      listeners.get(id).set(kind, cb);
    },
    click() {
      const cb = listeners.get(id)?.get('click');
      if (cb) cb();
    },
    appendChild(child) { this.children.push(child); },
    classList: { add(x){classes.add(x)}, remove(x){classes.delete(x)}, contains(x){return classes.has(x)} },
    querySelectorAll() { return []; }
  };
};
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element(id));
  return nodes.get(id);
};
const context = vm.createContext({
  document: { getElementById, querySelectorAll: () => [], createElement: element, readyState: 'loading', addEventListener() {} },
  window: { addEventListener() {}, location: new URL('http://localhost/'), history: { replaceState() {} } },
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {},
  navigator: { clipboard: { writeText: t => copied.push(t) } }
});
const script = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(script, context);
const testUrl = "http://127.0.0.1:6080/vnc.html?token=it's-a-key&test=\"quoted\"&unicode=Zażółć🧪";
vm.runInContext(`
  renderWorkspacePreview({
    workspace_id: "ws-test",
    name: "Test",
    display: ":1",
    ws_port: 6080,
    rfb_port: 5900,
    novnc_url: ${JSON.stringify(testUrl)},
    engine: "native",
    terminal_tabs: []
  });
`, context);

const previewHtml = getElementById('previewArea').innerHTML;
const hasInlineOnclick = /<button[^>]*id="copyWorkspaceUrlBtn"[^>]*onclick=/i.test(previewHtml);

getElementById('copyWorkspaceUrlBtn').click();

process.stdout.write(JSON.stringify({ copied, hasInlineOnclick }));
"""
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        temp_js = f.name
    try:
        run = subprocess.run([node, "-e", test_script, temp_js], capture_output=True, text=True, check=True)
        out = json.loads(run.stdout)
        expected_url = "http://127.0.0.1:6080/vnc.html?token=it's-a-key&test=\"quoted\"&unicode=Zażółć🧪"
        assert out["hasInlineOnclick"] is False
        assert out["copied"] == [expected_url]
    finally:
        os.unlink(temp_js)


@pytest.mark.parametrize("query", ["shell", ""])
@pytest.mark.parametrize("refresh_empty", [False, True])
def test_digit_shortcuts_align_with_filtered_workspaces(query, refresh_empty):
    node = shutil.which("node")
    assert node, "Test requires Node.js"
    test_script = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
const listeners = new Map();
let selectedWorkspace = null;
const windowListeners = new Map();

const element = id => {
  const classes = new Set();
  return {
    id, innerHTML: '', textContent: '', value: '', style: {}, children: [],
    addEventListener(kind, cb) {
      if (!listeners.has(id)) listeners.set(id, new Map());
      listeners.get(id).set(kind, cb);
    },
    appendChild(child) { this.children.push(child); },
    classList: { add(x){classes.add(x)}, remove(x){classes.delete(x)}, toggle(){}, contains(x){return classes.has(x)} },
    querySelectorAll() { return []; }
  };
};
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element(id));
  return nodes.get(id);
};
const context = vm.createContext({
  document: { getElementById, querySelectorAll: () => [], createElement: element, readyState: 'loading', addEventListener() {} },
  window: {
    addEventListener(kind, cb) { windowListeners.set(kind, cb); },
    location: new URL('http://localhost/'), history: { replaceState() {} }
  },
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {},
  navigator: { clipboard: { writeText() {} } }
});
const script = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(script, context);
vm.runInContext(`
  activeWorkspaces = [
    {workspace_id: "ws-codex", name: "Codex", engine: "native", tabs_count: 1, terminal_tabs: [{name: "codex", provider: "codex"}]},
    {workspace_id: "ws-shell", name: "Shell", engine: "native", tabs_count: 1, terminal_tabs: [{name: "shell", provider: "shell"}]}
  ];
  selectWorkspace = id => { selectedWorkspace = id; };
`, context);

// Render a nonempty inventory, with or without a search filter.
getElementById('workspaceSearchInput').value = process.argv[2];
vm.runInContext('renderWorkspacesBar();', context);

if (process.argv[3] === 'true') {
  vm.runInContext('activeWorkspaces = []; renderWorkspacesBar();', context);
}

// Trigger keydown '1' after the optional inventory refresh.
let prevented = false;
const keydownCb = windowListeners.get('keydown');
keydownCb({ key: '1', ctrlKey: false, metaKey: false, altKey: false, preventDefault() { prevented = true; } });

process.stdout.write(JSON.stringify({
  selectedWorkspace: context.selectedWorkspace ?? null,
  prevented,
  barDisplay: getElementById('workspacesBar').style.display
}));
"""
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(script)
        temp_js = f.name
    try:
        run = subprocess.run(
            [node, "-e", test_script, temp_js, query, json.dumps(refresh_empty)],
            capture_output=True, text=True, check=True,
        )
        out = json.loads(run.stdout)
        expected = None if refresh_empty else ("ws-shell" if query else "ws-codex")
        assert out["selectedWorkspace"] == expected
        assert out["prevented"] is (not refresh_empty)
        if refresh_empty:
            assert out["barDisplay"] == "none"
    finally:
        os.unlink(temp_js)





WORKSPACE_BAR_HARNESS = r"""
const vm = require('node:vm'), fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map(), selected = [], closed = [], listeners = {};
const attr = (tag, name) => tag.match(new RegExp('\\b'+name+'="([^"]*)"'))?.[1];
let markup = '', targets = [], stopped = false;
const fixed = ['workspacesBar', 'shortcutsBar', 'workspacesChips', 'workspaceSearchInput', 'searchInput', 'workspacesCountBadge', 'wsWrapModeBtn', 'wsScrollModeBtn'];
const node = id => {
  const classes = new Set();
  return {
    id, value:'', style:{}, innerHTML:'', textContent:'', addEventListener(){},
    classes,
    classList:{
      add(cls){ classes.add(cls); },
      remove(cls){ classes.delete(cls); },
      toggle(cls, force){
        if (force === undefined) { if (classes.has(cls)) classes.delete(cls); else classes.add(cls); }
        else if (force) classes.add(cls);
        else classes.delete(cls);
      },
      contains(cls){ return classes.has(cls); }
    }
  };
};
for (const id of fixed) {
  nodes.set(id, node(id));
}
const chips = nodes.get('workspacesChips');
Object.defineProperty(chips, 'innerHTML', {
  get: () => markup,
  set: value => {
    markup = value; targets = [];
    for (const id of [...nodes.keys()]) {
      if (!fixed.includes(id)) nodes.delete(id);
    }
    for (const match of markup.matchAll(/<[a-z][\w-]*\b[^>]*>/gi)) {
      const tag = match[0], id = attr(tag, 'id');
      const element = node(id);
      element.inline = attr(tag, 'onclick');
      element.classes = (attr(tag, 'class') || '').split(/\s+/);
      if (id) nodes.set(id, element);
      if (element.classes.includes('workspace-chip') || element.classes.includes('chip-close')) targets.push(element);
    }
  }
});
const context = vm.createContext({
  document:{readyState:'loading',activeElement:{tagName:'BODY'},addEventListener(){},
    getElementById: id => nodes.get(id) || null},
  window:{addEventListener:(kind,fn) => listeners[kind]=fn, location:new URL('http://localhost/'),history:{replaceState(){}}},
  URL, URLSearchParams, console, setTimeout(){}, setInterval(){},
  localStorage:{
    _items: {},
    getItem(k){ return this._items[k] || null; },
    setItem(k, v){ this._items[k] = String(v); }
  }
});
vm.runInContext(input.script, context, {timeout:1000});
context.showToast = () => {};
context.selectWorkspace = id => selected.push(id);
context.closeWorkspace = id => closed.push(id);
context.items = input.workspaces;
vm.runInContext('activeWorkspaces = items;', context);
nodes.get('workspaceSearchInput').value = input.query;
if (input.wrapMode) {
  context.setWorkspacesWrapMode(input.wrapMode);
}
context.renderWorkspacesBar();
let error = null;
const event = {stopPropagation(){stopped = true;}};
const invoke = target => {
  if (!target) throw Error('No rendered action target');
  if (typeof target.onclick === 'function') target.onclick(event);
  else if (target.inline) {context.event=event;vm.runInContext(target.inline,context,{timeout:1000});}
  else throw Error('Rendered action has no handler');
};
try {
  if (input.click) {
    const parent = targets.filter(n => n.classes.includes('workspace-chip'))[0];
    if (input.click === 'close') {
      invoke(targets.filter(n => n.classes.includes('chip-close'))[0]);
      if (!stopped) invoke(parent);
    } else invoke(parent);
  }
  if (input.key) listeners.keydown({key:input.key,ctrlKey:false,metaKey:false,altKey:false,preventDefault(){}});
} catch(err) {error=err.message;}
process.stdout.write(JSON.stringify({
  html: markup,
  selected,
  closed,
  stopped,
  error,
  injected: !!context.injected,
  countBadge: nodes.get('workspacesCountBadge')?.textContent || '',
  chipsClasses: Array.from(chips.classes),
  wrapBtnActive: nodes.get('wsWrapModeBtn')?.classes.has('active'),
  scrollBtnActive: nodes.get('wsScrollModeBtn')?.classes.has('active')
}));
"""


def execute_workspace_bar(workspaces, *, query="", click=None, key=None, wrap_mode=None):
    node = shutil.which("node")
    assert node, "Workspace bar execution tests require Node"
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    run = subprocess.run(
        [node, "-e", WORKSPACE_BAR_HARNESS],
        input=json.dumps(dict(script=script, workspaces=workspaces, query=query, click=click, key=key, wrapMode=wrap_mode)),
        capture_output=True, text=True, timeout=10,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def workspace_chip(**overrides):
    result = dict(workspace_id="ws-test", name="Workspace", engine="native", display=":1", tabs_count=0)
    result.update(overrides)
    return result


@pytest.mark.parametrize("field", ["name", "workspace_id", "display"])
@pytest.mark.parametrize("text", [
    "Normal label",
    '<img src=x onerror="globalThis.injected=true">',
    '<svg onload="globalThis.injected=true"></svg>',
    'Projekt Żółć 🧪 O\'Reilly "quoted" & < >',
])
def test_workspace_chip_metadata_is_literal_text(field, text):
    ws = workspace_chip(**{field:text})
    if field == "workspace_id":
        ws["name"] = ""
    result = execute_workspace_bar([ws])
    assert result["error"] is None
    parsed = ParsedHTML(result["html"])
    assert text in "".join(parsed.text)
    assert not any(tag in {"img", "svg", "script"} for tag, _ in parsed.tags)
    assert all("onerror" not in attrs and "onload" not in attrs for _, attrs in parsed.tags)


@pytest.mark.parametrize("workspace_id", [
    "ws-test", "O'Reilly Żółć 🧪", "x');globalThis.injected=true;//",
])
@pytest.mark.parametrize("click", ["select", "close"])
def test_workspace_chip_callbacks_keep_raw_ids_and_close_stops_selection(workspace_id, click):
    result = execute_workspace_bar([workspace_chip(workspace_id=workspace_id)], click=click)
    assert result["error"] is None
    assert not result["injected"]
    assert result["selected"] == ([workspace_id] if click == "select" else [])
    assert result["closed"] == ([workspace_id] if click == "close" else [])
    assert result["stopped"] is (click == "close")
    parsed = ParsedHTML(result["html"])
    assert all("onclick" not in attrs for _, attrs in parsed.tags)


@pytest.mark.parametrize("click,key", [("select", None), ("close", None), (None, "1")])
def test_workspace_chip_actions_match_first_visible_filtered_item(click, key):
    workspaces = [workspace_chip(workspace_id="codex-first", name="Codex"),
                  workspace_chip(workspace_id="shell-second", name="Shell")]
    result = execute_workspace_bar(workspaces, query="shell", click=click, key=key)
    assert result["error"] is None
    assert result["selected"] == ([] if click == "close" else ["shell-second"])
    assert result["closed"] == (["shell-second"] if click == "close" else [])
    assert 'Codex' not in result["html"]
    assert '<span class="kbd-hint">1</span>' in result["html"]


def test_workspace_tabs_bar_wrap_mode_and_counter_badge():
    workspaces = [
        workspace_chip(workspace_id="ws-1", name="Uncrash", terminal_tabs=[dict(name="codex", provider="codex")]),
        workspace_chip(workspace_id="ws-2", name="Twinerd", terminal_tabs=[dict(name="shell", provider="shell")]),
    ]
    # Default is wrap mode, count badge is 2
    res_default = execute_workspace_bar(workspaces)
    assert res_default["error"] is None
    assert "wrap-mode" in res_default["chipsClasses"]
    assert res_default["wrapBtnActive"] is True
    assert res_default["countBadge"] == "2"

    # Switch to scroll mode
    res_scroll = execute_workspace_bar(workspaces, wrap_mode="scroll")
    assert res_scroll["error"] is None
    assert "scroll-mode" in res_scroll["chipsClasses"]
    assert res_scroll["scrollBtnActive"] is True

    # Filtered query updates count badge to 1/2
    res_filtered = execute_workspace_bar(workspaces, query="Twinerd")
    assert res_filtered["error"] is None
    assert res_filtered["countBadge"] == "1/2"


def test_workspace_chip_deduplication_of_backend_tag():
    ws = workspace_chip(workspace_id="ws-uncrash", name="Uncrash [Twinerd NATIVE]")
    res = execute_workspace_bar([ws])
    assert res["error"] is None
    parsed = ParsedHTML(res["html"])
    # The title inside the chip must be deduplicated
    assert "Uncrash" in "".join(parsed.text)
    assert "Uncrash [Twinerd NATIVE]" not in "".join(parsed.text)
    # The full metadata is kept in the tooltip
    assert any("Uncrash [Twinerd NATIVE]" in attrs.get("title", "") for _, attrs in parsed.tags)


def test_workspace_keyboard_shortcut_key_zero_for_tenth_workspace():
    workspaces = [
        workspace_chip(workspace_id=f"ws-{i}", name=f"Workspace {i}")
        for i in range(10)
    ]
    res = execute_workspace_bar(workspaces, key="0")
    assert res["error"] is None
    # Key 0 must select the 10th workspace (ws-9)
    assert res["selected"] == ["ws-9"]
    # The 10th chip must have kbd-hint '0'
    assert '<span class="kbd-hint">0</span>' in res["html"]


APPS_CATALOG_HARNESS = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));

const nodes = new Map();
const classes = new Map();
const makeElement = (id) => {
  const el = {
    id,
    _html: '',
    textContent: '',
    value: '',
    style: {},
    children: [],
    options: [],
    set innerHTML(val) {
      this._html = val;
      if (id === 'appTargetWorkspaceSelect') {
        this.options = [];
        for (const m of val.matchAll(/<option\b[^>]*value="([^"]*)"/g)) {
          this.options.push({ value: m[1] });
        }
      }
      if (id === 'appsGrid') {
        for (const m of val.matchAll(/id="([^"]*)"/g)) {
          if (!nodes.has(m[1])) nodes.set(m[1], makeElement(m[1]));
        }
      }
    },
    get innerHTML() { return this._html || ''; },
    classList: {
      add(cls) {
        if (!classes.has(id)) classes.set(id, new Set());
        classes.get(id).add(cls);
      },
      remove(cls) {
        if (classes.has(id)) classes.get(id).delete(cls);
      },
      toggle(cls, force) {
        if (!classes.has(id)) classes.set(id, new Set());
        const s = classes.get(id);
        if (force === undefined) {
          if (s.has(cls)) s.delete(cls); else s.add(cls);
        } else if (force) {
          s.add(cls);
        } else {
          s.delete(cls);
        }
      },
      contains(cls) {
        return classes.has(id) && classes.get(id).has(cls);
      }
    },
    addEventListener() {},
    appendChild(child) { this.children.push(child); }
  };
  return el;
};

const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, makeElement(id));
  return nodes.get(id);
};

const fixedIds = [
  'appsModal', 'appsSearchInput', 'appFilterInput', 'appsGrid',
  'appsViewGridBtn', 'appsViewTableBtn', 'appTargetWorkspaceSelect',
  'previewArea', 'modalTotalApps', 'modalRecoverableApps', 'categoryPills', 'toast'
];
fixedIds.forEach(id => getElementById(id));

let copied = [];
let fetchCalls = [];
let toasts = [];
let selectedWorkspaces = [];

const context = vm.createContext({
  document: {
    readyState: 'loading',
    getElementById,
    createElement: id => makeElement(id),
    addEventListener() {}
  },
  window: {
    addEventListener() {},
    location: new URL('http://localhost/?modal=apps'),
    history: { replaceState() {} }
  },
  URL,
  URLSearchParams,
  console,
  setTimeout() {},
  setInterval() {},
  navigator: { clipboard: { writeText: text => copied.push(text) } },
  fetch: async (url, opts) => {
    fetchCalls.push({ url, opts });
    if (url.includes('/workspace?')) {
      return {
        ok: true,
        json: async () => ({
          workspace_id: 'ws-new-launched',
          engine: 'native',
          status: 'running'
        })
      };
    }
    return { ok: true, json: async () => ({ status: 'launched', workspace_id: 'ws-target' }) };
  },
  Array
});

vm.runInContext(input.script, context, { timeout: 1000 });

context.showToast = (msg) => toasts.push(msg);
context.selectWorkspace = (id) => selectedWorkspaces.push(id);
context.renderWorkspacePreview = (ws) => {};
context.fetchWorkspaces = async () => {};

(async () => {
  let error = null;
  try {
    context.rawApps = input.applicationsData;
    context.rawWs = input.activeWorkspaces || [];
    context.rawCurWs = input.currentWorkspaceId || null;
    vm.runInContext('applicationsData = rawApps; activeWorkspaces = rawWs; currentWorkspaceId = rawCurWs;', context);

    if (input.viewMode) {
      context.setAppsViewMode(input.viewMode);
    }
    context.populateAppTargetWorkspaces();
    if (input.targetWorkspace) {
      getElementById('appTargetWorkspaceSelect').value = input.targetWorkspace;
    }
    context.renderFilteredApps();

    if (input.clickId) {
      const target = getElementById(input.clickId);
      if (target && typeof target.onclick === 'function') {
        await target.onclick();
      }
    }
  } catch (err) {
    error = err.message + '\n' + err.stack;
  }

  const gridHtml = getElementById('appsGrid').innerHTML;
  const selectHtml = getElementById('appTargetWorkspaceSelect').innerHTML;
  const gridClasses = Array.from(classes.get('appsViewGridBtn') || []);
  const tableClasses = Array.from(classes.get('appsViewTableBtn') || []);

  process.stdout.write(JSON.stringify({
    error,
    gridHtml,
    selectHtml,
    gridClasses,
    tableClasses,
    copied,
    fetchCalls,
    toasts,
    selectedWorkspaces
  }));
})();
"""


def execute_apps_catalog(applications_data, *, active_workspaces=None, current_workspace_id=None,
                         target_workspace=None, view_mode=None, click_id=None):
    node = shutil.which("node")
    assert node, "Applications catalog execution tests require Node"
    script = DASHBOARD_HTML.split("<script>", 1)[1].split("</script>", 1)[0]
    payload = {
        "script": script,
        "applicationsData": applications_data,
        "activeWorkspaces": active_workspaces or [],
        "currentWorkspaceId": current_workspace_id,
        "targetWorkspace": target_workspace,
        "viewMode": view_mode,
        "clickId": click_id
    }
    run = subprocess.run(
        [node, "-e", APPS_CATALOG_HARNESS],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_apps_catalog_view_mode_toggle_grid_and_table():
    apps_data = {
        "total_installed": 1,
        "categories": {
            "jetbrains": {
                "label": "JetBrains IDE",
                "apps": [{
                    "id": "gateway",
                    "name": "Gateway 2026.2.2",
                    "cmd": "/path/to/gateway",
                    "category": "jetbrains",
                    "has_recovery_profile": True,
                    "profile_id": "jetbrains-settings",
                    "desktop_file": "/home/tom/.local/share/applications/jetbrains-gateway.desktop"
                }]
            }
        }
    }

    # 1. Table view mode
    res_table = execute_apps_catalog(apps_data, view_mode="table")
    assert res_table["error"] is None
    assert "active" in res_table["tableClasses"]
    assert "active" not in res_table["gridClasses"]
    assert '<table class="apps-table">' in res_table["gridHtml"]
    assert "Aplikacja" in res_table["gridHtml"]
    assert "Profil odzyskiwania" in res_table["gridHtml"]
    assert "Polecenie CLI / Ścieżka" in res_table["gridHtml"]
    assert "Plik Desktop" in res_table["gridHtml"]
    assert "Opcje akcji" in res_table["gridHtml"]
    assert "Gateway 2026.2.2" in res_table["gridHtml"]
    assert "jetbrains-settings" in res_table["gridHtml"]
    assert "app-launch-0" in res_table["gridHtml"]
    assert "app-copy-0" in res_table["gridHtml"]

    # 2. Grid view mode
    res_grid = execute_apps_catalog(apps_data, view_mode="grid")
    assert res_grid["error"] is None
    assert "active" in res_grid["gridClasses"]
    assert "active" not in res_grid["tableClasses"]
    assert '<div class="app-card">' in res_grid["gridHtml"]
    assert '<div class="app-card-actions">' in res_grid["gridHtml"]
    assert "Gateway 2026.2.2" in res_grid["gridHtml"]
    assert "app-launch-0" in res_grid["gridHtml"]
    assert "app-copy-0" in res_grid["gridHtml"]


def test_apps_catalog_target_workspaces_population():
    apps_data = {"total_installed": 0, "categories": {}}
    workspaces = [
        {"workspace_id": "ws-1", "name": "PyCharm Host", "display": ":183"},
        {"workspace_id": "ws-2", "name": "Terminal Box", "display": ":184"},
    ]
    res = execute_apps_catalog(apps_data, active_workspaces=workspaces, current_workspace_id="ws-2")
    assert res["error"] is None
    select_html = res["selectHtml"]
    assert '__new__' in select_html
    assert '✨ Nowy workspace (kolejna maszyna)' in select_html
    assert 'ws-1' in select_html
    assert 'PyCharm Host' in select_html
    assert '(:183)' in select_html
    assert 'ws-2' in select_html
    assert 'selected' in select_html


def test_apps_catalog_launch_in_new_workspace():
    apps_data = {
        "total_installed": 1,
        "categories": {
            "jetbrains": {
                "apps": [{
                    "id": "pycharm",
                    "name": "PyCharm EAP",
                    "cmd": "/opt/pycharm/bin/pycharm",
                    "category": "jetbrains",
                    "has_recovery_profile": True,
                    "profile_id": "jetbrains-settings"
                }]
            }
        }
    }
    res = execute_apps_catalog(apps_data, target_workspace="__new__", click_id="app-launch-0")
    assert res["error"] is None
    assert len(res["fetchCalls"]) >= 1
    call = res["fetchCalls"][0]
    assert "/api/v1/snapshots/" in call["url"]
    assert "workspace?" in call["url"]
    assert "force_new=true" in call["url"]
    assert "app_name=PyCharm+EAP" in call["url"] or "app_name=PyCharm%20EAP" in call["url"]
    assert "app_cmd=" in call["url"]


def test_apps_catalog_launch_in_existing_workspace():
    apps_data = {
        "total_installed": 1,
        "categories": {
            "cli": {
                "apps": [{
                    "id": "tmux",
                    "name": "Tmux Terminal",
                    "cmd": "tmux new-session -A -s main",
                    "category": "code_terminals",
                    "has_recovery_profile": False
                }]
            }
        }
    }
    workspaces = [{"workspace_id": "ws-target-42", "name": "Dev Machine"}]
    res = execute_apps_catalog(
        apps_data,
        active_workspaces=workspaces,
        target_workspace="ws-target-42",
        click_id="app-launch-0"
    )
    assert res["error"] is None
    assert any("/api/v1/workspaces/ws-target-42/launch-app" in c["url"] for c in res["fetchCalls"])
    launch_call = next(c for c in res["fetchCalls"] if "/launch-app" in c["url"])
    body = json.loads(launch_call["opts"]["body"])
    assert body["name"] == "Tmux Terminal"
    assert body["cmd"] == "tmux new-session -A -s main"
    assert "ws-target-42" in res["selectedWorkspaces"]


def test_apps_catalog_copy_command():
    apps_data = {
        "total_installed": 1,
        "categories": {
            "jetbrains": {
                "apps": [{
                    "id": "idea",
                    "name": "IntelliJ IDEA",
                    "cmd": "/opt/idea/bin/idea.sh",
                    "category": "jetbrains"
                }]
            }
        }
    }
    res = execute_apps_catalog(apps_data, click_id="app-copy-0")
    assert res["error"] is None
    assert res["copied"] == ["/opt/idea/bin/idea.sh"]
    assert any("Skopiowano" in t for t in res["toasts"])


def test_apps_catalog_xss_sanitization():
    xss_app = {
        "id": "xss",
        "name": '<img src=x onerror="alert(1)">',
        "cmd": 'echo "hello"; <script>evil()</script>',
        "category": "jetbrains",
        "has_recovery_profile": True,
        "profile_id": '"><script>evil()</script>',
        "desktop_file": '/path/to/<svg onload="evil()">.desktop'
    }
    apps_data = {"total_installed": 1, "categories": {"jetbrains": {"apps": [xss_app]}}}

    for mode in ["grid", "table"]:
        res = execute_apps_catalog(apps_data, view_mode=mode)
        assert res["error"] is None
        html = res["gridHtml"]
        parsed = ParsedHTML(html)
        assert not any(tag in {"img", "script", "svg"} for tag, _ in parsed.tags)
        assert all("onerror" not in attrs and "onload" not in attrs for _, attrs in parsed.tags)

