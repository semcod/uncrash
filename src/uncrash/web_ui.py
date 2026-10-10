"""Web Client Dashboard for Uncrash snapshot browser and graphical preview."""
from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Uncrash · Dashboard & Graphical Snapshot Preview</title>
  <style>
    :root {
      --bg-base: #11111b;
      --bg-surface: #181825;
      --bg-card: #1e1e2e;
      --bg-hover: #313244;
      --border: #45475a;
      --text-main: #cdd6f4;
      --text-muted: #a6adc8;
      --accent: #89b4fa;
      --accent-hover: #b4befe;
      --green: #a6e3a1;
      --purple: #cba6f7;
      --orange: #fab387;
      --red: #f38ba8;
      --yellow: #f9e2af;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 700;
      font-size: 1.25rem;
      letter-spacing: -0.5px;
    }
    .logo-badge {
      background: #313244;
      color: var(--accent);
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 600;
      border: 1px solid var(--border);
    }
    .header-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.875rem;
      margin-left: 16px;
      transition: color 0.2s;
    }
    .header-links a:hover { color: var(--accent); }
    .layout {
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }
    .sidebar {
      width: 360px;
      background: var(--bg-surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .sidebar-header {
      padding: 16px;
      border-bottom: 1px solid var(--border);
    }
    .search-input {
      width: 100%;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 12px;
      color: var(--text-main);
      font-size: 0.875rem;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent); }
    .snapshot-list {
      flex: 1;
      overflow-y: auto;
      list-style: none;
      padding: 8px;
    }
    .snapshot-item {
      padding: 12px 14px;
      margin-bottom: 6px;
      border-radius: 8px;
      cursor: pointer;
      border: 1px solid transparent;
      background: var(--bg-card);
      transition: all 0.15s ease;
    }
    .snapshot-item:hover {
      background: var(--bg-hover);
      border-color: var(--border);
    }
    .snapshot-item.active {
      background: #26293d;
      border-color: var(--accent);
    }
    .snapshot-time {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-main);
      display: flex;
      justify-content: space-between;
      margin-bottom: 4px;
    }
    .snapshot-id {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .snapshot-tags {
      margin-top: 8px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .tag {
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 500;
      background: #313244;
      color: var(--text-muted);
    }
    .tag.tabs { background: rgba(166, 227, 161, 0.15); color: var(--green); }
    .tag.gui { background: rgba(137, 180, 250, 0.15); color: var(--accent); }
    .content-pane {
      flex: 1;
      padding: 24px;
      overflow-y: auto;
      background: var(--bg-base);
    }
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: var(--text-muted);
      text-align: center;
      gap: 12px;
    }
    .detail-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .detail-title {
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 4px;
      font-family: var(--font-mono);
    }
    .detail-subtitle {
      font-size: 0.875rem;
      color: var(--text-muted);
    }
    .actions-bar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-surface);
      color: var(--text-main);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 16px;
      font-size: 0.875rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .btn:hover {
      background: var(--bg-hover);
      border-color: var(--accent);
    }
    .btn.primary {
      background: var(--accent);
      color: #11111b;
      border-color: var(--accent);
    }
    .btn.primary:hover {
      background: var(--accent-hover);
    }
    .btn.success {
      background: var(--green);
      color: #11111b;
      border-color: var(--green);
    }
    .btn-native { background: rgba(137, 180, 250, 0.12); border-color: #89b4fa; color: #89b4fa; }
    .btn-native:hover { background: #89b4fa; color: #11111b; }
    .btn-kasm { background: rgba(203, 166, 247, 0.12); border-color: #cba6f7; color: #cba6f7; }
    .btn-kasm:hover { background: #cba6f7; color: #11111b; }
    .btn-clonebox { background: rgba(250, 179, 135, 0.12); border-color: #fab387; color: #fab387; }
    .btn-clonebox:hover { background: #fab387; color: #11111b; }
    .btn-clonebox-cnt { background: rgba(148, 226, 213, 0.12); border-color: #94e2d5; color: #94e2d5; }
    .btn-clonebox-cnt:hover { background: #94e2d5; color: #11111b; }
    .btn-pelorus { background: rgba(166, 227, 161, 0.12); border-color: #a6e3a1; color: #a6e3a1; }
    .btn-pelorus:hover { background: #a6e3a1; color: #11111b; }
    .section-title {
      font-size: 1.125rem;
      font-weight: 600;
      margin: 24px 0 12px 0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .tabs-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 12px;
    }
    .tab-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      transition: border-color 0.2s;
    }
    .tab-card:hover { border-color: var(--accent); }
    .tab-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .tab-provider {
      font-weight: 700;
      font-size: 0.85rem;
      padding: 2px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .provider-codex { background: rgba(166, 227, 161, 0.2); color: var(--green); }
    .provider-agy { background: rgba(203, 166, 247, 0.2); color: var(--purple); }
    .provider-claude { background: rgba(250, 179, 135, 0.2); color: var(--orange); }
    .provider-shell { background: rgba(166, 173, 200, 0.2); color: var(--text-muted); }
    .tab-cwd {
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: var(--text-main);
      word-break: break-all;
      background: #181825;
      padding: 6px 8px;
      border-radius: 6px;
      border: 1px solid #313244;
    }
    .tab-cmd {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--yellow);
    }
    .code-box {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      color: var(--text-main);
      white-space: pre-wrap;
      word-break: break-all;
      position: relative;
    }
    .copy-btn {
      position: absolute;
      top: 8px;
      right: 8px;
      background: var(--bg-hover);
      color: var(--text-main);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 4px 8px;
      font-size: 0.75rem;
      cursor: pointer;
    }
    .copy-btn:hover { background: var(--border); }
    .novnc-container {
      margin-top: 16px;
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
      background: #000;
    }
    .novnc-frame {
      width: 100%;
      height: 600px;
      border: none;
    }
    .screenshot-img {
      max-width: 100%;
      border-radius: 10px;
      border: 1px solid var(--border);
      margin-top: 12px;
      display: block;
    }
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--green);
      color: #11111b;
      padding: 12px 20px;
      border-radius: 8px;
      font-weight: 600;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      opacity: 0;
      transition: opacity 0.3s ease;
      pointer-events: none;
    }
    .toast.show { opacity: 1; }
    .workspaces-bar {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 8px 24px;
      display: flex;
      align-items: center;
      gap: 12px;
      overflow-x: auto;
      flex-shrink: 0;
    }
    .workspaces-label {
      font-size: 0.8rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .workspace-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 4px 12px;
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.2s;
      white-space: nowrap;
      user-select: none;
    }
    .workspace-chip:hover {
      border-color: var(--accent);
      background: var(--bg-hover);
    }
    .workspace-chip.active {
      border-color: var(--accent);
      background: #26293d;
      color: var(--accent);
      font-weight: 600;
      box-shadow: 0 0 10px rgba(137, 180, 250, 0.3);
    }
    .chip-close {
      color: var(--text-muted);
      font-weight: bold;
      margin-left: 4px;
      padding: 0 4px;
      border-radius: 50%;
      transition: color 0.15s, background 0.15s;
    }
    .chip-close:hover {
      color: var(--red);
      background: rgba(243, 139, 168, 0.2);
    }
    .btn.accent-btn {
      background: var(--accent);
      color: #11111b;
      border-color: var(--accent);
      font-weight: 700;
    }
    .btn.accent-btn:hover {
      background: var(--accent-hover);
    }
    .gpu-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.78rem;
      background: rgba(166, 227, 161, 0.1);
      border: 1px solid rgba(166, 227, 161, 0.3);
      color: var(--green);
      padding: 4px 12px;
      border-radius: 20px;
      cursor: pointer;
      font-family: var(--font-mono);
      transition: all 0.2s;
      white-space: nowrap;
    }
    .gpu-badge:hover {
      background: rgba(166, 227, 161, 0.2);
      border-color: var(--green);
    }
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
      z-index: 999;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 24px;
    }
    .modal-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      width: 1040px;
      max-width: 95vw;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
      overflow: hidden;
    }
    .modal-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-body {
      padding: 20px;
      overflow-y: auto;
      flex: 1;
    }
    .cat-pill {
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 16px;
      padding: 5px 12px;
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.15s;
      user-select: none;
    }
    .cat-pill:hover, .cat-pill.active {
      background: var(--accent);
      color: #11111b;
      border-color: var(--accent);
      font-weight: 700;
    }
    .app-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: border-color 0.15s;
    }
    .app-card:hover {
      border-color: var(--accent);
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }
    .metric-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 14px;
    }
    .metric-card .label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 700;
    }
    .metric-card .val {
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text-main);
      font-family: var(--font-mono);
      margin-top: 4px;
    }
  </style>
