# Próba generalna od czystego stanu: instrukcja krok po kroku

Stan wyjściowy (po `python3 reset_demo.py --tak`): Linear bez zgłoszeń (zarchiwizowane; etykiety i widok „Dla mnie dziś” zostały), Rinvo bez wyników,
materiałów, rejestrów i stron z danymi, karta auto-tama tylko z konfiguracją (nazwa, domena, Kasia jako potwierdzony kontakt i jej zakres decyzji),
Rinvo-app z konfiguracją sprzed poprawek agenta (Toruń sobota do 14:00, dzwonienie do 20:00). Wrócić do stanu sprzed resetu: tag `przed-proba` w obu repo.
Transkrypcje czekają w `proba/transkrypcje/auto-tama/`, kliniki w `proba/archiwum/klinika-usmiech/` (w tej próbie nieużywana).

## 0. Raz, przed startem

1. GitHub → Rinvo → Settings → Secrets and variables → Actions:
   - **Variables:** `AGENT_WLACZONY` = `true` (bez tego agent rusza tylko ręcznie), `MAILE_WLACZONE` = `true` (bez tego cron nie sprawdza skrzynki; ręczne uruchomienie działa zawsze), opcjonalnie `RINVO_MODEL`.
   - **Secrets** (powinny już być): `CLAUDE_CODE_OAUTH_TOKEN`, `LINEAR_API_KEY`, `SLACK_WEBHOOK_URL`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `AGENT_GITHUB_TOKEN`.
2. Wysyłka maili do Kasi działa **tylko w dni robocze 8:00–18:00 czasu polskiego**. Poza oknem mail czeka (Slack: „poza oknem wysyłki”) i wyjdzie w najbliższym oknie.
3. Skrzynka systemu czyta maile od dnia włączenia (dziś). Przed startem nie wysyłaj do niej nic innego, bo zostanie przetworzone.
4. Sprawdź stan wyjściowy: Linear → widok „Dla mnie dziś” jest pusty; https://rembolekk.github.io/Rinvo/ pokazuje jednego klienta (Grupa Auto Tama) bez spraw i bez sygnałów.
5. Zakładka Actions powinna być czysta; po pushu resetu przebieg „Przetwarzanie rozmów” z 0 transkrypcji to norma.

W każdym kroku najpierw: `cd ~/Desktop/Rinvo && git pull --rebase origin main` (boty commitują na main).

## 1. Rozmowa auto-tama z 6.10

```bash
git pull --rebase origin main
mkdir -p ops/transkrypcje/auto-tama
git mv proba/transkrypcje/auto-tama/2026-10-06-call-statusowy.md ops/transkrypcje/auto-tama/
git commit -m "Próba: rozmowa auto-tama 6.10" && git push
```

**Czekaj** ok. 10–20 min na „Przetwarzanie rozmów”, potem do ok. 60–90 min na agenta (workflow „Agent wykonawczy” rusza sam po udanym przetworzeniu; zgłoszenia ruszają po kolei, bo część dotyczy tych samych plików konfiguracji, a scalenie PR wymaga zielonych testów i recenzji CodeRabbit; cron co 15 min).
**Nie przechodź do kroku 2, dopóki w Rinvo-app nie zostaną scalone poprawki z tego kroku** (potrzebne do zobaczenia „regresji” w kroku 2).

