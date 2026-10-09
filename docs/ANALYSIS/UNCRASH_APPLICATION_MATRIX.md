---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-application-matrix",
  "kind": "analysis",
  "version": 1,
  "title": "Uncrash installed application recovery on Twinerd noVNC",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-08",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://ticket-001",
    "artifact://ticket-002",
    "artifact://application-matrix-20261008-final",
    "artifact://novnc-fixture-20261008-v3",
    "artifact://service-proof-20261008"
  ]
}
---

# Uncrash: odzyskiwanie aplikacji w Twinerd noVNC

<!-- docs:section summary -->
## Wynik

**191 wpisów aplikacji i CLI** zinwentaryzowano; **52 przypadki GUI** przetestowano. W 35 pojawiło się okno po odzyskaniu syntetycznych plików, w 17 okna nie było. Osobno Chrome odzyskał dokładnie dwie zapisane karty i localStorage; xterm pokazał odtworzony dokument.

**Pełne odtworzenie wszystkich aplikacji pozostaje niepotwierdzone.** Nie odzyskano sesji terminali JetBrains ani rzeczywistych czatów Codex/Claude/Agy. Osobny [test backendów](UNCRASH_LOCAL_RECOVERY_BACKENDS.md) potwierdził syntetyczne dane Agy i RAM małej VM oraz powłokę i PTY we własnym gościu Linux. Inwentaryzacja obejmuje duplikaty, panele ustawień i URI; liczba pakietów systemowych nie oznacza liczby przetestowanych aplikacji.

<!-- docs:section details -->
## Metoda i dane

GUI: virtualenv Twinerd, NativeClone, TigerVNC/Openbox, RFB i noVNC; prywatne HOME/runtime/D-Bus, system tylko do odczytu, sieć odłączona, lokalne CDP Chrome. Osobistych danych w stanowiskach GUI nie używano.

Seria ogólna: syntetyczny dokument/projekt → szyfrowany snapshot → zmiana źródła → odtworzenie osobnego katalogu → porównanie bajtów → uruchomienie → screenshot noVNC. **Okno może oznaczać splash lub konfigurację; natywnej sesji nie dowodzi.**

[Pełna macierz JSON](../DATA/UNCRASH_APPLICATION_MATRIX.json) zawiera wszystkie 191 wpisów, 52 przypadki i przyczyny. Statusy:

| Status | Potwierdzenie |
|---|---|
| DATA_AND_WINDOW_PASS | Pliki i widoczne okno; sesja niezweryfikowana |
| NO_WINDOW_IN_ISOLATED_FIXTURE | Brak okna w ograniczonym stanowisku |
| NATIVE_PROFILE_PASS_LAUNCHER_PENDING | Chrome karty/localStorage; desktop wrapper osobno nieweryfikowany |
| DURABLE_FILE_REPLAY_PASS | xterm zapisany plik; brak żywego PTY |
| EXECUTABLE_MISSING | Nieodnaleziony wykonawca |
| ADAPTER_OR_FIXTURE_REQUIRED | Brak adaptera lub bezpiecznych asercji |

Launchery przypisano po dokładnej ścieżce; wspólny interpreter/Snap nie przenosi wyników na inne aplikacje. Chrome kopiowano po zatrzymaniu własnego profilu: test nie dowodzi spójności aktywnej bazy podczas awarii. Dłuższy test PyCharm Toolbox zatrzymał się na umowie EAP; nie zaakceptowano jej automatycznie.

<!-- docs:section validation -->
## Weryfikacja i dostarczenie

- Najnowsza seria: 38 testów zaliczonych (38 unit/native, 5 backendów, 1 Chrome/xterm noVNC), 1 opcjonalny systemd pominięty.
- Osobny test Chrome/xterm: zaliczony, rzeczywiste obrazy noVNC.
- Pełna seria: zaliczony test zbiorczy w 110,50 s; 17 ujemnych wyników pozostaje jawnych.
- Systemd: osobny test zaliczony; restart po SIGKILL wyłącznie własnego procesu, kolejna kopia po **300,111 s**.
- Wheel 0.1.0 zainstalowano w virtualenv Twinerd. Usługa aktywna, **4 profile**: pliki sesji Codex/Claude/Agy i ustawienia JetBrains. Dwie rzeczywiste kopie ukończone, początki oddalone o **299,997696 s**. Pierwsza: 13,07 GB logicznych → 3,39 GB zaszyfrowanych; pięć próbek integralności zaliczonych. Późniejszy pełny restore trzeciej kopii: 3779 plików / 13 072 648 410 bajtów, wszystkie hashe zgodne; prywatne dane testowe usunięto. Kontrola SQLite jest osobna. Kod Twinerd niezmieniony.
- Nowych commitów, push/PR i merge brak. Lokalnie wdrożono paczkę/usługę. Adopcja governance i `.governance/docs.json` niedokończone. Wdrożony Validator zgłosił `PUBLICATION_PROFILE_MISSING` dla `semcod/uncrash`.

Surowe JSON/logi/PNG: `artifact://application-matrix-20261008-final`, `artifact://novnc-fixture-20261008-v3`, `artifact://service-proof-20261008`; prywatne dane poza Git. Błędów stanowiska nie zaliczano jako dowodów.

Kontrola 503 baz: 502 poprawne, jedna Agy zgłasza `SQLITE_CORRUPT` w kopii i źródle. Drugi silnik SQLite potwierdził błąd źródła. Nie naprawiano ani nie zmieniano oryginału; zachowano zaszyfrowany dowód poza rotacją kopii.

<!-- docs:section risks -->
## Ograniczenia i kontynuacja

To pulpit w przestrzeniach nazw współdzielący kernel, nie pełna VM/checkpoint RAM. Nie wykonano fizycznego restartu hosta. Niezapisane bufory, scrollback, PTY, konta i czaty nie są odtwarzane. Snap, GNOME, UPower, AppArmor, systemowy D-Bus i zasoby instalacji wymagają dalszych stanowisk.

Następnie: natywne adaptery IDE/dostawców AI, testy wznowienia z zapisanych profili, pozostałe aplikacje w pełnej VM, dokończenie adopcji i chroniony profil OneDev/Validator. [Model odzyskiwania](../INFORMATION/UNCRASH_RECOVERY_MODEL.md) opisuje granice kopii plikowej.

Rust oraz domyślne kopie bez szyfrowania: [konfiguracja `.env`](../SERVICE/UNCRASH_RUST_AND_ENVIRONMENT.md).
