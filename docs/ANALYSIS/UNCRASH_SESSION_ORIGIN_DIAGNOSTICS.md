---
{
  "schema": "wellmanifest.docs/document/v2",
  "id": "uncrash-session-origin-diagnostics",
  "kind": "analysis",
  "version": 1,
  "title": "Session origins and backup diagnostic evidence",
  "status": "draft",
  "owner": "semcod/uncrash",
  "scope": "repository",
  "updated": "2026-10-09",
  "source_revision": "f617cc08ecc22eb40c617813a4df45eea654cdbf",
  "priority": "P1",
  "evidence": [
    "artifact://diagnostic-audit-20261009",
    "artifact://backup-probe-result-20261009",
    "artifact://diagnostics-ticket-002-source-complete"
  ]
}
---

# Session origins and backup diagnostic evidence

<!-- docs:section summary -->
## Cel i rezultat

Diagnostyka rozróżnia proces aplikacji, terminal oraz zapis rozmowy. Potwierdzone pochodzenie procesu nie oznacza odzyskania taba ani przypisania konkretnego ID rozmowy. Obserwacje po wdrożeniu pochodzą z 9 października 2026, 08:59 UTC; stan bieżący wymaga ponownego odczytu.

<!-- docs:section details -->
## Zakres i rozwiązanie

`uncrash diagnose --output NOWY_KATALOG` wykonuje świeży skan procesów, kontrolę kopii i porównanie katalogów sesji z plikami. Raport pozostaje prywatny. Skan sprawdza PID/czas startu przed i po odczycie oraz przodków, zapisuje boot ID i przestrzeń PID. Odczytuje wyłącznie metadane; nie czyta wyjścia terminala ani treści rozmów.

| Dowód | Wynik | Ograniczenie |
| --- | --- | --- |
| Drzewo awarii oraz manifesty z metadanymi JetBrains | 8 procesów Codex pod PyCharm PID546341 | Jedna przechwycona instancja; brak UUID rozmów |
| Świeże drzewa procesów | 3 Codex i 3 agy pod GNOME Terminal | Pochodzenie obecnego procesu, nie historia wszystkich uruchomień |
| 143 manifesty plaintext | Poprawne sumy kontrolne; 133 zawierają metadane IDE | Nie sprawdzono wszystkich payloadów |
| Katalog agy | 1159 unikalnych ID, 502 pliki DB, 657 wpisów bez pliku | Wpis katalogu nie gwarantuje odtworzenia |
| Codex | 1300 plików metadanych | Etykiety cli/vscode/exec nie określają terminala systemowego |

Dawne procesy PyCharma pracowały w `twinerd` (5), `twinerd/twinerd` (1), `digitaltwin-run/twin-campus` (1) i `paxlet-com/willmux` (1). Katalog roboczy sam nie wystarcza do przypisania rozmowy. Znacznik JetBrains odziedziczony przez współdzielony serwer Codex opisuje kontekst startu; jego rozmowy mogą obsługiwać inne klienty. Stare manifesty nie zawierają boot ID, więc pary PID/czas startu nie są globalną tożsamością.

Poprzedni raport używał stałej listy PID-ów i niewystarczająco rozróżniał wpisy katalogu od plików. Nowa diagnostyka skanuje wszystkie dostępne procesy użytkownika i jawnie pozostawia nieustalone powiązania.

<!-- docs:section validation -->
## Weryfikacja

Zestaw 74 testów przeszedł przy dziewięciu pominięciach; po uzupełnieniu obsługi zaszyfrowanych manifestów przeszło 14 testów diagnostyki. Regresje obejmują zmianę tożsamości PID, mylące znaczniki serwera, brak pliku rozmowy, uszkodzony manifest i łańcuch logu, respektowanie force oraz dry-run. Sygnały sprawdzono na atrapach i jednym własnym procesie testowym.

Kanoniczny checker wellmanifest/logs z rewizji cd9d9558e09b9135ef92712096eb951fd524aa75 zweryfikował strumień zdarzeń i 13 runbooków. Dokumenty korzystają z przypiętego wellmanifest/docs 19efafbeb18923cfd51cc69bd519330488500137. Wynik walidacji kontraktu nie oznacza pełnej adopcji governance ani zgody na publikację.

<!-- docs:section risks -->
## Ryzyka i następny krok

Aktywna usługa miała serię błędów capture-failed po kopii 08:06 UTC. Oddzielny magazyn oraz nowa kopia produkcyjna o 08:57 UTC potwierdziły zapis; przyczyna starego procesu pozostaje nieustalona. [Procedura obsługi](../SERVICE/UNCRASH_SERVICE_OPERATIONS.md) wymaga weryfikacji nowej ukończonej kopii.

Właściciel: semcod/uncrash. Następny krok: rejestrować przyłączenie UUID rozmowy do klienta i taba; obecna wersja pozostawia je nieustalone. Brak procesu agy w przechwyconym drzewie nie dowodzi, że nigdy nie działał w innym IDE. Odtworzenie widoków Codex/agy i terminali pozostaje niezweryfikowane.
