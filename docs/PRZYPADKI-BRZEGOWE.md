# Przypadki brzegowe (utwardzanie)

> Skrót dla czytelnika jest w [README](../README.md), pozostałe szczegóły w [SZCZEGOLY.md](SZCZEGOLY.md).

Kod, a nie model, pilnuje 26 sytuacji na styku rozmów i maili (`higiena.py`, `utwardz.py`, `maile.py`, `zasady.py`, `linear_sync.py`, `render.py`). Znaczniki trafiają do `wynik.json` (pola `flagi` pozycji i `kontrola` wyniku), a pozycja z jakimkolwiek znacznikiem trafia do „Do weryfikacji”, nigdy do „Dla agenta”. Testy: `python3 testy/test_utwardzanie.py` (88 testów, bez sieci i modelu; nazwy testów zaczynają się od numeru punktu).

| Sytuacja | Co robi system | Plik | Test |
|---|---|---|---|
| 1. Ta sama rozmowa przetranskrybowana ponownie (inny tekst, ta sama data, godzina i uczestnicy) | bez analizy, Slack z pytaniem; `--wymus` omija | `higiena.py` (odcisk), `utwardz.przed_analiza`, `przetworz.py` | `test_t01_*` |
| 2. Starsza rozmowa wrzucona po nowszej | jej aktualizacje spraw i zmiany decyzji nie nadpisują nowszych; nowe pozycje dodane z oznaczeniem „źródło starsze niż stan karty” | `higiena.zrodlo_starsze`, `linear_sync.main` | `test_t02_*` |
| 3. Rozmowa urwana albo pusta (bardzo krótka, bez wypowiedzi klienta, urwana w pół zdania) | „niepełna transkrypcja”; pozycje bez „Dla agenta” | `higiena.ocena_kompletnosci`, `zasady.przypisz` | `test_t03_*` |
| 4. Pomyleni mówcy (decyzja zastrzeżona u osoby bez prawa, treść wskazuje inną) | „Do weryfikacji”, powód „możliwa pomyłka mówcy” | `higiena.pomylka_mowcy` | `test_t04_*` |
| 5. Liczby, adresy, godziny, kwoty w zmianach do klienta lub do konfiguracji | znacznik „sprawdź z nagraniem” w opisie i raporcie | `higiena.wartosci_do_sprawdzenia`, `linear_sync.build_description` | `test_t05_*` |
| 6. Rozmowa bez nikogo od klienta | „rozmowa wewnętrzna”; karta i Linear klienta bez zmian | `higiena.rozmowa_wewnetrzna`, `linear_sync.main` | `test_t06_*` |
| 7. Nowy klient bez karty | karta z rozmowy (kontakty niepotwierdzone, decydenci jako wniosek), Slack „nowy klient, potwierdź kartę”; nic dla agenta ani do wysyłki | `higiena.karta_nowego_klienta`, `utwardz.po_analizie` | `test_t07_*` |
| 8. Dwóch klientów w jednej rozmowie | pozycje innego klienta nie trafiają do karty ani Lineara tego klienta; jedno zgłoszenie „Do weryfikacji” z listą | `higiena.inny_klient`, `linear_sync.zglosz_cudze_pozycje` | `test_t08_*` |
| 9. Niepewność („chyba”, „może”, „zobaczymy”) i żart albo sarkazm | to nie zobowiązanie ani decyzja: pewność niska | `higiena.niepewnosc`, `ops/zasady.json` → `kontrola` | `test_t09_*` |
| 10. Prośba o coś, czego nie oferujemy | w szkicach nigdy obietnica ani termin, tylko „zapisane”; filtr wysyłki blokuje obietnice | `szkice.PROMPT_REGULY`, `wyslij.filtr_tresci` | `test_t10_*` |
| 11. Dane osobowe (telefony, PESEL, e-maile spoza kontaktów, nazwiska klientów końcowych) | maskowanie przed zapisem wyników, kart, opisów i stron; cytaty porównywane po zamaskowaniu; raport podaje liczbę | `higiena.maskuj*`, `utwardz.po_analizie`, `render.py` | `test_t11_*` |
| 12. Polecenia dla systemu w treści rozmowy lub maila | dane, nie polecenia: bez efektu na kartę i zakazy, ostrzeżenie na Slacku, pozycja do weryfikacji | `higiena.polecenia_w_tresci`, instrukcje `analizuj*.md` | `test_t12_*` |
| 13. Mail bez DKIM/SPF pass dla domeny nadawcy | nic nie wznawia ani nie uchyla; „Do weryfikacji”, Slack | `higiena.uwierzytelnienie`, `maile.py`, `linear_sync.ustal_zrodlo` | `test_t13_*` |
| 14. Autoodpowiedź (Auto-Submitted, „out of office”, „jestem na urlopie”) | bez analizy treści; daty (daty.py) dopisują nieobecność kontaktu w karcie | `higiena.autoodpowiedz`, `maile.przetworz_skrzynke` | `test_t14_*` |
| 15. Załączniki wykonywalne, archiwa i powyżej 10 MB | nie otwierane, nie są dowodem dostarczenia; Slack | `higiena.klasa_zalacznika`, `maile.parsuj_wiadomosc` | `test_t15_*` |
| 16. Mail przekazany (Fwd) | przekazana treść to informacja, nie decyzja; klient w kopii nie jest nadawcą | `higiena.przekazany`, `maile.czysc_tresc` | `test_t16_*` |
| 17. Odpowiedź klienta na nasz wysłany mail (In-Reply-To z historii wysyłek) | przypisanie do właściwych zgłoszeń; krótkie potwierdzenie („dzięki”, „będę”) zamyka je bez nowego zgłoszenia | `higiena.znajdz_wyslany`, `utwardz.obsluz_potwierdzenie` | `test_t17_*` |
| 18. Naprawiona sprawa wraca (Toruń znowu podaje 14:00, a zgłoszenie jest Done) | to samo zgłoszenie wraca do Todo z etykietą „Regresja” i komentarzem „Wróciło” (cytat, źródło); bez nowego zgłoszenia; na stronie klienta znacznik „regresja” i wpis na osi czasu | `linear_sync.sprawdz_regresje`, `generuj_strony.py` | `test_c01_*` |
| 19. Człowiek zamknął, anulował albo zmienił etykiety zgłoszenia lub je usunął | automat tego nie cofa; ponowne otwarcie tylko przez źródło późniejsze niż zmiana człowieka; usunięte lub zarchiwizowane = odrzucone (wpis w karcie, bez ponownego tworzenia). Zmiany człowieka rozpoznaje różnica migawek, bo automat i człowiek używają jednego konta | `czlowiek.py`, `stan_linear.odswiez`, `linear_sync.py`, `przelicz.py` | `test_c02_*` |
| 20. Duża zmiana agenta (powyżej 40 linii albo 3 plików, `ops/zasady.json`) | PR zostaje otwarty bez auto-scalenia, „Decyzja człowieka” z powodem „duża zmiana” | `agent_scal.ocen_pr` | `test_c03_*` |
| 21. Zadanie zmienia plik z otwartym PR innego zadania; gałąź za main | zadanie czeka na scalenie (nie liczy się do limitu); przed scaleniem aktualizacja gałęzi z main i ponowne testy i recenzja; konflikt = oddanie człowiekowi | `agent.pliki_zadania`, `agent_scal.py`, `agent_github.aktualizuj_galaz` | `test_c04_*` |
| 22. Blokada „nic nowego nie startuje” (urlop 19–23.10) | blokuje nowe kampanie, marki, funkcje i teksty; poprawki błędów i korekty istniejącej konfiguracji przechodzą; reguła w `ops/zasady.json` (`blokady`) | `zakazy_czas.powod_blokady`, `agent.py` | `test_c05_*` |
| 23. Wygasający klucz lub token | 7 dni przed linijka w „Uwadze” porannego podsumowania (nagłówek `github-authentication-token-expiration`, daty z `ops/zasady.json`) | `klucze.py`, `podsumowanie.py` | `test_c06_*` |
| 24. Limit albo kredyty modelu skończone | zadanie trafia do kolejki „oczekuje na limit”, nie liczy się jako próba, jedna informacja na Slacku na epizod, ponowienie przy następnym przebiegu (kod wyjścia 75) | `limity.py`, `agent_srodowisko.py`, `przetworz.py` | `test_c07_*` |
| 25. Dzienny bezpiecznik kosztów | limit wywołań modelu dla całego systemu i osobno dla agenta (`budzet_modelu`); po przekroczeniu zatrzymanie, alert raz dziennie, dalej następnego dnia | `limity.Budzet` | `test_c08_*` |
| 26. „Decyzja człowieka” bez reakcji | ponad 2 dni robocze: na górze porannego podsumowania z liczbą dni; ponad 5: osobna wiadomość, raz na zgłoszenie | `podsumowanie.eskalacje`, `eskalacje_osobne` | `test_c09_*` |

Wiersze 18–26 (utwardzanie cz. 2): `python3 testy/test_utwardzanie2.py` (74 testy, bez sieci i modelu, nazwy `test_c01_…` … `test_c09_…`). Nazwy testów w wierszach 1–17: `test_t01_…` … `test_t17_…` (np. `test_t01_inny_tekst_ta_sama_data_godzina_uczestnicy_to_duplikat`).
