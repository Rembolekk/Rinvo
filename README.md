# Analiza rozmów z klientem: prototyp

Zamienia transkrypcję rozmowy z klientem w listę zadań, decyzji, zakazów i ryzyk. Z listy powstaje czytelny raport ze szkicem maila podsumowującego.

## Co robi i dlaczego tak

1. **Ekstrakcja.** Komenda `/analizuj` wypisuje z rozmowy każdą pozycję: typ, właściciela, termin, warunek, status i dosłowny cytat.
2. **Weryfikacja.** Pozycje bez dosłownego cytatu są usuwane. Gdy ktoś zmienił zdanie, zostaje ostatnia wersja. Błąd jest oddzielony od nowej funkcji, a zakazy zapisane osobno. Daty są zestawione ze sobą. To, co nie wynika wprost z cytatu, jest oznaczone jako **wniosek**. Cytaty są po to, żeby każdą pozycję dało się sprawdzić w kilka sekund i żeby model nie dopisywał ustaleń, które nie padły.
3. **Daty liczy kod.** Model wypisuje surowe fakty czasowe (`fakty_czasowe`): urlopy, blokady, terminy i najwcześniejsze starty z dosłownymi cytatami. Skrypt `daty.py` oblicza z nich wolne okna robocze (Pn–Pt) dla każdej sprawy, stosując blokady specyficzne i globalne (np. urlop = blokada dla wszystkich). Wynik trafia do `okna_czasowe` w `wynik.json`. Model nie liczy konfliktów sam — zamiast tego dostarcza dane, kod robi arytmetykę.
4. **Raport.** Stały skrypt `render.py` zamienia `wynik.json` w `raport.html`. Wcześniej porównuje każdy cytat — w pozycjach, aktualizacjach i `fakty_czasowe` — z transkrypcją i odmawia, jeśli któryś nie jest dosłowny. Stały skrypt zamiast HTML pisanego za każdym razem od nowa daje ten sam układ przy każdej rozmowie i twardą kontrolę cytatów.
5. **Człowiek zatwierdza.** Nic nie trafia do klienta automatycznie. Szkic maila i lista zadań to propozycja do przejrzenia.

```mermaid
flowchart LR
    A[transkrypcja .md] --> B["/analizuj<br/>ekstrakcja → weryfikacja"]
    B --> C[wynik.json\nfakty_czasowe]
    C --> D["daty.py<br/>okna robocze"]
    D --> C2[wynik.json\nokna_czasowe]
    C2 --> E["render.py<br/>sprawdzenie cytatów"]
    E --> F[raport.html]
    F --> G{człowiek zatwierdza}
    G -.następny krok.-> H[Linear / Gmail / kalendarz / CRM]
```

## Jak uruchomić

### Jeden przebieg end-to-end (zalecane)

```bash
python3 przetworz.py ops/transkrypcje/<klient>/<plik>.md
```

Skrypt: sprawdza rejestr (pomija, jeśli już przetworzona), uruchamia analizę Claude, render.py, daty.py, linear_sync.py, wysyła Slack i rejestruje. Wymaga `LINEAR_API_KEY` i `SLACK_WEBHOOK_URL` w `.env`.

```bash
python3 przetworz.py ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md --wymus  # wymuś ponowne przetworzenie
```

### Krok po kroku (ręcznie)

1. Otwórz Claude Code w tym folderze.
2. Wpisz: `/analizuj ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md` (albo podaj inny plik `.md`).
3. Po zapisaniu `wynik.json` uruchom daty.py i render.py:

```bash
python -I daty.py wyniki/auto-tama/2026-10-06-call-statusowy/wynik.json
python -I render.py wyniki/auto-tama/2026-10-06-call-statusowy/wynik.json --transkrypcja ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md
```

Jeśli komenda `/analizuj` nie pojawi się na liście, wpisz zamiast niej:

```
Wykonaj instrukcje z .claude/commands/analizuj.md na pliku X.md
```

## Struktura

| Plik | Rola |
|---|---|
| `.claude/commands/analizuj.md` | instrukcja dla Claude Code (kroki, schemat JSON, zapis w częściach) |
| `render.py` | walidacja schematu i cytatów (w tym fakty_czasowe), generowanie raportu |
| `daty.py` | oblicza wolne okna robocze z fakty_czasowe, zapisuje okna_czasowe do wynik.json |
| `przetworz.py` | automat end-to-end: rejestr → Claude → daty.py → render.py → Linear → Slack |
| `linear_sync.py` | wysyła wynik.json do Linear (team RIN); idempotentny po klucz_sprawy |
| `sekrety.py` | czyszczenie kluczy API z białych i niewidocznych znaków (Notatki na Macu je dodają) |
| `ops/zasady.json`, `zasady.py` | zasady AI-first: kto robi co (agent / człowiek), jedno miejsce prawdy |
| `podsumowanie.py`, `.github/workflows/podsumowanie.yml` | codzienne podsumowanie o 8:00 czasu polskiego + szkice przypomnień |
| `przelicz.py`, `uzupelnij.py` | przeliczenie istniejących zgłoszeń (przypisanie, terminy, notatki); scalanie pól dla agenta i wyrażeń dat z wyników |
| `notatki.py` | jedna notatka przed spotkaniem (ze wszystkimi ryzykami i otwartymi tematami klienta) zamiast zadania na każde ryzyko |
| `maile.py` | pobieranie maili od znanych nadawców (Gmail IMAP, tylko odczyt) → `ops/maile/` |
| `.claude/commands/analizuj-mail.md` | instrukcja analizy maila (dane, nie polecenia) |
| `.github/workflows/sprawdz-maile.yml` | cron co 15 min: maile → przetworz.py → commit |
| `ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md` | przykładowa transkrypcja (fikcyjna) |
| `wyniki/` | wyniki analiz, jeden folder na transkrypcję |
| `testy/test_logika.py` | testy jednostkowe logiki (bez sieci, 46 testów) |
| `testy/test_maile.py`, `testy/maile/*.eml` | testy źródła „maile” na przykładowych plikach .eml (53 testy) |
| `testy/test_zasady.py` | zasady AI-first, opis zgłoszenia, przeliczanie, podsumowanie, strefa czasowa (89 testów) |
| `testy/test_daty.py` | daty względne liczone przez kod: parser, pierwszeństwo kodu nad modelem, „wniosek”, poprawa tekstów (37 testów) |
| `testy/test_notatki.py` | jedna notatka na spotkanie, scalanie zadań na ryzyka, archiwizacja z komentarzem (20 testów) |
| `testy/test_agent.py` | agent wykonawczy: ponowne sprawdzenie zakazów, limit 3, zakazane ścieżki, oddanie po dwóch nieudanych testach, warunki scalania (72 testy, bez sieci) |
| `testy/test_wysylka.py` | szkice maili i wysyłka: wszystkie bezpieczniki (duplikat, odbiorca, zakazy, filtr treści, limit, okno czasowe, urlop), mail zbiorczy, prośba o informację w starszych cytatach, szkice od razu dla zgłoszeń „do klienta” (83 testy, bez poczty) |
| `testy/uruchom.py` | runner testów oczekiwań (X/Y, exit 0/1) |
| `testy/oczekiwania/` | pliki oczekiwań zakotwiczone w cytatach |
| `kontrola.md` | kontrola jakości na przykładowej rozmowie |
| `logi/przebiegi/` | logi automatycznych przebiegów przetworz.py |
| `logi/` | logi z pracy z AI (sesje Claude Code: surowe `.jsonl` i czytelne `.md`) |

