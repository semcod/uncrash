# Agent session record - ticket-034

- Agent: gemini
- Role: Software Engineer / UX Implementer
- Workstream: application
- Authority: SESSION_EXECUTION_AUTHORIZATION (User request: "dodaj po otworzeniu katalogu aplikacji , mozliwosc dodania pliakcji do wybranej maszyny w kolejnym workspace http://127.0.0.1:8850/?snapshot=20261011T170217025037-124cdf3ae6f0&engine=native&workspace=ws-20261011T210753181726-1adb37f36140&action=novnc&modal=apps&cat=jetbrains , doddaj zmiane wyswietlania panele/tabela z opcjami akcji")

## Actions

1. Enhance the Applications Catalog modal (`modal=apps`) with:
   - Target workspace / machine selector (`#appTargetWorkspaceSelect`) allowing users to launch/add the application either into a new workspace machine or an existing active workspace.
   - Switchable view mode toggle (`#appsViewGridBtn` / `#appsViewTableBtn`) between Grid (cards: `.app-card`) and Table (responsive table: `.apps-table`) with full action options (`🚀 Uruchom w workspace`, `📋 Kopiuj polecenie`).
2. Add backend support in `src/uncrash/api.py` and `src/uncrash/preview.py` to launch/attach application commands to workspaces.
3. Add unit and regression tests in `tests/test_web_ui.py` and `tests/test_api.py`.
4. Verify all tests pass and `./project/governance-check.sh` succeeds cleanly.
