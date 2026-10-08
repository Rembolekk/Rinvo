---
description: Analiza transkrypcji rozmowy z klientem → wynik.json + raport.html
argument-hint: <plik transkrypcji, np. transkrypcja-spotkanie.md>
---

Przeanalizuj transkrypcję rozmowy z klientem z pliku: $ARGUMENTS

Wszystkie ścieżki poniżej są względne wobec folderu projektu (tego, w którym leży `.claude/`).
Pracuj w trzech krokach i zapisz wyniki do plików.

KROK 1. EKSTRAKCJA
Wypisz każdą pozycję wynikającą z rozmowy. Dla każdej podaj:
typ (bug, zmiana_konfiguracji, poprawka_bazy_wiedzy, pomysl_produktowy, zobowiazanie_nasze, czeka_na_klienta, zakaz, finanse, ryzyko_handlowe, spotkanie),
wlasciciel (konkretna osoba), termin (data lub "brak"), warunek (co musi się stać, zanim to ruszymy, lub "brak"),
status (zrob_teraz, czeka, backlog, nigdy),
cytat (dosłowny fragment rozmowy uzasadniający pozycję).

KROK 2. WERYFIKACJA
Sprawdź listę z kroku 1:
- usuń każdą pozycję bez dosłownego cytatu,
- jeśli ktoś zmienił zdanie w trakcie rozmowy, zostaw tylko ostatnią wersję i odnotuj zmianę. Do zmian zdania zaliczaj tylko odwołanie lub zmianę wcześniejszej decyzji. Doprecyzowanie, odrzucona propozycja albo oferta, której druga strona nie przyjęła, to nie zmiana zdania,
- odróżnij błąd (coś miało działać i nie działa) od nowej funkcji (czegoś nigdy nie było),
- zakazy i ograniczenia ("nie rób", "nie wcześniej niż", "tylko raz", "nie wierzcie") zapisz jako osobne pozycje,
- jeśli brakuje danych do działania (numer, nagranie, plik), status = czeka, nie zgaduj,
- zestaw ze sobą wszystkie daty (urlopy, terminy, okna testów) i zapisz konflikty. Konflikt to sytuacja, w której ustalone terminy lub zakazy się wykluczają albo zawężają okno. Zwykłe zależności („B po A”) nie są konfliktami,
- każde stwierdzenie, które nie wynika wprost z cytatu (np. przeliczona data przypomnienia, domysł o intencji), przenieś do pola "wnioski",
- połącz duplikaty.

KROK 3. WYNIK
Folder wyników: wyniki/<nazwa pliku transkrypcji bez rozszerzenia>/ (utwórz, jeśli nie istnieje).

a) Zapisz wynik.json z finalną listą, w tym schemacie:
{
  "zrodlo": "<ścieżka transkrypcji względem folderu projektu>",
  "wygenerowano": "RRRR-MM-DD",
  "spotkanie": { "tytul", "data", "godziny", "uczestnicy": [..], "wspominani": [..] },
  "pozycje": [{
    "id": "T1",                 // T = sekcja 1, K = 2, B = 3, Z = 4, R = 5; numeracja po kolei
    "sekcja": 1,                // 1 do zrobienia teraz, 2 czeka na klienta, 3 backlog, 4 zakazy, 5 ryzyka
    "typ", "rodzaj" (opcjonalnie: błąd / nowa_funkcja / zmiana),
    "tytul", "opis", "wlasciciel", "termin", "warunek",
    "status": "zrob_teraz | czeka | backlog | nigdy",
    "cytat": ["dosłowny fragment", ...],
    "wnioski": ["stwierdzenie, które nie wynika wprost z cytatu", ...] (opcjonalnie),
    "zmiana_zdania": "..." (opcjonalnie),
    "przypomnienie": { "data", "limit", "uwagi" } (sekcja 2)
  }],
  "zmiany_zdania": [{ "temat", "przed", "po", "pozycja", "cytat" }],
  "konflikty_dat": [{ "opis", "pozycje": ["id", ...], "wnioski": [..] (opcjonalnie) }],
  "weryfikacja": { "usuniete_bez_cytatu": [..], "zastapione_lub_scalone": [..], "pominiete": [..] },
  "szkic_maila": "pełny tekst maila do klienta (tylko to, co faktycznie ustalono)"
}

b) Raport generuj WYŁĄCZNIE skryptem render.py z folderu projektu. Nie pisz nowego
renderera i nie twórz raport.html ręcznie. Uruchom z folderu projektu:
   python -I render.py wyniki/<nazwa>/wynik.json --transkrypcja <plik transkrypcji>
Skrypt sprawdza schemat i dosłowność każdego cytatu, a potem zapisuje raport.html obok wynik.json.
Raport ma sekcje 1–6, liczniki na górze, zmiany zdania, konflikty dat i oznaczone wnioski.
Jeśli skrypt zgłosi błąd (kod 1: schemat, kod 2: cytat niedosłowny), popraw wynik.json
(cytat skopiuj dokładnie albo usuń pozycję) i uruchom go ponownie. Samego render.py nie zmieniaj.

Nie wpisuj na sztywno nazw firm ani osób. Wszystko bierz z transkrypcji.
Niczego nie wysyłaj do klienta. Szkic maila zatwierdza człowiek.