## Automat przetwarzania (`przetworz.py`)

`przetworz.py` uruchamia pełen pipeline bez interakcji:

```
transkrypcja.md
  → sha256 check (rejestr)
  → claude --print (analizuj.md) → wynik.json
  → render.py (sprawdzenie cytatów) → raport.html
  → daty.py (okna robocze) → wynik.json [okna_czasowe]
  → linear_sync.py → Linear
  → Slack (podsumowanie z linkami)
  → rejestr (hash transkrypcji)
```

Wymagane zmienne w `.env`:
- `LINEAR_API_KEY` — klucz API Linear (team RIN)
- `SLACK_WEBHOOK_URL` — webhook do kanału powiadomień

Zabezpieczenia: lock file (jeden przebieg jednocześnie), rejestr rejestruje dopiero po pełnym sukcesie (retry jest bezpieczny), klucze nigdy nie trafiają do logów.

Log trafia do `logi/przebiegi/<timestamp>-<klient>.log`.

`--bez-analizy` pomija model i przetwarza istniejący `wynik.json` (render, daty, Linear, testy, Slack): do naprawy stanu po poprawce kodu, bez ponownego wołania Claude'a.

Klucze z `.env` i ze zmiennych środowiskowych są czyszczone z białych i niewidocznych znaków (`sekrety.py`). Klucz wklejony z Notatek potrafi mieć na końcu enter albo `\u2028` i wygląda poprawnie, a serwer go odrzuca. W logu pojawia się tylko ostrzeżenie z nazwą zmiennej i liczbą usuniętych znaków, nigdy wartość.

### Wiadomość na Slacku (Block Kit)

Wiadomości są krótkie: do przeczytania w 10 sekund, wysyłane jako Block Kit przez webhook (z tekstem zapasowym do powiadomień). Wspólne klocki są w `slack_widok.py`.

Po przetworzeniu rozmowy albo maila: **jedno zdanie, co się zmieniło** (np. „rozmowa z 13.10 przetworzona. Nowych zgłoszeń: 4, zamkniętych: 1, wznowionych: 1”; dla maila „mail „temat” przetworzony”), potem **tylko to, co wymaga człowieka** (maks. 5 linijek: tytuł do 60 znaków jako link, klient, jedno słowo powodu: pieniądze, klient, zakaz, decyzja, weryfikacja; do tego powtarzające się ryzyka, odrzucone zmiany bez uprawnień i nieudane testy) i **link do widoku wszystkich otwartych zgłoszeń w Linearze**. Gdy nic nie wymaga człowieka: „Nic nie wymaga człowieka.” Model i wynik testów to szara linijka na samym dole. Bez zer, bez powtórzeń i bez technicznych nazw (identyfikatory, klucze spraw) w tekście, tylko w linkach. Tytuły i tematy z maili są oczyszczane ze znaczników Slacka (`<!channel>`, linki).

## Daty liczy kod (`daty.py`)

```bash
python3 -I daty.py wyniki/<klient>/<nazwa>/wynik.json
```

Czyta pole `fakty_czasowe` (ekstrahowane przez model z transkrypcji), oblicza wolne okna robocze Pn–Pt dla każdej sprawy i zapisuje wynik w `okna_czasowe`. Typy faktów:

| Typ | Znaczenie |
|---|---|
| `urlop` / `blokada` | Okres, w którym nie można pracować nad zadaniem |
| `termin` | Ostateczny termin dla danej sprawy |
| `start_nie_wczesniej` | Najwcześniejsza data startu |

`dotyczy: "wszystko_nowe"` = blokada globalna (np. urlop = blokuje wszystkie nowe wdrożenia).

### Daty względne liczy kod, nie model

Model źle przelicza „do piątku” czy „przyszły czwartek” (zdarzyło się: lista lekarzy z terminem 17.10, czyli w sobotę, zamiast piątku 16.10). Dlatego obok daty model zapisuje **dosłowne wyrażenie** (`wyrazenie` w `fakty_czasowe`, `termin_wyrazenie` w pozycji), a `daty.py` liczy z niego datę względem **daty źródła** (rozmowy albo maila; dla maila z pliku maila, nie z pola modelu):

- dzień tygodnia = najbliższy **następny** (ten sam dzień co źródło = za tydzień); „przyszły czwartek” = czwartek następnego tygodnia; wszystkie odmiany nazw dni,
- „jutro”, „pojutrze”, „dziś”; liczebniki dnia miesiąca („dwudziesty siódmy”, „piętnastego”, także z miesiącem i dniem tygodnia), daty „27.10”, „27 października”, zakresy „od dziewiętnastego do dwudziestego trzeciego”,
- „w tym tygodniu” = do piątku, „w przyszłym tygodniu” = pn–pt następnego, „do końca miesiąca” = ostatni dzień miesiąca.

