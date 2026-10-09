---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-local-recovery-backends",
  "kind": "analysis",
  "version": 1,
  "title": "Uncrash local recovery backends",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-08",
  "source_revision": "99601d769ca03236d8ed1249bda97451fe455d79",
  "priority": "P1",
  "evidence": [
    "artifact://ticket-001",
    "artifact://ticket-002",
    "artifact://local-backends-20261008-linux-final",
    "artifact://search-index-20261008-continue"
  ]
}
---

# Lokalne backendy odzyskiwania

<!-- docs:section summary -->
## Wynik

Wyszukiwanie wykonano lokalnym CLI **semcod/search**, następnie sprawdzono kod i uruchomiono odizolowane testy. Indeks obejmuje 1002 z 1003 wykrytych repozytoriów; jeden niezwiązany worktree nie miał dostępnych metadanych Git. Ograniczone indeksowanie nie dowodzi kompletności wszystkich plików.

<!-- docs:section details -->
## Znalezione projekty i próby

| Projekt | Potwierdzone działanie | Granica |
|---|---|---|
| wronai/clonebox | API FULL: checkpoint dysku i RAM libvirt, odtworzenie po zatrzymaniu VM i transferze przez Uncrash | BIOS oraz minimalny Linux/BusyBox z PTY; bez aplikacji GUI |
| clonerd-com/clonerd | Zweryfikowane kopiowanie zaszyfrowanego snapshotu; odtworzenie dokumentu | Klucz potrzebny oddzielnie; brak samodzielnego odzyskiwania RAM |
| twinerd/vnclone | Manifest, syntetyczne bazy/historia Agy, natywny odczyt ID; orkiestrator przywraca zbiór i liczbę kart | Rzeczywiste wznowienie rozmowy oraz kolejność kart niezweryfikowane |
| twinerd/twinerd | Własne pulpity NativeClone i rzeczywisty noVNC | Brak automatycznego checkpointu wszystkich procesów hosta |
| twinerd/clonerd-accounts | Obsługa kont/poświadczeń znaleziona w kodzie | Nie jest kopią historii rozmów; nie uruchamiano na kontach użytkownika |
| clonerd-com/app | Interfejs/backend; recovery domyślnie wyłączone | Nie uruchamiano |
| wellmanifest/clonerd | Kontrakty i standardy | Nie jest wykonawcą odtwarzania |

Własna VM: `SAVEDRAM` → FULL checkpoint → `MUTATED` → zatrzymanie → szyfrowany transfer → osobne odtworzenie → revert. VGA/noVNC potwierdziły `SAVEDRAM`. BIOS: 32 MiB RAM/16 MiB dysku. Linux/BusyBox: 256 MiB RAM, własny initramfs; odzyskano pierwotną zmienną, PID powłoki i `/dev/pts/0`. Hostowy PyCharm nieweryfikowany; istniejące domeny libvirt niezmienione.

[Źródła i wyniki JSON](../DATA/UNCRASH_LOCAL_RECOVERY_BACKENDS.json) wiążą rewizje i hashe kodu z dowodami. Testy są w `tests/test_local_backends.py`, opt-in `UNCRASH_LOCAL_BACKENDS=1`. Wszystkie używają wyłącznie własnych danych. Linux wymaga `UNCRASH_LINUX_KERNEL`; pobrany [kernel Debiana](https://deb.debian.org/debian/dists/bookworm/main/installer-amd64/current/images/netboot/debian-installer/amd64/linux) ma hash w JSON. Test buduje initramfs ze statycznego BusyBox i własnego programu `forkpty`; nie montuje katalogów hosta ani nie podłącza sieci.

<!-- docs:section validation -->
## Weryfikacja

Pięć testów backendów zaliczonych, w tym działająca powłoka/PTY we własnej VM. Osobny test Chrome/xterm zaliczony w prawdziwym noVNC. Trzydzieści dwa testy unit/native zaliczonych, w tym aktywny SQLite WAL: zatwierdzony rekord odzyskany, niezakończona transakcja pominięta, `integrity_check=ok`.

Dodano `sqlite_backup_files` i `sqlite_backup_globs`: jawne ścieżki i wzorce względne, online backup w pamięci, limity bajtów/czasu, bez kopii sidecarów WAL/SHM. Spójność dotyczy pojedynczej bazy. vnclone kopiuje źródłowe artefakty zwykłym kopiowaniem: późniejszy backup SQLite nie naprawi już niespójnej kopii źródłowej. Token OAuth Agy i `.credentials.json` są wykluczone przez Uncrash.

Kontrola 503 baz: 502 poprawne, jedna Agy zgłasza `SQLITE_CORRUPT` w kopii i źródle. Drugi silnik SQLite potwierdził błąd źródła. Nie naprawiano ani nie zmieniano oryginału; zachowano zaszyfrowany dowód poza rotacją kopii.

<!-- docs:section risks -->
## Błędy i następne działania

- CLI CloneBox odwołuje się do nieistniejącego `SnapshotType.DISK`; próba zakończyła się błędem przed zmianą VM. Test RAM używa działającego API.
- Adapter Chromium vnclone dubluje karty i zwraca sukces przy niedostępnym CDP. Orkiestrator osobno przeszedł test liczby i zbioru kart po dwukrotnym odtworzeniu.
- vnclone kopiuje token Agy jawnym tekstem; Uncrash go pomija. Nie modyfikowano tych repozytoriów ani zawartości osobistych profili; wybrane pliki użytkownika są teraz czytane do autoryzowanych szyfrowanych kopii.

Następnie: prawdziwa sesja IDE/dostawcy AI we własnej pełnej VM i kontrolowane provider-resume. Usługa ma cztery autoryzowane profile natywnych plików, kompresję i kopie zaczynane co 300 sekund. Dwie pierwsze produkcyjne kopie ukończono; pełne plikowe odtworzenie trzeciej zweryfikowało wszystkie 3779 plików i hashe. Kontrola SQLite jest osobna. Wznowienie czatów/widoków pozostaje nieweryfikowane. Publikację blokują adopcja governance oraz brak chronionego profilu OneDev/Validator; commit/push/PR/merge nie wykonane.

Rust oraz domyślne kopie bez szyfrowania: [konfiguracja `.env`](../SERVICE/UNCRASH_RUST_AND_ENVIRONMENT.md).