Co sprawdzić i czego się spodziewać:
- **Slack:** podsumowanie przetworzenia rozmowy; później „Nowy sygnał w głosie klientów” (integracja z CRM: klient ma ryzyko utraty i prosi o to, co oferuje konkurencja); potem jedna linijka na każdy scalony PR agenta.
- **Linear** (zespół RIN), ok. 28 zgłoszeń: 11 do zrobienia teraz, 5 czeka na klienta, 9 z backlogu (prośby produktowe), 3 ryzyka; 14 zakazów trafia tylko do karty (nie do Lineara). Zgłoszenia dla człowieka mają tytuły od czynności (`Zdecyduj: …`, `Wyślij: …`) i blok „Co masz zrobić” na górze opisu. Widok „Dla mnie dziś” je pokazuje. Zgłoszenia dla agenta w repo `rinvo-app`: adres Włocławek (wiedza), godziny dzwonienia 9–19 / sobota 9–15 oraz godziny salonu w sobotę 15:00 (config).
- **PR w Rinvo-app:** agent otwiera PR-y (tytuł `[auto-tama] …`, `Fixes RIN-…`), CodeRabbit recenzuje, testy muszą być zielone, drobne zmiany scala sam (squash). Zmiana większa niż 40 linii albo 3 plików zostaje do Twojej decyzji („Decyzja człowieka: duża zmiana”). Po scaleniu zgłoszenie przechodzi na Done.
- **Strony:** https://rembolekk.github.io/Rinvo/ (po 1–2 min od commita bota): Grupa Auto Tama z zakazami, ryzykami, osią czasu, a w „Głos klientów” sygnał o CRM.
- **Odbiór offline:** `git pull && python3 testy/uruchom.py wyniki/auto-tama/2026-10-06-call-statusowy/wynik.json testy/oczekiwania/auto-tama-2026-10-06-call-statusowy.json` (oczekiwane PASS 20/20; z `--online` dodatkowo sprawdza Linear).
- Propozycje produktowe (`Zdecyduj: propozycja – …`) powstają w codziennym podsumowaniu; żeby zobaczyć je od razu: Actions → „Codzienne podsumowanie” → Run workflow (powstanie też poranne podsumowanie na Slacku).

## 2. Rozmowa auto-tama z 13.10

```bash
git pull --rebase origin main
git mv proba/transkrypcje/auto-tama/2026-10-13-call-statusowy.md ops/transkrypcje/auto-tama/
git commit -m "Próba: rozmowa auto-tama 13.10" && git push
```

Czekaj 10–20 min (przetworzenie) i znów do ok. 60 min (agent).

Co sprawdzić:
- **Regresja:** w rozmowie Toruń znowu podaje sobotę do 14:00. Zgłoszenie „Toruń … sobotę do 15:00” (naprawione w kroku 1) wraca do **Todo** z etykietą **Regresja** i komentarzem „Wróciło” z cytatem i źródłem, **bez nowego zgłoszenia**. Na stronie klienta znacznik „regresja”. (Jeśli poprawka z kroku 1 nie była jeszcze Done, zgłoszenie dostanie zwykły komentarz.)
- **Aktualizacje spraw:** adres Włocławek, filtr statusu i korekta faktury zamykają się (Done), a test wstępu i zaproszenie dla Pawła wracają do Todo.
- **Ryzyka:** VoiceDesk po raz drugi z innego źródła: etykieta „Powtarzające się ryzyko”, priorytet Urgent, wiersz w „Uwadze” porannego podsumowania, na stronie klienta światło czerwone.
- **Nowe zgłoszenia:** ok. 7 do zrobienia teraz, w tym `Wyślij: …` (zaproszenie na spotkanie z Pawłem w czwartek 10:00, ściąga statusów, zestawienie na piątek); 4 nowe zakazy w karcie (m.in. „Nie przypominać Kasi o pliku ze świeżymi leadami”, Opel na starej bazie).
- **Szkice maili:** po zamknięciu/utworzeniu zgłoszeń przy następnym przebiegu agenta powstają szkice (etykieta „Szkic gotowy”, blok „Gotowy mail” na górze opisu, komentarz ze szkicem). **Wysyłka:** dodaj etykietę **Wyślij** na zgłoszeniu ze szkicem (mail pójdzie do Kasi na adres z karty, tylko 8–18, z zaproszeniem .ics albo załącznikiem PDF tam, gdzie szkic go przewiduje). Możesz poprawić treść w bloku opisu i dopiero wtedy dać „Wyślij”; „Odrzuć” anuluje zgłoszenie. Po wysyłce: komentarz „Wysłano …” i etykieta „Wysłano”.
- **Odbiór offline:** `python3 testy/uruchom.py wyniki/auto-tama/2026-10-13-call-statusowy/wynik.json testy/oczekiwania/auto-tama-2026-10-13-call-statusowy.json` (oczekiwane PASS; kroki „--online” pomijane bez flagi).
- Blokada: Kasia ma urlop 19–23.10; od niej „Nic nowego nie startuje” blokuje tylko nowe rzeczy, poprawki błędów przechodzą.