**Gdy kod umie policzyć, jego data wygrywa nad datą modelu, a rozbieżność trafia do `ostrzezenia_dat`** (raport ją pokazuje, tak samo `data_modelu`/`termin_modelu` w wyniku). Gdy nie umie (wyrażenie złożone jak „od jutra, środa i czwartek”, „po urlopie”), zostaje data modelu z oznaczeniem `zrodlo_daty: "wniosek"` (`termin_zrodlo` dla pozycji). Znaczenie zależy od typu faktu (termin = koniec, „od X” = początek, „w tym tygodniu” przy starcie to zakaz, nie data startu). Gdy kod zmienia termin pozycji, poprawia też tę samą datę w jej tytule, przypomnieniu i szkicu maila. Przeliczenie jest idempotentne. Wyrażenia w starszych wynikach dopisuje `.claude/commands/uzupelnij-daty.md` (model wskazuje tylko słowa, `uzupelnij.py --wyrazenia` scala je z walidacją), a `przelicz.py` synchronizuje terminy w Linearze.

## Synchronizacja z Linear

Po przejrzeniu raportu: wyślij pozycje do Linear jednym poleceniem.

```bash
python3 linear_sync.py wyniki/<klient>/<nazwa>/wynik.json --klient <slug>
python3 linear_sync.py wyniki/<klient>/<nazwa>/wynik.json --klient auto-tama --dry-run
```

Wymaga `LINEAR_API_KEY` w `.env`. Klucz musi mieć dostęp do zespołu `RIN`.

- Sprawdza i tworzy brakujące etykiety w zespole.
- Sekcja 1 (zrób teraz) → stan **Todo**; `bug`/`zmiana_konfiguracji`/`poprawka_bazy_wiedzy` + `pewnosc: wysoka` + brak `konflikt_z_zakazem` → etykieta **Dla agenta**.
- Sekcja 2 (czeka na klienta) → **Backlog** + etykieta **Czeka na klienta**.
- Sekcja 3 (backlog produktowy) → **Backlog** + etykieta **Produkt**; jeśli ta sama funkcja pojawia się u ≥ 2 klientów → etykieta **Wielu klientów**.
- Sekcja 4 (zakazy) → zapisuje do `ops/klienci/<klient>/karta.json`, **bez zgłoszenia w Linear**.
- Sekcja 5 (ryzyka) → **Todo** + etykieta **Ryzyko** + priorytet High; przy ≥ 2 wystąpieniach tego samego `temat_ryzyka` → etykieta **Powtarzające się ryzyko** + Urgent.
- **Strażnik zakazów**: pozycja z `konflikt_z_zakazem` → **Backlog** + etykieta **Zablokowane przez zakaz**, bez **Dla agenta**.
- **Pewność niska**: `pewnosc: niska` → etykieta **Do weryfikacji**.
- **Idempotentny po klucz_sprawy**: ta sama `klucz_sprawy` z innego źródła → komentarz w istniejącym zgłoszeniu. Ochrona przed duplikatami opiera się na kluczu sprawy, nie na sha256 pliku.
- **Aktualizacje otwartych spraw**: `aktualizacje_spraw` z wynik.json → zmiana stanu istniejącego zgłoszenia w Linear (Todo/Done/Cancelled). Aktualizacja musi pochodzić z rozmowy późniejszej niż ta, z której sprawa pochodzi; ta sama aktualizacja nie zadziała dwa razy, a zgłoszenie, które już jest w docelowym stanie, nie dostaje drugiego komentarza.
- **Sprawa wspomniana ponownie** (ta sama `klucz_sprawy`): komentarz z nowym cytatem, **nowy termin** z najnowszej rozmowy oraz — dla ryzyk — licznik rozmów w karcie i eskalacja (**Powtarzające się ryzyko** + Urgent) także dla zgłoszenia, które już istnieje.
- **Zakazy** dostają unikalne id w karcie (numeracja z rozmowy zaczyna się od Z1, więc przy kolizji linear_sync nadaje kolejny wolny numer), a nie są pomijane.
- Po każdym przebiegu regeneruje `ops/klienci/<klient>/karta.md`.

## Pamięć między rozmowami

Kontekst klienta jest przechowywany w `ops/klienci/<klient>/karta.json`:

- **`zakazy`** — lista aktywnych zakazów (id + cytat). Analizuj.md sprawdza każdą pozycję względem tych zakazów i ustawia `konflikt_z_zakazem`.
- **`otwarte_sprawy`** — mapowanie `klucz_sprawy → {linear_id, identifier, url, zrodla[]}`. Używane do idempotentności i aktualizacji statusów.
- **`ryzyka`** — historia wystąpień ryzyk (per temat, per źródło). Przy ≥ 2 unikalnych źródłach → eskalacja.
- **`historia_zakazow`** — uchylone zakazy (zachowane dla audytu).

`ops/produkt/prosby.json` — globalna lista próśb o funkcje produktowe, mapowanie `klucz_funkcji → [{klient, cytat, zrodlo}]`. Przy ≥ 2 klientach → etykieta **Wielu klientów**.

`ops/.przetworzone.json` — rejestr sha256 **transkrypcji** (nie wynik.json). `przetworz.py` pomija transkrypcje, których hash jest już w rejestrze; rejestruje dopiero po pełnym sukcesie (Linear + Slack). Flaga `--wymus` pomija sprawdzenie.

## Struktura ops/

```
ops/
  transkrypcje/<klient>/        – transkrypcje rozmów
  klienci/<klient>/
    karta.json                  – zakazy, decydenci, otwarte sprawy, historia ryzyk
    karta.md                    – czytelna wersja karty (generowana przez linear_sync.py)
  produkt/
    prosby.json                 – globalna lista próśb o funkcje (aktualizowana przez linear_sync.py)
  .przetworzone.json            – rejestr sha256 transkrypcji (zarządza przetworz.py)
  .przetworz.lock               – lock file (jeden przebieg jednocześnie)
```

## Założenia

- Silnikiem jest Claude Code na subskrypcji, bez klucza API.
- Integracje z narzędziami (Linear, Gmail, kalendarz, CRM) są opisane jako następny krok, ale nie zbudowane.
- Nic nie wychodzi do klienta bez zatwierdzenia przez człowieka.
- Analiza zakłada perspektywę dostawcy („nasz zespół”). Nazwy firm i osób pochodzą wyłącznie z transkrypcji.

## Automatyczny start

Nagranie trafia do repo jako transkrypcja, a GitHub Actions sam uruchamia `przetworz.py` w chmurze.

```mermaid
flowchart LR
    A[nagranie] --> B[repo: ops/transkrypcje/&lt;klient&gt;/*.md]
    B -->|push na main| C[GitHub Actions<br/>przetworz-rozmowy.yml]
    C --> D["przetworz.py<br/>analiza Claude → render → daty"]
    D --> E[Linear]
    D --> F[Slack]
    D --> G[karta klienta, wyniki, rejestr<br/>commit do repo]
```

