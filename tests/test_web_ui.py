"""Execute the shipped dashboard script without starting browsers or applications."""
import copy
from html.parser import HTMLParser
import json
import shutil
import subprocess

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


def test_testwins_ux_workspaces_bar_rendering():
    node = shutil.which("node")
    assert node
    test_script = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const nodes = new Map();
const element = () => ({innerHTML: '', textContent: '', value: '', style: {}, children: [],
  addEventListener() {}, appendChild(child) { this.children.push(child); },
  classList: {add() {}, remove() {}}});
const getElementById = id => {
  if (!nodes.has(id)) nodes.set(id, element());
  return nodes.get(id);
};
const context = vm.createContext({
  document: {getElementById, createElement: element, readyState: 'loading', addEventListener() {}},
  window: {addEventListener() {}, location: new URL('http://localhost/'), history: {replaceState() {}}},
  URL, URLSearchParams, console, setTimeout() {}, setInterval() {}, navigator: {clipboard: {writeText() {}}}
});
const script = fs.readFileSync(process.argv[1], 'utf8');
vm.runInContext(script, context);
vm.runInContext('activeWorkspaces = [{workspace_id: "ws-uncrash", name: "Uncrash", engine: "native", tabs_count: 3}, {workspace_id: "ws-twinerd", name: "Twinerd", engine: "native", tabs_count: 2}]; renderWorkspacesBar();', context);
const chipsHtml = getElementById('workspacesChips').innerHTML;
const barDisplay = getElementById('workspacesBar').style.display;
const shortcutsDisplay = getElementById('shortcutsBar').style.display;
process.stdout.write(JSON.stringify({chipsHtml, barDisplay, shortcutsDisplay}));
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
    finally:
        os.unlink(temp_js)