## 3. Mail od Kasi z plikiem leadów

Z adresu Kasi z karty (konto `mateuszrembecki1@gmail.com`) wyślij na skrzynkę systemu (`GMAIL_ADDRESS`, wcześniej: contact.invaltic@gmail.com) maila z załącznikiem CSV, np.:

> Temat: Plik ze świeżymi leadami  
> Cześć Marek, tak jak obiecywałam, w załączniku plik ze świeżymi leadami z ostatniego miesiąca, strona i Facebook. Możecie puszczać. Kasia

Następnie albo poczekaj do 15 min (cron „Sprawdzanie maili”, wymaga `MAILE_WLACZONE=true`), albo Actions → „Sprawdzanie maili” → Run workflow (pole ścieżki puste).

Co sprawdzić:
- W repo pojawia się `ops/maile/auto-tama/<data>-plik-ze-swiezymi-leadami.md` (bez adresów w stronach publicznych) i `wyniki/auto-tama/<data>-…/` po przetworzeniu (Slack z podsumowaniem).
- Linear: sprawa „Plik świeżych leadów” (czekała na klienta) przechodzi do „do zrobienia”; zgłoszenie „Przyjąć plik…” dla agenta (repo rinvo-ops, bez startu kampanii) oraz pytanie „Potwierdzenie od Kasi, czy «możecie puszczać» znosi blokadę nowych startów” (Do weryfikacji).
- Mail jest przetworzony **raz** (rejestr `ops/.maile.json`); stare maile sprzed dziś nie wracają.
- Pozostałe maile w skrzynce od innych nadawców trafiają do „nieznanych” i nie tworzą zgłoszeń.

## 4. Rozmowa NOWEGO klienta (Twój plik)

```bash
git pull --rebase origin main
mkdir -p ops/transkrypcje/<nowy-klient>
cp /ścieżka/do/pliku.md ops/transkrypcje/<nowy-klient>/<data>-call-<temat>.md
git add ops/transkrypcje && git commit -m "Próba: rozmowa nowego klienta" && git push
```

Nazwa pliku z datą (RRRR-MM-DD), folder = slug klienta. Czekaj 10–20 min. Co sprawdzić (system nie zna tej rozmowy, więc to test na zimno):
- powstaje karta `ops/klienci/<nowy-klient>/` (zakazy, sprawy, ryzyka) i strona `klienci/<nowy-klient>.html` na Pages;
- w Linearze zgłoszenia z prefiksem `[<nowy-klient>]`; zgłoszenia, w których nie wiadomo, co robić albo brakuje kontaktu, trafiają do „Do weryfikacji” z tytułem `Uzupełnij: …` lub `Sprawdź: …` (karta nowego klienta nie ma potwierdzonego kontaktu, więc **żaden mail nie powstanie ani nie wyjdzie**, dopóki nie dopiszesz kontaktu w karcie);
- Slack: podsumowanie przetworzenia; ewentualne nowe sygnały w Głosie klientów;
- uwagi, które warto spisać: czy cytaty są dosłowne, czy pozycje są oznaczone „niska pewność”, czy nic nie przecieka do innych klientów.

## Gdy coś pójdzie nie tak

- Zawsze zacznij od Actions → ostatni przebieg → log (sekrety są maskowane). Logi przebiegów są też w `logi/przebiegi/`.
- Limit modelu albo dzienny bezpiecznik: zadanie czeka w kolejce, Slack da jedną informację, ponowienie następuje przy kolejnym przebiegu.
- Powtórka od zera: `python3 reset_demo.py --tak` (po przeniesieniu transkrypcji z powrotem do `proba/` albo `git checkout przed-proba -- proba`), albo powrót do stanu sprzed próby: `git checkout przed-proba` w obu repo.
- Testy offline: `for t in logika maile zasady daty notatki agent wysylka notatka_spotkania strony utwardzanie utwardzanie2 porzadek_produkt reset_demo; do python3 testy/test_$t.py 2>&1 | tail -3; done`