- **Wyzwalacz:** push na `main` zmieniający `ops/transkrypcje/**/*.md` albo ręcznie (*Actions → Przetwarzanie rozmów → Run workflow*, opcjonalnie ze ścieżką transkrypcji).
- **Wykrywanie:** workflow bierze pliki dodane lub zmienione w pushu. Przy pierwszym pushu albo braku poprzedniego commita bierze wszystkie transkrypcje, a już przetworzone pomija rejestr sha256.
- **Jedna rozmowa naraz:** `concurrency` bez anulowania trwających przebiegów. Każdy przebieg startuje od najnowszego `main`, więc widzi karty klientów zaktualizowane przez poprzedni.
- **Zapis wyników:** po każdej transkrypcji commit `[automat] przetworzono <plik> [skip ci]` (`wyniki/`, `ops/klienci/`, `ops/produkt/`, `ops/.przetworzone.json`, `logi/przebiegi/`). `[skip ci]` i push tokenem `GITHUB_TOKEN` nie uruchamiają workflow drugi raz. Przy odrzuconym pushu: `pull --rebase` i ponowna próba.
- **Błędy:** gdy `przetworz.py` się wysypie, wysyła alert na Slacka, a workflow kończy się błędem.
- **Model:** zmienna `RINVO_MODEL` (w GitHubie: *Settings → Variables*), domyślnie `claude-sonnet-5-5`. Model jest podany w wiadomości na Slacku.

Sekrety (*Settings → Secrets and variables → Actions*): `CLAUDE_CODE_OAUTH_TOKEN` (z `claude setup-token`), `LINEAR_API_KEY`, `SLACK_WEBHOOK_URL`. Bez pliku `.env` `przetworz.py` czyta je ze zmiennych środowiskowych.

## Źródło: maile

Drugie źródło obok transkrypcji: maile od klienta. Skrzynka automatu to osobne konto Gmail (`GMAIL_ADDRESS`).

> **Uwaga: repo demo jest publiczne**, więc wszystkie dane (maile, karty klientów, wyniki) są fikcyjne. W produkcji repo Rinvo-Ops jest prywatne.

```mermaid
flowchart LR
    A[mail od klienta] --> B["maile.py<br/>Gmail IMAP, tylko odczyt"]
    B -->|znany nadawca| C[ops/maile/&lt;klient&gt;/&lt;data&gt;-&lt;slug&gt;.md]
    B -->|nieznany| S1[Slack: pominięto nadawcę]
    C --> D["przetworz.py<br/>analizuj-mail.md"]
    D --> E[Linear + Slack + karta klienta]
```

- **`maile.py`** (biblioteka standardowa: `imaplib`, `email`) otwiera INBOX **tylko do odczytu** (`SELECT readonly`, treść przez `BODY.PEEK`). Niczego nie wysyła, nie usuwa, nie oznacza ani nie przenosi; test pilnuje, że kod używa wyłącznie `login/select/uid/logout`.
- **Kto jest znany:** tylko nadawcy z pól `kontakty` w kartach klientów albo z `domeny` klienta. Od nieznanego nadawcy treść **nie jest pobierana**.
- **Mało szumu na Slacku** (skrzynka to zwykła poczta: LinkedIn, Uber, Instagram…):
  - maile **automatyczne** (nagłówki `List-Unsubscribe`, `Auto-Submitted` inny niż `no`, `Precedence: bulk/list/junk`, adresy `noreply`, `no-reply`, `notifications`…) są pomijane całkowicie i po cichu: bez Slacka, bez rejestru, bez pobierania treści,
  - pozostali nieznani nadawcy to **jedna linijka na przebieg**, bez adresów: „pominięto N maili od nieznanych nadawców" (w rejestrze są tylko jako hasze, bo repo bywa publiczne),
  - osobny alert z adresem tylko dla nadawcy z domeny klienta (patrz niżej),
  - **data włączenia** (`wlaczono` w `ops/.maile.json`): nie czytamy historii skrzynki, tylko maile od tego dnia.