</head>
<body>
  <header>
    <div style="display:flex; align-items:center; gap:16px">
      <div class="logo">
        <span>🛡️ uncrash</span>
        <span class="logo-badge">web client</span>
      </div>
      <div id="gpuHeaderBadge" class="gpu-badge" style="display:none" onclick="toggleAppsModal('gpu_hardware')" title="Kliknij, aby otworzyć status GPU i narzędzia NVIDIA">
        <span id="gpuStatusText">🎮 Ładowanie GPU...</span>
      </div>
    </div>
    <div class="header-links">
      <a href="javascript:void(0)" onclick="toggleAppsModal()" style="color:var(--accent); font-weight:600">📱 Zainstalowane Aplikacje (<span id="appsHeaderCount">...</span>)</a>
      <a href="/docs" target="_blank">API Docs</a>
      <a href="/api/v1/registry" target="_blank">Registry</a>
      <a href="/api/v1/workspaces" target="_blank">Workspaces</a>
      <a href="/api/v1/health" target="_blank">Health</a>
    </div>
  </header>

  <div id="workspacesBar" class="workspaces-bar" style="display:none">
    <div class="workspaces-label">
      <span>🖥️ noVNC Workspaces:</span>
    </div>
    <div id="workspacesChips" style="display:flex; gap:8px; align-items:center; flex:1; overflow-x:auto;"></div>
    <button class="btn" style="padding:3px 8px; font-size:0.75rem" onclick="fetchWorkspaces(true)">🔄 Odśwież</button>
  </div>

  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <input type="text" id="searchInput" class="search-input" placeholder="Filtruj snapshoty...">
      </div>
      <ul id="snapshotList" class="snapshot-list">
        <!-- Rendered via JS -->
      </ul>
    </aside>

    <main id="contentPane" class="content-pane">
      <div class="empty-state">
        <h2>Wybierz snapshot z listy po lewej</h2>
        <p>Możesz graficznie podejrzeć stan okien, karty terminali oraz otwarte projekty.</p>
      </div>
    </main>
  </div>

  <div id="toast" class="toast"></div>

  <div id="appsModal" class="modal-overlay" style="display:none" onclick="if(event.target===this) toggleAppsModal()">
    <div class="modal-card">
      <div class="modal-header">
        <div>
          <h2 style="font-size:1.25rem; font-weight:700; display:flex; align-items:center; gap:8px">
            <span>📱</span>
            <span>Zainstalowane Aplikacje PC & Status Odzyskiwania Stanu</span>
          </h2>
          <div style="font-size:0.8rem; color:var(--text-muted); margin-top:3px">
            Wykryto <strong id="modalTotalApps" style="color:var(--text-main)">...</strong> aplikacji systemowych · 
            <strong id="modalRecoverableApps" style="color:var(--green)">...</strong> skonfigurowanych profili odzyskiwania
          </div>
        </div>
        <button class="btn" onclick="toggleAppsModal()" style="padding:6px 12px; font-size:0.85rem">✕ Zamknij</button>
      </div>
      <div class="modal-body">
        <div id="modalGpuSection" style="margin-bottom:20px; background:var(--bg-card); border:1px solid var(--border); border-radius:10px; padding:16px;">
        </div>
        <div id="categoryPills" style="display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; align-items:center">
        </div>
        <div style="margin-bottom:14px">
          <input type="text" id="appFilterInput" class="search-input" placeholder="🔍 Szukaj aplikacji po nazwie, komendzie lub profilu..." oninput="renderFilteredApps()">
        </div>
        <div id="appsGrid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:10px;">
        </div>
      </div>
    </div>
  </div>

  <script>
    let snapshots = [];
    let currentSnapshotId = null;

    function updateUrl(params = {}) {
      const url = new URL(window.location);
      for (const [key, val] of Object.entries(params)) {
        if (val === null || val === undefined || val === '') {
          url.searchParams.delete(key);
        } else {
          url.searchParams.set(key, val);
        }
      }
      window.history.replaceState({}, '', url.toString());
    }

    async function loadSnapshots() {
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const queryParam = urlParams.get('q');
        if (queryParam) {
          document.getElementById('searchInput').value = queryParam;
        }

        const res = await fetch('/api/v1/snapshots');
        const data = await res.json();
        snapshots = data.snapshots || [];
        renderSnapshotList();

        const requestedSnapshot = urlParams.get('snapshot');
        const requestedAction = urlParams.get('action');
        const requestedTab = urlParams.get('tab');

        if (requestedSnapshot && snapshots.some(s => s.id === requestedSnapshot)) {
          await selectSnapshot(requestedSnapshot, requestedAction);
        } else if (snapshots.length > 0) {
          await selectSnapshot(snapshots[0].id, requestedAction);
        }

        if (requestedTab !== null && requestedTab !== undefined) {
          setTimeout(() => focusTab(parseInt(requestedTab, 10)), 200);
        }
      } catch (err) {
        console.error('Failed to load snapshots:', err);
      }
    }

    function renderSnapshotList() {
      const listEl = document.getElementById('snapshotList');
      const query = document.getElementById('searchInput').value.toLowerCase();
      const filtered = snapshots.filter(s => s.id.toLowerCase().includes(query) || (s.created_at && s.created_at.includes(query)));

      listEl.innerHTML = '';
      filtered.forEach(s => {
        const li = document.createElement('li');
        li.className = `snapshot-item ${s.id === currentSnapshotId ? 'active' : ''}`;
        li.onclick = () => {
          selectSnapshot(s.id);
          updateUrl({ action: null, tab: null });
        };

        const timeStr = s.created_at ? new Date(s.created_at).toLocaleTimeString() + ' · ' + new Date(s.created_at).toLocaleDateString() : 'Nieznany czas';
        const tabsCount = s.terminal_tabs_count || 0;
        const guiCount = s.gui_projects_count || 0;

        li.innerHTML = `
          <div class="snapshot-time">
            <span>${timeStr}</span>
          </div>
          <div class="snapshot-id">${s.id}</div>
          <div class="snapshot-tags">
            <span class="tag tabs">${tabsCount} tab(ów)</span>
            <span class="tag gui">${guiCount} proj. GUI</span>
            <span class="tag">${(s.profiles || []).length} profili</span>
          </div>
        `;
        listEl.appendChild(li);
      });
    }

    document.getElementById('searchInput').addEventListener('input', (e) => {
      renderSnapshotList();
      updateUrl({ q: e.target.value.trim() });
    });

    async function selectSnapshot(id, autoAction = null) {
      currentSnapshotId = id;
      renderSnapshotList();
      updateUrl({ snapshot: id });
      const contentEl = document.getElementById('contentPane');
      contentEl.innerHTML = '<div class="empty-state">Ładowanie metadanych snapshotu...</div>';

      try {
        const res = await fetch(`/api/v1/snapshots/${id}`);
        const data = await res.json();
        renderSnapshotDetails(data);
        if (autoAction === 'novnc') {
          launchNovnc(id);
        } else if (autoAction === 'screenshot') {
          captureScreenshot(id);
        } else if (autoAction === 'launch-tabs') {
          launchTabs(id);
        } else if (autoAction === 'workspace') {
          const wsParam = new URLSearchParams(window.location.search).get('workspace');
          const engineParam = new URLSearchParams(window.location.search).get('engine') || 'native';
          if (wsParam) {
            selectWorkspace(wsParam);
          } else {
            launchWorkspace(id, false, engineParam);
          }
        }
      } catch (err) {
        contentEl.innerHTML = `<div class="empty-state" style="color:var(--red)">Błąd ładowania snapshotu: ${err.message}</div>`;
      }
    }

    function renderSnapshotDetails(data) {
      const contentEl = document.getElementById('contentPane');
      const timeStr = data.created_at ? new Date(data.created_at).toLocaleString() : 'Nieznany';
      const tabs = data.terminal_tabs || [];
      const gui = data.gui_projects || [];
      const profiles = data.profiles || [];

      let tabsHtml = '';
      if (tabs.length === 0) {
        tabsHtml = '<p style="color:var(--text-muted)">Brak zapisanych interaktywnych kart terminala.</p>';
      } else {
        tabsHtml = '<div class="tabs-grid">' + tabs.map((t, idx) => {
          const provClass = t.provider ? `provider-${t.provider}` : 'provider-shell';
          const provLabel = t.provider ? t.provider.toUpperCase() : 'SHELL';
          return `
            <div class="tab-card" id="tabCard${idx}" onclick="focusTab(${idx})" style="cursor:pointer; transition:border-color 0.2s, box-shadow 0.2s">
              <div class="tab-header">
                <span class="tab-provider ${provClass}">${provLabel}</span>
                <span style="font-size:0.75rem; color:var(--text-muted)">${t.terminal || 'brak tty'}</span>
              </div>
              <div style="font-weight:600; font-size:0.9rem">${t.title}</div>
              <div class="tab-cwd">${t.cwd}</div>
              <div class="tab-cmd">▶ ${t.resume_command}</div>
            </div>
          `;
        }).join('') + '</div>';
      }

      let guiHtml = '';
      if (gui.length === 0) {
        guiHtml = '<p style="color:var(--text-muted)">Brak zapisanych projektów IDE.</p>';
      } else {
        guiHtml = '<div style="display:flex; flex-direction:column; gap:6px;">' + gui.slice(0, 15).map(p => `
          <div style="background:var(--bg-card); padding:8px 12px; border-radius:6px; border:1px solid var(--border); font-family:var(--font-mono); font-size:0.8rem; display:flex; justify-content:space-between">
            <span>${p.path}</span>
            <span style="color:${p.state === 'open' ? 'var(--green)' : 'var(--text-muted)'}">${p.state}</span>
          </div>
        `).join('') + (gui.length > 15 ? `<p style="font-size:0.8rem; color:var(--text-muted)">...i jeszcze ${gui.length - 15} projektów</p>` : '') + '</div>';
      }

      contentEl.innerHTML = `
        <div class="detail-header">
          <div>
            <div class="detail-title">${data.snapshot}</div>
            <div class="detail-subtitle">Zapisano: ${timeStr} · Profile: ${profiles.join(', ')}</div>
          </div>
          <div class="actions-bar">
            <button class="btn primary" onclick="launchNovnc('${data.snapshot}')">🖥️ Podgląd noVNC</button>
            <button class="btn" onclick="captureScreenshot('${data.snapshot}')">📸 Zrzut ekranu</button>
            <button class="btn success" onclick="launchTabs('${data.snapshot}')">💻 Uruchom taby w terminalu</button>
            <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center; background:var(--bg-surface); padding:4px 8px; border-radius:8px; border:1px solid var(--border)">
              <span style="font-size:0.75rem; color:var(--text-muted); font-weight:700; margin-right:2px">WIRTUALIZACJA:</span>
              <button class="btn btn-native" onclick="launchWorkspace('${data.snapshot}', false, 'native')" title="Natywny wirtualny pulpit X11 na hoście przez Twinerd">🖥️ Natywny</button>
              <button class="btn btn-kasm" onclick="launchWorkspace('${data.snapshot}', false, 'kasm')" title="Izolowany Kasm Workspace ze stagingiem plików przez twinerd-kasm">📦 Kasm</button>
              <button class="btn btn-clonebox" onclick="launchWorkspace('${data.snapshot}', false, 'clonebox')" title="Wirtualizacja KVM/QEMU maszyn z projektu clonebox (wronai/clonebox)">🎛️ CloneBox VM</button>
              <button class="btn btn-clonebox-cnt" onclick="launchWorkspace('${data.snapshot}', false, 'clonebox-container')" title="Lekka konteneryzacja za pośrednictwem clonebox.container (Docker/Podman)">🐳 CloneBox Cnt</button>
              <button class="btn btn-pelorus" onclick="launchWorkspace('${data.snapshot}', false, 'pelorus')" title="Cyfrowy bliźniak i arbiter sesji twinerd-pelorus">🧭 Pelorus</button>
              <button class="btn" onclick="promptNewWorkspace('${data.snapshot}')" title="Uruchom kolejną instancję wybranego silnika dla tej sesji">+ Nowy</button>
            </div>
          </div>
        </div>

        <div id="previewArea"></div>

        <div class="section-title">Terminal Tabs (${tabs.length})</div>
        ${tabsHtml}

        <div class="section-title">Polecenie startowe w systemowym gnome-terminal</div>
        <div class="code-box">
          <button class="copy-btn" onclick="copyText('${btoa(data.launch_script || '')}')">Kopiuj</button>
          <code>${data.launch_script || '# Brak zdefiniowanych tabów'}</code>
        </div>

        <div class="section-title">Projekty JetBrains & Okna GUI (${gui.length})</div>
        ${guiHtml}

        ${data.system_gpu && data.system_gpu.present ? `
          <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:10px 14px; margin-top:20px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px">
            <div style="display:flex; align-items:center; gap:8px">
              <span style="font-size:1.1rem">🎮</span>
              <span style="font-weight:600; font-size:0.85rem">Akceleracja GPU: ${data.system_gpu.name}</span>
              <span style="font-size:0.75rem; color:var(--text-muted)">Driver ${data.system_gpu.driver_version} · CUDA ${data.system_gpu.cuda_version}</span>
            </div>
            <div style="display:flex; gap:8px; align-items:center">
              <span class="tag" style="background:rgba(166,227,161,0.15); color:var(--green)">VRAM: ${data.system_gpu.memory_used_mb} / ${data.system_gpu.memory_total_mb} MiB</span>
              <span class="tag">${data.system_gpu.temperature_c}°C</span>
              <button class="btn" style="padding:2px 8px; font-size:0.75rem" onclick="toggleAppsModal('gpu_hardware')">Szczegóły GPU ↗</button>
            </div>
          </div>
        ` : ''}

        ${data.recorded_gui_apps && data.recorded_gui_apps.length > 0 ? `
          <div class="section-title">Zarejestrowane Okna i Aplikacje GUI w Snapshot (${data.recorded_gui_apps.length})</div>
          <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:8px;">
            ${data.recorded_gui_apps.map(a => `
              <div style="background:var(--bg-card); padding:8px 12px; border-radius:6px; border:1px solid var(--border); display:flex; justify-content:space-between; align-items:center">
                <div>
                  <div style="font-weight:600; font-size:0.85rem">${a.name}</div>
                  <div style="font-size:0.72rem; color:var(--text-muted); font-family:var(--font-mono)">PID: ${a.pid} ${a.cmd ? ('· ' + a.cmd) : ''}</div>
                </div>
                <span class="tag ${a.has_profile ? 'gui' : ''}">${a.has_profile ? 'Profil ✅' : 'Proces'}</span>
              </div>
            `).join('')}
          </div>
        ` : ''}

        <div style="margin-top:24px; padding:16px; background:var(--bg-card); border-radius:10px; border:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px">
          <div>
            <div style="font-weight:700; font-size:0.95rem">📱 Wszystkie Zainstalowane Aplikacje PC (NVIDIA / AI / IDE / Narzędzia)</div>
            <div style="font-size:0.8rem; color:var(--text-muted)">Przeglądaj macierz aplikacji systemowych i stan ich profili odzyskiwania uncrash</div>
          </div>
          <button class="btn primary" onclick="toggleAppsModal()">Otwórz katalog aplikacji PC ↗</button>
        </div>
      `;
    }

    let activeWorkspaces = [];
    let currentWorkspaceId = null;

    async function fetchWorkspaces(notify = false) {
      try {
        const res = await fetch('/api/v1/workspaces');
        const data = await res.json();
        activeWorkspaces = data.workspaces || [];
        renderWorkspacesBar();
        if (notify) showToast(`Znaleziono ${activeWorkspaces.length} aktywnych workspace'ów`);
      } catch (err) {
        console.error('Failed to fetch workspaces:', err);
      }
    }

    function renderWorkspacesBar() {
      const bar = document.getElementById('workspacesBar');
      const chips = document.getElementById('workspacesChips');
      if (!bar || !chips) return;

      if (activeWorkspaces.length === 0) {
        bar.style.display = 'none';
        return;
      }
      bar.style.display = 'flex';
      chips.innerHTML = activeWorkspaces.map(ws => {
        const isActive = ws.workspace_id === currentWorkspaceId;
        const shortName = ws.name || ws.workspace_id;
        let icon = '●';
        let badge = '🖥️ Natywny';
        let color = '#89b4fa';
        if (ws.engine === 'kasm' || ws.workspace_id.startsWith('kasm-')) {
          icon = '📦'; badge = '📦 Kasm'; color = '#cba6f7';
        } else if (ws.engine === 'clonebox' || ws.workspace_id.startsWith('cb-')) {
          icon = '🎛️'; badge = '🎛️ CloneBox VM'; color = '#fab387';
        } else if (ws.engine === 'clonebox-container' || ws.workspace_id.startsWith('cbc-')) {
          icon = '🐳'; badge = '🐳 CloneBox Cnt'; color = '#94e2d5';
        } else if (ws.engine === 'pelorus' || ws.workspace_id.startsWith('pelorus-')) {
          icon = '🧭'; badge = '🧭 Pelorus'; color = '#a6e3a1';
        }
        const tabsInfo = ws.tabs_count > 0 ? `${ws.tabs_count} tab(ów)` : (ws.display || '');
        return `
          <div class="workspace-chip ${isActive ? 'active' : ''}" style="border-left: 3px solid ${color}" onclick="selectWorkspace('${ws.workspace_id}')">
            <span>${icon}</span>
            <span><strong>${shortName}</strong> [${badge}] (${tabsInfo})</span>
            <span class="chip-close" onclick="event.stopPropagation(); closeWorkspace('${ws.workspace_id}')" title="Zamknij workspace">✕</span>
          </div>
        `;
      }).join('');
    }

    async function launchWorkspace(snapshotId, forceNew = false, engine = 'native') {
      updateUrl({ snapshot: snapshotId, action: 'workspace', engine: engine });
      const area = document.getElementById('previewArea');
      const engineLabels = {
        'native': 'Natywny Workspace (Twinerd / TigerVNC)',
        'kasm': 'Kasm Workspace (twinerd-kasm)',
        'clonebox': 'CloneBox VM (wronai/clonebox)',
        'clonebox-container': 'CloneBox Container (Docker/Podman)',
        'pelorus': 'Pelorus Digital Twin (twinerd-pelorus)'
      };
      const label = engineLabels[engine] || engine;
      area.innerHTML = `<div style="padding:16px; background:var(--bg-card); border-radius:8px">Inicjalizacja i uruchamianie silnika wirtualizacji: <strong>${label}</strong>...</div>`;
      try {
        const url = `/api/v1/snapshots/${snapshotId}/workspace?force_new=${forceNew}&engine=${engine}`;
        const res = await fetch(url, { method: 'POST' });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const ws = await res.json();
        currentWorkspaceId = ws.workspace_id;
        updateUrl({ snapshot: snapshotId, action: 'workspace', workspace: ws.workspace_id, engine: ws.engine });
        renderWorkspacePreview(ws);
        await fetchWorkspaces();
        showToast(`Workspace '${ws.workspace_id}' [${(ws.engine || engine).toUpperCase()}] został uruchomiony!`);
      } catch (err) {
        area.innerHTML = `<div style="padding:16px; color:var(--red)">Błąd uruchamiania workspace noVNC (${engine}): ${err.message}</div>`;
      }
    }

    function promptNewWorkspace(snapshotId) {
      const choice = prompt('Wybierz silnik (1: native, 2: kasm, 3: clonebox, 4: clonebox-container, 5: pelorus):', '1');
      if (!choice) return;
      const map = {
        '1': 'native', 'native': 'native',
        '2': 'kasm', 'kasm': 'kasm',
        '3': 'clonebox', 'clonebox': 'clonebox',
        '4': 'clonebox-container', 'clonebox-container': 'clonebox-container',
        '5': 'pelorus', 'pelorus': 'pelorus'
      };
      const eng = map[choice.trim().toLowerCase()] || 'native';
      launchWorkspace(snapshotId, true, eng);
    }

    async function selectWorkspace(workspaceId) {
      currentWorkspaceId = workspaceId;
      renderWorkspacesBar();
      updateUrl({ action: 'workspace', workspace: workspaceId });
      const existing = activeWorkspaces.find(w => w.workspace_id === workspaceId);
      if (existing) {
        if (existing.snapshot_id && existing.snapshot_id !== 'twinerd' && existing.snapshot_id !== currentSnapshotId) {
          await selectSnapshot(existing.snapshot_id, 'workspace');
          return;
        }
        renderWorkspacePreview(existing);
      } else {
        try {
          const res = await fetch(`/api/v1/workspaces/${workspaceId}`);
          if (res.ok) {
            const ws = await res.json();
            renderWorkspacePreview(ws);
          }
        } catch (err) {
          console.error(err);
        }
      }
    }

    function renderWorkspacePreview(ws) {
      currentWorkspaceId = ws.workspace_id;
      renderWorkspacesBar();
      const area = document.getElementById('previewArea');
      const tabsCount = ws.tabs_count || (ws.terminal_tabs ? ws.terminal_tabs.length : 0);
      let engineBadge = '<span class="tag" style="background:rgba(137,180,250,0.25); color:var(--accent); font-weight:700">🖥️ NATYWNY TWINERD</span>';
      if (ws.engine === 'kasm' || ws.workspace_id.startsWith('kasm-')) {
        engineBadge = '<span class="tag" style="background:rgba(203,166,247,0.25); color:#cba6f7; font-weight:700">📦 KASM WORKSPACE (twinerd-kasm)</span>';
      } else if (ws.engine === 'clonebox' || ws.workspace_id.startsWith('cb-')) {
        engineBadge = '<span class="tag" style="background:rgba(250,179,135,0.25); color:#fab387; font-weight:700">🎛️ CLONEBOX VM (wronai/clonebox)</span>';
      } else if (ws.engine === 'clonebox-container' || ws.workspace_id.startsWith('cbc-')) {
        engineBadge = '<span class="tag" style="background:rgba(148,226,213,0.25); color:#94e2d5; font-weight:700">🐳 CLONEBOX CONTAINER (Docker/Podman)</span>';
      } else if (ws.engine === 'pelorus' || ws.workspace_id.startsWith('pelorus-')) {
        engineBadge = '<span class="tag" style="background:rgba(166,227,161,0.25); color:#a6e3a1; font-weight:700">🧭 PELORUS TWIN (twinerd-pelorus)</span>';
      }
      const stagingInfo = ws.workspace_dir
        ? `<span style="font-size:0.75rem; color:var(--text-muted)">Staging: <code>${ws.workspace_dir}</code> (${ws.staged_files_count || 0} plików)</span>`
        : '';
      area.innerHTML = `
        <div class="novnc-container">
          <div style="background:var(--bg-surface); padding:10px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); flex-wrap:wrap; gap:8px">
            <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap">
              <span style="font-weight:700; font-size:0.95rem">🖥️ Workspace: <strong>${ws.workspace_id}</strong></span>
              ${engineBadge}
              <span class="tag tabs">${tabsCount} aktywnych kart</span>
              <span style="font-size:0.8rem; color:var(--text-muted)">Ekran: <code>${ws.display}</code> · Port WS: <code>${ws.ws_port}</code> · RFB: <code>${ws.rfb_port}</code></span>
              ${stagingInfo}
            </div>
            <div style="display:flex; gap:8px">
              <a href="${ws.novnc_url}" target="_blank" class="btn" style="padding:4px 10px; font-size:0.75rem">Otwórz w nowej karcie ↗</a>
              <button class="btn" onclick="reloadNovncIframe()" style="padding:4px 10px; font-size:0.75rem">🔄 Odśwież</button>
              <button class="btn" onclick="closeWorkspace('${ws.workspace_id}')" style="padding:4px 10px; font-size:0.75rem; color:var(--red); border-color:var(--red)">✕ Zamknij Workspace</button>
              <button class="btn" onclick="closePreviewArea()" style="padding:4px 10px; font-size:0.75rem">✕ Ukryj</button>
            </div>
          </div>
          <iframe id="novncIframe" src="${ws.novnc_url}" class="novnc-frame" style="height:680px"></iframe>
        </div>
      `;
    }

    function reloadNovncIframe() {
      const iframe = document.getElementById('novncIframe');
      if (iframe) iframe.src = iframe.src;
    }

    async function closeWorkspace(workspaceId) {
      if (!confirm(`Czy na pewno chcesz zamknąć workspace '${workspaceId}' i zakończyć uruchomione w nim procesy?`)) {
        return;
      }
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/close`, { method: 'POST' });
        const result = await res.json();
        showToast(`Workspace '${workspaceId}' został zamknięty`);
        if (currentWorkspaceId === workspaceId) {
          currentWorkspaceId = null;
          closePreviewArea();
        }
        await fetchWorkspaces();
      } catch (err) {
        showToast('Błąd zamykania workspace: ' + err.message);
      }
    }

    function focusTab(idx) {
      updateUrl({ tab: idx });
      document.querySelectorAll('.tab-card').forEach((el, i) => {
        if (i === idx) {
          el.style.borderColor = 'var(--accent)';
          el.style.boxShadow = '0 0 12px rgba(137, 180, 250, 0.4)';
        } else {
          el.style.borderColor = 'var(--border)';
          el.style.boxShadow = 'none';
        }
      });
    }

    function closePreviewArea() {
      document.getElementById('previewArea').innerHTML = '';
      currentWorkspaceId = null;
      renderWorkspacesBar();
      updateUrl({ action: null, workspace: null, engine: null });
    }

    async function launchNovnc(id) {
      updateUrl({ action: 'novnc' });
      const area = document.getElementById('previewArea');
      area.innerHTML = '<div style="padding:16px; background:var(--bg-card); border-radius:8px">Uruchamianie wirtualnego pulpitu noVNC...</div>';
      try {
        const res = await fetch(`/api/v1/snapshots/${id}/novnc`, { method: 'POST' });
        const result = await res.json();
        if (result.novnc_url) {
          showToast('Wirtualny pulpit noVNC uruchomiony!');
          area.innerHTML = `
            <div class="novnc-container">
              <div style="background:var(--bg-surface); padding:8px 12px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border)">
                <span style="font-size:0.85rem">Wirtualny ekran: <strong>${result.display}</strong> · Port: <strong>${result.ws_port}</strong></span>
                <div style="display:flex; gap:8px">
                  <a href="${result.novnc_url}" target="_blank" class="btn" style="padding:4px 10px; font-size:0.75rem">Otwórz w nowej karcie ↗</a>
                  <button class="btn" onclick="closePreviewArea()" style="padding:4px 10px; font-size:0.75rem">✕ Zamknij</button>
                </div>
              </div>
              <iframe src="${result.novnc_url}" class="novnc-frame"></iframe>
            </div>
          `;
        } else {
          area.innerHTML = `<div style="padding:16px; color:var(--red)">Błąd startu noVNC: ${result.error || 'Nieznany błąd'}</div>`;
        }
      } catch (err) {
        area.innerHTML = `<div style="padding:16px; color:var(--red)">Błąd żądania noVNC: ${err.message}</div>`;
      }
    }

    async function captureScreenshot(id) {
      updateUrl({ action: 'screenshot' });
      const area = document.getElementById('previewArea');
      area.innerHTML = '<div style="padding:16px; background:var(--bg-card); border-radius:8px">Generowanie zrzutu ekranu wirtualnego pulpitu...</div>';
      try {
        const res = await fetch(`/api/v1/snapshots/${id}/screenshot`, { method: 'POST' });
        const result = await res.json();
        if (result.screenshot_url) {
          showToast('Zrzut ekranu wygenerowany pomyślnie!');
          area.innerHTML = `
            <div style="margin-top:12px; background:var(--bg-card); padding:12px; border-radius:8px; border:1px solid var(--border)">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px">
                <span style="font-size:0.85rem; color:var(--text-muted)">Zrzut ekranu wirtualnego pulpitu:</span>
                <button class="btn" onclick="closePreviewArea()" style="padding:4px 10px; font-size:0.75rem">✕ Zamknij podgląd</button>
              </div>
              <img src="${result.screenshot_url}?t=${Date.now()}" class="screenshot-img" alt="Zrzut ekranu snapshotu">
            </div>
          `;
        } else {
          area.innerHTML = `<div style="padding:16px; color:var(--red)">Nie udało się utworzyć zrzutu ekranu: ${result.error || 'Błąd'}</div>`;
        }
      } catch (err) {
        area.innerHTML = `<div style="padding:16px; color:var(--red)">Błąd żądania: ${err.message}</div>`;
      }
    }

    async function launchTabs(id) {
      updateUrl({ action: 'launch-tabs' });
      try {
        const res = await fetch(`/api/v1/snapshots/${id}/launch-tabs`, { method: 'POST' });
        const result = await res.json();
        if (result.status === 'launched') {
          showToast(`Uruchomiono ${result.tabs_count} kart w systemowym terminalu!`);
        } else {
          showToast(`Wynik: ${result.status || 'sukces'}`);
        }
      } catch (err) {
        alert('Błąd uruchamiania tabów: ' + err.message);
      }
    }

    function copyText(b64) {
      const text = atob(b64);
      navigator.clipboard.writeText(text);
      showToast('Skopiowano do schowka!');
    }

    function showToast(msg) {
      const toast = document.getElementById('toast');
      toast.textContent = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 3000);
    }

    let gpuData = null;
    let applicationsData = null;
    let currentAppCategory = 'all';

    const categoryMeta = {
      'all': { label: 'Wszystkie', icon: '📱' },
      'gpu_hardware': { label: 'NVIDIA & GPU', icon: '🎮' },
      'ai_agents': { label: 'AI Agenci & IDE', icon: '🤖' },
      'jetbrains': { label: 'JetBrains IDE', icon: '☕' },
      'code_terminals': { label: 'Terminale & Edytory', icon: '💻' },
      'browsers': { label: 'Przeglądarki', icon: '🌐' },
      'virtualization': { label: 'Wirtualizacja & VM', icon: '📦' },
      'creative_media': { label: 'Multimedia & 3D', icon: '🎨' },
      'system_utils': { label: 'Narzędzia Systemowe', icon: '⚙️' }
    };

    async function fetchGpuAndApps() {
      try {
        const [gpuRes, appsRes] = await Promise.all([
          fetch('/api/v1/system/gpu'),
          fetch('/api/v1/system/applications')
        ]);
        if (gpuRes.ok) gpuData = await gpuRes.json();
        if (appsRes.ok) applicationsData = await appsRes.json();
        renderGpuWidget();
        renderAppsHeader();
        renderCategoryPills();
        renderFilteredApps();
      } catch (err) {
        console.error('Error fetching GPU or apps:', err);
      }
    }

    function renderGpuWidget() {
      const badge = document.getElementById('gpuHeaderBadge');
      const text = document.getElementById('gpuStatusText');
      if (!badge || !text) return;
      if (gpuData && gpuData.present) {
        badge.style.display = 'inline-flex';
        text.textContent = `🎮 ${gpuData.name} · ${gpuData.memory_used_mb}/${gpuData.memory_total_mb} MiB · ${gpuData.temperature_c}°C`;
      } else {
        badge.style.display = 'none';
      }
      renderGpuSection();
    }

    function renderGpuSection() {
      const sec = document.getElementById('modalGpuSection');
      if (!sec) return;
      if (!gpuData || !gpuData.present) {
        sec.innerHTML = '<div style="color:var(--text-muted)">🎮 Brak dedykowanej karty graficznej NVIDIA na hoście.</div>';
        return;
      }
      const tools = gpuData.tools || {};
      sec.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:8px">
          <div style="display:flex; align-items:center; gap:10px">
            <span style="font-size:1.5rem">🎮</span>
            <div>
              <div style="font-weight:700; font-size:1.1rem; color:var(--green)">${gpuData.name}</div>
              <div style="font-size:0.8rem; color:var(--text-muted)">NVIDIA Driver: <strong>${gpuData.driver_version}</strong> · CUDA: <strong>${gpuData.cuda_version}</strong></div>
            </div>
          </div>
          <div style="display:flex; gap:6px; flex-wrap:wrap">
            <span class="tag" style="background:${tools['nvidia-smi'] ? 'rgba(166,227,161,0.2)' : 'rgba(243,139,168,0.2)'}; color:${tools['nvidia-smi'] ? 'var(--green)' : 'var(--red)'}">nvidia-smi ${tools['nvidia-smi'] ? '✓' : '✗'}</span>
            <span class="tag" style="background:${tools['nvtop'] ? 'rgba(166,227,161,0.2)' : 'rgba(243,139,168,0.2)'}; color:${tools['nvtop'] ? 'var(--green)' : 'var(--red)'}">nvtop ${tools['nvtop'] ? '✓' : '✗'}</span>
            <span class="tag" style="background:${tools['nvidia-settings'] ? 'rgba(166,227,161,0.2)' : 'rgba(243,139,168,0.2)'}; color:${tools['nvidia-settings'] ? 'var(--green)' : 'var(--red)'}">nvidia-settings ${tools['nvidia-settings'] ? '✓' : '✗'}</span>
          </div>
        </div>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="label">VRAM Pamięć</div>
            <div class="val">${gpuData.memory_used_mb} <span style="font-size:0.8rem; font-weight:400; color:var(--text-muted)">/ ${gpuData.memory_total_mb} MiB</span></div>
          </div>
          <div class="metric-card">
            <div class="label">Obciążenie GPU</div>
            <div class="val">${gpuData.gpu_utilization_pct}%</div>
          </div>
          <div class="metric-card">
            <div class="label">Temperatura</div>
            <div class="val">${gpuData.temperature_c}°C</div>
          </div>
          <div class="metric-card">
            <div class="label">Compute Cache (~/.nv)</div>
            <div class="val" style="color:var(--green); font-size:0.95rem">✅ Aktywny profil</div>
          </div>
        </div>
      `;
    }

    function renderAppsHeader() {
      if (!applicationsData) return;
      const countEl = document.getElementById('appsHeaderCount');
      if (countEl) countEl.textContent = applicationsData.total_installed;
      const modalTotal = document.getElementById('modalTotalApps');
      if (modalTotal) modalTotal.textContent = applicationsData.total_installed;

      let recoverable = 0;
      for (const catObj of Object.values(applicationsData.categories || {})) {
        const apps = catObj.apps || (Array.isArray(catObj) ? catObj : []);
        recoverable += apps.filter(a => a.has_recovery_profile).length;
      }
      const modalRec = document.getElementById('modalRecoverableApps');
      if (modalRec) modalRec.textContent = recoverable;
    }

    function renderCategoryPills() {
      const pillsContainer = document.getElementById('categoryPills');
      if (!pillsContainer || !applicationsData) return;

      const keys = ['all', 'gpu_hardware', 'ai_agents', 'jetbrains', 'code_terminals', 'browsers', 'virtualization', 'creative_media', 'system_utils'];
      pillsContainer.innerHTML = keys.map(k => {
        const meta = categoryMeta[k] || { label: k, icon: '📦' };
        let count = 0;
        if (k === 'all') {
          count = applicationsData.total_installed;
        } else {
          const catObj = applicationsData.categories && applicationsData.categories[k];
          count = catObj ? (catObj.apps ? catObj.apps.length : (Array.isArray(catObj) ? catObj.length : 0)) : 0;
        }
        const active = currentAppCategory === k ? 'active' : '';
        return `
          <div class="cat-pill ${active}" onclick="selectAppCategory('${k}')">
            <span>${meta.icon} ${meta.label}</span>
            <span style="opacity:0.75; font-size:0.75rem; margin-left:4px">(${count})</span>
          </div>
        `;
      }).join('');
    }

    function selectAppCategory(cat) {
      currentAppCategory = cat;
      renderCategoryPills();
      renderFilteredApps();
      updateUrl({ cat: cat === 'all' ? null : cat });
    }

    function renderFilteredApps() {
      const grid = document.getElementById('appsGrid');
      if (!grid || !applicationsData) return;
      const filterText = (document.getElementById('appFilterInput')?.value || '').toLowerCase().trim();

      let list = [];
      if (currentAppCategory === 'all') {
        for (const catObj of Object.values(applicationsData.categories || {})) {
          const apps = catObj.apps || (Array.isArray(catObj) ? catObj : []);
          list.push(...apps);
        }
      } else {
        const catObj = applicationsData.categories && applicationsData.categories[currentAppCategory];
        list = catObj ? (catObj.apps ? catObj.apps : (Array.isArray(catObj) ? catObj : [])) : [];
      }

      if (filterText) {
        list = list.filter(a =>
          (a.name && a.name.toLowerCase().includes(filterText)) ||
          (a.cmd && a.cmd.toLowerCase().includes(filterText)) ||
          (a.profile_id && a.profile_id.toLowerCase().includes(filterText))
        );
      }

      if (list.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1 / -1; padding:32px; text-align:center; color:var(--text-muted)">Brak pasujących aplikacji w tej kategorii.</div>';
        return;
      }

      grid.innerHTML = list.map(app => {
        const meta = categoryMeta[app.category] || { icon: '📦', label: app.category };
        const hasProfile = app.has_recovery_profile;
        const profileBadge = hasProfile
          ? `<span class="tag" style="background:rgba(166,227,161,0.2); color:var(--green); font-weight:700">✅ Profil: ${app.profile_id}</span>`
          : `<span class="tag" style="background:rgba(166,173,200,0.12); color:var(--text-muted)">ℹ️ Systemowa</span>`;

        return `
          <div class="app-card">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px">
              <div>
                <div style="font-weight:700; font-size:0.92rem; display:flex; align-items:center; gap:6px">
                  <span>${meta.icon}</span>
                  <span>${app.name}</span>
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted); text-transform:uppercase; font-weight:600; margin-top:2px">${meta.label}</div>
              </div>
              <div>${profileBadge}</div>
            </div>
            <div style="font-family:var(--font-mono); font-size:0.75rem; color:var(--yellow); background:#181825; padding:4px 8px; border-radius:4px; border:1px solid #313244; word-break:break-all">
              ${app.cmd || 'brak polecenia cli'}
            </div>
            ${app.desktop_file ? `<div style="font-size:0.7rem; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${app.desktop_file}">📄 ${app.desktop_file}</div>` : ''}
          </div>
        `;
      }).join('');
    }

    function toggleAppsModal(category = null) {
      const modal = document.getElementById('appsModal');
      if (!modal) return;
      if (modal.style.display === 'none' || modal.style.display === '') {
        if (category) {
          selectAppCategory(category);
        }
        modal.style.display = 'flex';
        updateUrl({ modal: 'apps', cat: currentAppCategory === 'all' ? null : currentAppCategory });
      } else {
        modal.style.display = 'none';
        updateUrl({ modal: null, cat: null });
      }
    }

    window.addEventListener('popstate', () => {
      const urlParams = new URLSearchParams(window.location.search);
      const snap = urlParams.get('snapshot');
      const action = urlParams.get('action');
      const ws = urlParams.get('workspace');
      const modal = urlParams.get('modal');
      const cat = urlParams.get('cat');
      if (snap && snap !== currentSnapshotId) {
        selectSnapshot(snap, action);
      } else if (action === 'workspace' && ws && ws !== currentWorkspaceId) {
        selectWorkspace(ws);
      }
      if (modal === 'apps') {
        const modalEl = document.getElementById('appsModal');
        if (modalEl) modalEl.style.display = 'flex';
        if (cat) selectAppCategory(cat);
      } else {
        const modalEl = document.getElementById('appsModal');
        if (modalEl) modalEl.style.display = 'none';
      }
    });

    async function init() {
      await Promise.all([loadSnapshots(), fetchWorkspaces(), fetchGpuAndApps()]);
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('modal') === 'apps') {
        toggleAppsModal(urlParams.get('cat'));
      }
      setInterval(fetchWorkspaces, 15000);
      setInterval(fetchGpuAndApps, 30000);
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  </script>
</body>
</html>
"""
