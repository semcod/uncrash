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
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
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
      overflow: hidden;
      height: calc(100vh - 57px);
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
  </style>
</head>
<body>
  <header>
    <div class="logo">
      <span>🛡️ uncrash</span>
      <span class="logo-badge">web client</span>
    </div>
    <div class="header-links">
      <a href="/docs" target="_blank">API Docs</a>
      <a href="/api/v1/registry" target="_blank">Registry</a>
      <a href="/api/v1/health" target="_blank">Health</a>
    </div>
  </header>

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

  <script>
    let snapshots = [];
    let currentSnapshotId = null;

    async function loadSnapshots() {
      try {
        const res = await fetch('/api/v1/snapshots');
        const data = await res.json();
        snapshots = data.snapshots || [];
        renderSnapshotList();
        if (snapshots.length > 0) {
          selectSnapshot(snapshots[0].id);
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
        li.onclick = () => selectSnapshot(s.id);

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

    document.getElementById('searchInput').addEventListener('input', renderSnapshotList);

    async function selectSnapshot(id) {
      currentSnapshotId = id;
      renderSnapshotList();
      const contentEl = document.getElementById('contentPane');
      contentEl.innerHTML = '<div class="empty-state">Ładowanie metadanych snapshotu...</div>';

      try {
        const res = await fetch(`/api/v1/snapshots/${id}`);
        const data = await res.json();
        renderSnapshotDetails(data);
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
        tabsHtml = '<div class="tabs-grid">' + tabs.map(t => {
          const provClass = t.provider ? `provider-${t.provider}` : 'provider-shell';
          const provLabel = t.provider ? t.provider.toUpperCase() : 'SHELL';
          return `
            <div class="tab-card">
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
      `;
    }

    async function launchNovnc(id) {
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
                <a href="${result.novnc_url}" target="_blank" class="btn" style="padding:4px 10px; font-size:0.75rem">Otwórz w nowej karcie ↗</a>
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
      const area = document.getElementById('previewArea');
      area.innerHTML = '<div style="padding:16px; background:var(--bg-card); border-radius:8px">Generowanie zrzutu ekranu wirtualnego pulpitu...</div>';
      try {
        const res = await fetch(`/api/v1/snapshots/${id}/screenshot`, { method: 'POST' });
        const result = await res.json();
        if (result.screenshot_url) {
          showToast('Zrzut ekranu wygenerowany pomyślnie!');
          area.innerHTML = `
            <div style="margin-top:12px">
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

    window.addEventListener('DOMContentLoaded', loadSnapshots);
  </script>
</body>
</html>
"""