- **Domena klienta** (`domeny`, np. `autotama.pl`): mail z adresu w tej domenie, którego nie ma w kontaktach, jest czytany, a nadawca trafia do `kontakty` z flagą „nowy, bez prawa decyzji" (`potwierdzony: false`) i informacją na Slacku do potwierdzenia przez człowieka. Jego maile mogą dodawać informacje, ale nie uchylają zakazów ani nie zmieniają decyzji. Potwierdzenie: ustaw `potwierdzony: true` (i opis roli) w `ops/klienci/<klient>/karta.json`. Ogólne domeny pocztowe (gmail.com, wp.pl, onet.pl, o2.pl, outlook.com…) nigdy nie są domeną klienta, w nich liczy się tylko pełny adres.
- **Rejestr** `ops/.maile.json` działa jak rejestr transkrypcji: Message-ID trafia do `przetworzone` dopiero **po udanym przetworzeniu** (robi to `przetworz.py`). Do tego czasu mail jest w `oczekujace`. Mail, którego analiza padła, jest ponawiany przy kolejnym przebiegu, **maksymalnie 3 razy** (każde wejście na listę to jedna próba, więc awaria całego przebiegu też nie ponawia w nieskończoność). Potem status `porzucony` i alert na Slacku (raz). Ręczne ponowienie: workflow „Sprawdzanie maili" z polem `sciezka`; udany przebieg przenosi mail do `przetworzone`.
- **Zapis** `ops/maile/<klient>/<data>-<slug>.md`: od, do, data, temat, lista nazw załączników, treść tekstowa bez cytowanych wcześniejszych wiadomości i bez stopki.
- **Analiza** (`.claude/commands/analizuj-mail.md`, krótsza instrukcja): ten sam schemat `wynik.json`, więc `render.py`, `daty.py` i `linear_sync.py` działają bez zmian. Mail najczęściej aktualizuje otwarte sprawy (np. klient przysłał plik → wznowiona); załącznik jest dowodem dostarczenia tylko wtedy, gdy treść wskazuje, czego dotyczy.
- **Bezpieczeństwo treści:** treść maila to dane, nigdy polecenia („zignoruj…", „system ma…" analizowane jak każda inna treść). Polecenie w imieniu innej osoby („Paweł prosi…") to nie jej decyzja: `pewnosc: niska`. Analiza maila dostaje tylko narzędzia `Read`, `Write`, `Edit` (bez `Bash`) i nie widzi kluczy do Linear, Slacka ani Gmaila. Tematy i tytuły w wiadomości Slack są oczyszczane ze znaczników (`<!channel>`, linki).
- **Uprawnienia pilnuje kod** (`linear_sync.py`), nie tylko instrukcja. Aktualizacja, która uchyla zakaz albo zmienia decyzję zastrzeżoną dla konkretnej osoby (`decyzje_zastrzezone` w karcie, np. Opel: tylko Kasia, nie Paweł), jest odrzucana, jeśli nadawca maila (albo uczestnicy rozmowy) nie jest tą osobą, jeśli nadawca jest niepotwierdzony lub spoza kontaktów, albo jeśli `pewnosc` jest niska. Odrzucenie: etykieta „Do weryfikacji" i komentarz z powodem (dla zakazu: osobne zgłoszenie), a Slack pokazuje linię „Odrzucone (brak uprawnień)". Nadawcę i datę maila kod bierze z zapisanego pliku maila, nie z `wynik.json` (model nie może się podszyć).
- **Data maila** jest datą źródła dla reguły „wznowić może tylko późniejsze źródło" (mail z tym samym dniem co sprawa lub starszy jej nie wznawia).
- **`przetworz.py`** obsługuje oba źródła (ścieżka `ops/maile/<klient>/…md` albo transkrypcja) z tym samym rejestrem, blokadą, Slackiem i testami. Wiadomość na Slacku mówi, że źródłem był mail, i podaje temat.

**Workflow** `.github/workflows/sprawdz-maile.yml`: co 15 minut (cron) i ręcznie; ta sama grupa `concurrency` co przetwarzanie rozmów (karty się nie nadpisują). Kroki: `maile.py` → commit rejestru i maili → `przetworz.py` dla każdego nowego maila → commit „[automat] mail <temat> [skip ci]" i push (przy konflikcie `pull --rebase`). **Cron startuje dopiero po ustawieniu zmiennej repozytorium `MAILE_WLACZONE=true`**; ręczne uruchomienie działa zawsze, a z polem `sciezka` przetwarza ponownie jeden zapisany mail. Sekrety: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (hasło aplikacji; konto z 2FA i włączonym IMAP) oraz dotychczasowe. Klucze są czyszczone z niewidocznych znaków (`sekrety.py`) i nigdy nie są wypisywane.

Znane ograniczenia: nagłówek `From` może być sfałszowany (nie sprawdzamy DKIM/SPF), więc przy prawdziwym wdrożeniu warto to dodać; data źródła ma dokładność do dnia (mail z tego samego dnia co rozmowa nie wznawia jej spraw); harmonogram GitHuba bywa opóźniony, a w repo bez aktywności jest po 60 dniach wyłączany.

## AI-first: kto robi co

Firma pracuje AI-first: agenci (Claude, Cursor) podpięci do Lineara robią ok. 90% pracy, łącznie z poprawkami i nowymi funkcjami. Ludzie dostają tylko to, co naprawdę wymaga człowieka. **Wszystkie reguły są w jednym, czytelnym pliku `ops/zasady.json`** (słowa, powody, progi, szablony); zmieniasz go bez dotykania kodu. Silnik (`zasady.py`) jest jeden dla `linear_sync.py`, Slacka, podsumowania i testów.

**Domyślnie każda pozycja idzie do agenta** (etykieta **Dla agenta**). Do człowieka (etykieta **Decyzja człowieka** + komentarz z powodem) trafia pozycja tylko wtedy, gdy:

| Reguła | Kiedy |
|---|---|
| `pieniadze` | kosztuje pieniądze albo dotyczy cen i umów (typ finanse, słowa jak SMS, cena, rabat, faktura, kwota, umowa) |
| `do_klienta` | trafia do klienta (mail, przypomnienie, oferta, zaproszenie): agent przygotowuje gotowy szkic w zgłoszeniu (`szkic_klienta`), człowiek tylko wysyła |
| `zakaz` | jest w konflikcie z zakazem klienta (dodatkowo etykieta Zablokowane przez zakaz) |
| `decyzja_zastrzezona` | dotyczy decyzji zastrzeżonej w karcie dla konkretnej osoby (`decyzje_zastrzezone`) |
| `pewnosc_niska` | pewność niska (dodatkowo Do weryfikacji) |
| `nieodwracalne` | jest nieodwracalna: wyłączenie usługi, usunięcie danych, zmiana umowy |

- **Prośby produktowe** (sekcja 3): do agenta dopiero przy etykiecie **Wielu klientów** (ta sama funkcja u ≥ 2 klientów w `prosby.json`) albo gdy to drobna zmiana z wysoką pewnością (`rodzaj` zmiana lub błąd). Pojedyncza duża funkcja od jednego klienta: **Decyzja człowieka** z powodem „priorytet produktowy".
- **Ryzyka** (sekcja 5): samo ryzyko ma etykietę **Ryzyko** (dla ludzi). Agent dostaje **jedną notatkę na każde zaplanowane spotkanie z klientem** (repo `rinvo-ops`), zawierającą **wszystkie ryzyka i otwarte tematy tego klienta** (z linkami, cytatami, statusami i terminami). Gdy spotkanie nie jest zaplanowane, jedno zadanie na klienta (o ile ma ryzyka). Opis notatki odświeża się przy każdej zmianie (`opis_hash` w karcie), a dawne zadania „na każde ryzyko” są scalane: jedno przekształcane w notatkę, reszta archiwizowana z komentarzem, gdzie przeniesiono treść. Szablony i kryteria są w `ops/zasady.json` (`notatki`), a spotkania typu szkolenie (`pomijaj_spotkania_slowa`) nie dostają osobnej notatki. Logika: `notatki.py`.
- **Sprawy czekające na klienta** (sekcja 2): tylko Czeka na klienta. Przypisanie (agent albo człowiek) liczy się dopiero przy wznowieniu i jest zapamiętane w karcie (`po_wznowieniu`).
- **Zgłoszenie dla agenta**: analiza (`analizuj.md`, `analizuj-mail.md`, KROK 3c) dopisuje do pozycji `cel`, `kryteria_akceptacji`, `jak_sprawdzic`, `repo` (`rinvo` = kod aplikacji, `rinvo-ops` = wiedza, dokumenty, konfiguracja klienta, `brak`) i, gdy rezultat idzie do klienta, `szkic_klienta`. `linear_sync.py` składa opis w stałym układzie: **Cel, Kontekst (z cytatami), Kryteria akceptacji (lista do odhaczenia), Jak sprawdzić, Repo, Czego nie ruszać** (zakazy klienta i decyzje zastrzeżone), a dla człowieka także **Dlaczego człowiek** i **Szkic dla klienta**.
- **Brak kryteriów akceptacji**: zgłoszenie nie dostaje Dla agenta, tylko **Do weryfikacji** z powodem „brak kryteriów".
- **Istniejące zgłoszenia**: `python3 przelicz.py` pokazuje raport (kto zmienia przypisanie i dlaczego), a `--zastosuj` przelicza etykiety i opisy w Linearze bez tworzenia duplikatów (zgłoszenia są wiązane z kartą po kluczu sprawy). Pola dla agenta w starszych wynikach uzupełnia `.claude/commands/uzupelnij-agent.md`; model zapisuje tylko `pola-agenta.json`, a `uzupelnij.py` scala je z `wynik.json` z walidacją (nie nadpisuje istniejących pól).

### Codzienne podsumowanie (`podsumowanie.py`)

Jedna wiadomość na Slacku (Block Kit) o **8:00 czasu polskiego** (workflow `.github/workflows/podsumowanie.yml`, ręcznie z `--wymus`), do przeczytania w 10 sekund:

1. pierwsza linijka: „Dziś potrzebujemy Cię w N sprawach” (albo „Dziś nic nie wymaga człowieka.”),
2. **Wymaga człowieka**: maks. 5 pozycji, każda w jednej linijce (tytuł do 60 znaków bez prefiksu klienta jako link, klient, jedno słowo powodu); reszta jako „… i N więcej”,
3. **Uwaga**: tylko powtarzające się ryzyka i sprawy po terminie; gdy ich nie ma, sekcja znika,
4. jedna linijka o agentach („Agenci pracują nad X zadaniami, Y skończone od wczoraj”) i jedna o czekaniu na klientów („Czekamy na klientów w Z sprawach, najbliższy termin: data, sprawa”),
5. na dole link do widoku wszystkich otwartych zgłoszeń w Linearze.

**Każde zgłoszenie występuje w wiadomości tylko raz, w najważniejszej kategorii** (kolejność ważności: powtarzające się ryzyka, po terminie, decyzje człowieka, do weryfikacji, czeka na klienta, u agentów, nowe). Dlatego np. sprawa po terminie, która jest też u agentów, jest tylko w „Uwadze”, a liczniki agentów i czekania jej nie zawierają. „Po terminie” to każde otwarte zgłoszenie z minionym terminem. Bez list „nowe od wczoraj” i bez technicznych nazw w tekście (tylko w linkach). Słowa powodów są w `ops/zasady.json` (`slowa_powodow`).

- **Strefa czasowa:** cron GitHuba działa w UTC, więc workflow odpala skrypt o 06:00 i 07:00 UTC, a skrypt sam sprawdza czas w `Europe/Warsaw` (lato UTC+2, zima UTC+1) i wysyła raz dziennie w oknie 8:00–12:00 (znosi opóźnienia crona i zmianę czasu).
- **Przypomnienia:** gdy termin sprawy czekającej minął, limit przypomnień z rozmowy nie jest wyczerpany (brak limitu = `przypomnienia.domyslny_limit`) i klient nie prosił o brak przypomnień (limit 0 albo zakaz „nie przypominaj" w karcie), podsumowanie **przygotowuje szkic** w komentarzu zgłoszenia i podaje go na Slacku. **Nigdy nie wysyła nic do klienta.** Każdy szkic zwiększa `wykorzystane` w karcie (`otwarte_sprawy.<klucz>.przypomnienie`), więc limit nie zostanie przekroczony.

## Agent wykonawczy

Agent sam wykonuje zgłoszenia z Lineara w osobnym repozytorium [Rinvo-app](https://github.com/Rembolekk/Rinvo-app) (symulacja produktu: konfiguracja agenta głosowego klienta w `config/` i baza wiedzy w `wiedza/`). Człowiek wchodzi tylko w wyjątkach.

**Które zgłoszenia.** Etykiety `Dla agenta` + `repo: rinvo-app`, stan Todo. Etykietę `repo: …` dostaje każde nowe zgłoszenie (z pola `repo` i mapowania w `ops/zasady.json`: zmiany konfiguracji i bazy wiedzy trafiają do `rinvo-app`); `python3 przelicz.py` nadaje ją istniejącym. Do 3 zgłoszeń na przebieg.

**`agent.py`** (dla każdego zgłoszenia):
1. ponownie sprawdza zakazy i decyzje zastrzeżone z AKTUALNEJ karty klienta; konflikt: etykieta `Zablokowane przez zakaz`, komentarz, pominięcie (gdy sprawdzenia nie da się wykonać, agent niczego nie rusza),
2. stan In Progress, komentarz „Agent przejął”,
3. klonuje Rinvo-app, gałąź `rin-41-…` (Linear sam łączy PR ze zgłoszeniem),
4. `claude -p` z celem, kryteriami, „jak sprawdzić” i „czego nie ruszać”; ma tylko Read/Write/Edit i może zmieniać wyłącznie `config/` i `wiedza/` (kod cofa wszystko inne, w tym `.github/`, `tests/`, `zakazy/`, i szuka sekretów w diffie),
5. testy; po porażce jedna poprawka i testy jeszcze raz; dalej czerwone: bez PR, komentarz z powodem, etykieta `Do weryfikacji`, stan z powrotem Todo,
6. PR (tytuł ze zgłoszenia, `Fixes RIN-xx`, kryteria, cytat klienta, czego nie ruszać) i link w komentarzu w Linearze.

**`agent_scal.py`** scala PR (squash) tylko gdy JEDNOCZEŚNIE: testy zielone, CodeRabbit skończył recenzję ostatniego commita bez uwag, zmiana dotyka tylko `config/` lub `wiedza/`, zgłoszenie ma etykietę `Konfiguracja`. Uwagi CodeRabbit agent uwzględnia raz; dalej uwagi albo zmiana poza ścieżkami: etykieta `Decyzja człowieka` z powodem „przegląd kodu”. Po scaleniu zgłoszenie dostaje Done.

**Slack** tylko na koniec: „Agent naprawił: <tytuł> (link do PR)” albo „Agent oddał: <tytuł>, powód”.

**Workflow** `Agent wykonawczy` (`agent.yml`): ręcznie (zawsze), co 15 minut i po każdym udanym przetworzeniu rozmowy lub maila (te dwa dopiero po ustawieniu zmiennej repozytorium `AGENT_WLACZONY=true`). Sekret `AGENT_GITHUB_TOKEN` (dostęp tylko do Rinvo-app) istnieje wyłącznie w sekretach GitHuba; agent nie działa lokalnie. Testy logiki bez sieci: `python3 testy/test_agent.py`.

## Kontakt z klientem

Pętla: agent pisze szkic maila, człowiek daje jedną zgodę, automat wysyła.

1. **Szkice (`szkice.py`, w workflow „Agent wykonawczy”).** Gdy zgłoszenie przechodzi na Done, a klient prosił o informację („napisz, jak będzie poprawione”) albo zgłoszenie jest typu „do klienta” (przypomnienie, zaproszenie, zestawienie), agent pisze szkic w imieniu Marka: krótko, po ludzku, tylko ustalenia z rozmów. Model dostaje wyłącznie cel, kontekst z cytatami klienta i kryteria (bez zakazów, identyfikatorów i danych innych klientów). Szkic to komentarz w Linearze i etykieta `Szkic gotowy`. Szkice dla tego samego klienta z jednego dnia łączą się w jeden mail zbiorczy (treść w najstarszym zgłoszeniu, w pozostałych tylko wskazanie).
2. **Zgoda.** Człowiek dodaje etykietę `Wyślij` (na zgłoszeniu ze szkicem). To jedyna czynność człowieka. Poprawka treści: nowy komentarz w tym samym układzie, wysłany będzie najnowszy.
3. **Wysyłka (`wyslij.py`, osobne zadanie w workflow „Sprawdzanie maili”, co 15 minut).** SMTP z `GMAIL_ADDRESS` (hasło aplikacji) do kontaktu z karty klienta. Potem komentarz „Wysłano <data>”, zdjęcie `Wyślij` i `Szkic gotowy`, etykieta `Wysłano` i wpis w `karta.json` → `historia_wysylek` (data, Message-ID, temat, zgłoszenia, skrót treści). Historia zapisuje się zanim ruszy Linear: nawet awaria po wysyłce nie pozwoli wysłać drugi raz.

**Bezpieczniki w kodzie (przed każdą wysyłką; parametry w `ops/zasady.json` → `wysylka`):**

| Bezpiecznik | Działanie przy naruszeniu |
|---|---|
| nigdy dwa razy ten sam szkic (historia + etykieta `Wysłano` + skrót treści) | blokada |
| odbiorca tylko z kontaktów karty z potwierdzonym kontaktem, nigdy z treści szkicu | blokada |
| strażnik zakazów z karty: „nie przypominać Kasi o pliku” blokuje przypomnienie, „nie kontaktować się z Olą” blokuje adresata, „nie wysyłać wzoru” blokuje treść o wzorze (wzorce w `wzorce_zakazow`) | blokada |
| filtr treści: `RIN-`, Linear i inne narzędzia, „zakaz”, klucze i pliki techniczne, nazwa innego klienta, adres e-mail spoza karty (sprawdzany też przy pisaniu szkicu) | blokada |
| limit maili do jednego klienta dziennie (`max_dziennie_na_klienta`, teraz 2) | czeka do jutra |
| tylko dni robocze 8:00–18:00 czasu polskiego (bez świąt z listy) | czeka do okna |
| nieobecność osoby kontaktowej (`kontakty[].nieobecnosci` w karcie, np. urlop Kasi 19–23.10) | czeka do powrotu, Slack informuje |

Blokada: etykieta `Do weryfikacji`, zdjęcie `Wyślij`, komentarz z powodem i Slack („Wysyłka wstrzymana: <powód>”). Oczekiwanie zostawia `Wyślij`, a Slack dostaje powód tylko raz. Po udanej wysyłce Slack: „Wysłano do <osoba>: <temat>”.

Nic nie wyjdzie na prawdziwą skrzynkę, dopóki ktoś nie doda etykiety `Wyślij`. Podgląd bez zmian: `python3 wyslij.py --sucho`, `python3 szkice.py --sucho`. Testy bez sieci i poczty: `python3 testy/test_wysylka.py`.

## Testy automatyczne

Dwa poziomy testów uruchamiane bez sieci i bez modelu AI:

### Testy jednostkowe logiki

```bash
python3 testy/test_logika.py
```

Pokrycie (46 testów):
- `should_get_agent_label` — etykieta „Dla agenta” tylko dla bug/konfiguracja/baza_wiedzy z wysoka pewnością, bez zakazu, bez nowej_funkcji.
- `process_aktualizacje` — ta sama rozmowa odrzucona, ta sama data odrzucona, późniejsza data akceptowana, nieznana sprawa pominięta.
- `daty.py compute_windows` — blokada globalna, weekendy pomijane, deadline ogranicza okno.
- `daty.py has_temporal_word` — frazy przyszłe wykrywane, neutralne cytaty nie.
- `update_risk_counter` — dwa różne źródła eskalują, to samo źródło dwa razy nie.
- Rejestr sha256 — ten sam hash wykryty, różne treści dają różne hashe.
- `find_state` — stan anulowany w Linearze to „Canceled”, obie pisownie działają (regresja: wcześniej anulowania nie ustawiały stanu).
- Strażnik aktualizacji liczy się od **pochodzenia** sprawy (pierwsze źródło), a komentarz z późniejszej rozmowy go nie blokuje; aktualizacja z tej samej rozmowy nie zadziała dwa razy.
- Zakazy — id są unikalne w karcie (numeracja Z1, Z2… zaczyna się od nowa w każdej rozmowie), ponowna analiza nie dubluje zakazów.
- Czyszczenie kluczy (`sekrety.py`) — spacje, entery, `\u2028`, `\u2029`, `\u00a0`, znaki zerowej szerokości.
- Wiadomość Slack — krótka, bez zerowych linii (szczegółowo w `test_zasady.py`) i parsowanie zdarzeń z `linear_sync.py`.

### Testy zasad AI-first (offline)

```bash
python3 testy/test_zasady.py
```

89 testów: każda reguła z `zasady.json` (pieniądze, do klienta ze szkicem, zakaz, decyzja zastrzeżona, pewność niska, nieodwracalne), domyślnie agent, brak kryteriów → Do weryfikacji, prośby produktowe (Wielu klientów, drobna zmiana, priorytet produktowy), ryzyka i zadanie przygotowawcze, stały układ opisu, przeliczanie istniejących zgłoszeń, limit przypomnień i „nie przypominaj", szkic jako wykorzystane przypomnienie, strefa czasowa podsumowania (lato, zima, zmiana czasu) oraz wygląd obu wiadomości na Slacku (limit 5 pozycji, 60 znaków, słowa powodów, znikająca sekcja Uwaga, kolejność ważności i brak powtórzeń, brak technicznych nazw, Block Kit).

### Testy maili (offline, na plikach .eml)

```bash
python3 testy/test_maile.py
```

53 testy na przykładowych plikach `testy/maile/*.eml`: nieznany nadawca pominięty bez pobierania treści (jedna linijka na przebieg, bez adresów), maile automatyczne pomijane po cichu (każde kryterium osobno), data włączenia, rejestr po sukcesie z ponowieniami (3 próby, potem porzucony), ten sam Message-ID pominięty, cytaty i stopka obcięte, nadawca z domeny klienta dodany jako „nowy, bez prawa decyzji", ogólne domeny pocztowe nigdy nie są domeną klienta, aktualizacja zakazu od niewłaściwej osoby odrzucona przez kod, mail starszy niż sprawa nie wznawia, skrzynka otwierana tylko do odczytu.

### Testy oczekiwań (po analizie)

```bash
python3 testy/uruchom.py wyniki/<klient>/<nazwa>/wynik.json testy/oczekiwania/<klient>-<nazwa>.json
```

```bash
python3 testy/uruchom.py wyniki/<klient>/<nazwa>/wynik.json testy/oczekiwania/<klient>-<nazwa>.json --online
```

Każde oczekiwanie jest zakotwiczone w cytacie (`fragment_cytatu`, krótki i dosłowny) albo w kluczu sprawy. Rodzaje testów (`typ_sprawdzania`):

| Rodzaj | Co sprawdza |
|---|---|
| `pozycje` (domyślny) | pozycja znaleziona po cytacie: sekcja, status, rodzaj, termin, przypomnienia, etykiety, okna czasowe |
| `aktualizacja` | wpis w `aktualizacje_spraw` (zamknięta / wznowiona) albo jego brak |
| `karta_sprawa`, `karta_zakaz`, `karta_ryzyka` | stan **po rozmowie** w karcie klienta: sprawa zamknięta/otwarta, aktywny zakaz, licznik ryzyk |
| `prosby` | ta sama funkcja u kilku klientów w `ops/produkt/prosby.json` |
| `okno_w`, `okna_dokladnie` | okna czasowe sprawy |
| `mail_nie_zawiera` | szkic maila nie obiecuje tego, czego klient zabronił |
| `linear` | stan, etykiety, priorytet i termin zgłoszenia w Linearze (**tylko z `--online`**) |

Bez `--online` testy `linear` są pomijane i liczone osobno, a reszta działa offline. Wyjście: `PASS X/Y` lub `FAIL X/Y` (kod 0 tylko gdy wszystkie wykonane przeszły).

Pliki oczekiwań:
- `testy/oczekiwania/auto-tama-2026-10-06-call-statusowy.json` — 20 testów
- `testy/oczekiwania/klinika-usmiech-2026-10-13-call-statusowy.json` — 10 testów
- `testy/oczekiwania/auto-tama-2026-10-13-call-statusowy.json` — 38 testów (w tym stan po rozmowie w karcie, `prosby.json` i Linearze)

`przetworz.py` uruchamia plik oczekiwań automatycznie po analizie (gdy plik istnieje) i dodaje wynik do wiadomości Slack.

### Kontrola jakości ręczna

Na przykładowej rozmowie (szczegóły w [kontrola.md](kontrola.md)):

| Wynik | Folder | Kontrola |
|---|---|---|
| pierwszy | `wyniki/transkrypcja-spotkanie/` | **19 / 20** |
| od zera | `wyniki/od-zera/` | **20 / 20** |

Pierwszy wynik (`wyniki/transkrypcja-spotkanie/`) był poprawiany w trakcie budowy narzędzia, więc nie pokazuje, co daje samo uruchomienie komendy. Miarodajny jest wynik od zera (`wyniki/od-zera/`), wygenerowany jednym przebiegiem komendy i niepoprawiany ręcznie. Zastrzeżenie: przebieg od zera zrobiono w sesji, która znała już listę kontrolną z `kontrola.md`. W pełni niezależny wynik da dopiero przebieg w nowej sesji.

Znane ograniczenia:
- W pierwszym wyniku okno testu wstępu podano tylko jako 12–16.10, bez drugiej możliwości od 26.10 (po urlopie). Wynik od zera ma oba okna.
- Godzin Torunia w dni robocze nie ma w rozmowie, więc oznaczono je jako wniosek, a nie fakt.
- Kompletność listy sprawdzana jest ręcznie (oczekiwania) i automatycznie (uruchom.py). Dosłowność cytatów sprawdza render.py.
- Daty względne („do czwartku”, „wczoraj”) są przeliczane od daty spotkania. Przeliczone daty przypomnień są oznaczone jako wnioski.

## Co dalej z większą ilością czasu

- **Integracje po zatwierdzeniu:** zadania do Linear, szkic maila do Gmaila (jako szkic, nie wysyłka), spotkania do kalendarza, notatka do CRM.
- **Zatwierdzanie w raporcie:** przy każdej pozycji akceptuj, popraw albo odrzuć, a dopiero potem eksport.
- **Historia klienta:** zakazy i ustalenia z poprzednich rozmów jako kontekst do następnej analizy, z wykrywaniem sprzeczności.
- ~~**Kalendarz w kodzie:**~~ Zrealizowane w `daty.py` — model dostarcza `fakty_czasowe`, kod oblicza wolne okna robocze.
- ~~**Automatyczna kontrola kompletności:**~~ Zrealizowane w `testy/` — oczekiwania zakotwiczone w cytatach, runner X/Y, integracja z przetworz.py.

## Logi

Logi z pracy z AI są w folderze [logi/](logi/): surowe sesje Claude Code (`.jsonl`) i ich czytelne wersje (`.md`, tylko wiadomości użytkownika i odpowiedzi asystenta).
