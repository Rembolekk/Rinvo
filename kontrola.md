# Kontrola jakości: wynik.json

Plik: `wyniki/transkrypcja-spotkanie/wynik.json`. Sprawdzono 2026-10-08, po poprawkach z kroku 2.
Pozycje sprawdzano ręcznie, porównując z treścią pliku. Brakujących rzeczy nie dopisywano do wynik.json.

**Wynik: 19 / 20**

| # | Pozycja | Znaleziono | Id w wynik.json |
|---|---|---|---|
| 1 | Sobota 9–15 zamiast 14, dla dzwonienia i dla godzin salonu w obu salonach | tak | T4, T5 |
| 2 | Adres we Włocławku: Toruńska 120; Kasi tylko napisać, że poprawione, bez nagrania | tak | T3 |
| 3 | Filtr „zainteresowany” to błąd, kliknięcie w kafelek to nowa funkcja | tak | T2, B2 |
| 4 | Kolumna z nazwiskiem tylko przy okazji naprawy filtra | tak | T6, Z16 |
| 5 | Opel wyłączony nawet na polecenie Pawła, najpierw telefon do Kasi | tak | Z3 |
| 6 | Nie wierzyć wiadomości „Kasia mówiła, że po godzinach od wtorku” | tak | Z10 |
| 7 | Jedno przypomnienie o wstępie, jedno o pliku z leadami | tak | Z6, K1, K2 |
| 8 | Nie wysyłać wzoru pliku, starej bazy nie puszczać drugi raz | tak | Z5, Z4 |
| 9 | Nie pisać do Oli | tak | Z13 |
| 10 | Limit 5 prób bez zmian | tak | Z7 |
| 11 | Urlop Kasi 19–23.10: nic nowego nie startuje, Opel i wstęp czekają na Kasię | tak | Z9, Z3 |
| 12 | Lead „oddzwońcie po urlopie” to zainteresowany, nie odmowa | tak | Z15 |
| 13 | Agent nie sprzedaje, bez aut używanych | tak | Z8 |
| 14 | Sprawy bez numeru (przegląd od Oli, drugie pytanie o model) czekają, bez zgadywania | tak | K3, K4, Z12 |
| 15 | Korektę faktury robi Michał | tak | T7 |
| 16 | Zaproszenie dla Pawła na 15.10, 10:00 dopiero po potwierdzeniu Kasi | tak | K5 |
| 17 | Case 208 tylko bez nazwy firmy | tak | Z14, K6 |
| 18 | Numery assistance przyjąć i nie podpinać | tak | Z10, B5 |
| 19 | VoiceDesk jako ryzyko handlowe | tak | R1 |
| 20 | Okno testu wstępu tylko 12–16.10 albo od 26.10 | nie | (konflikt dat przy K1 podaje tylko 12–16.10) |

## Znane ograniczenia

- **Punkt 20.** Konflikt dat przy teście wstępu (K1, Z1, Z9) wskazuje tylko okno 12–16.10. Brakuje drugiej możliwości: startu od 26.10, po urlopie. Analiza poprawnie wykluczyła tydzień 5–11.10 i urlop, ale nie podała okna po urlopie. Zgodnie z zasadą kontroli nie poprawiono tego ręcznie. Powinno to wyjść z kolejnego przebiegu `/analizuj`.
- **Punkt 1, godziny Torunia w dni robocze.** W transkrypcji jest tylko „Toruń bez zmian”, bez konkretnych godzin. Dlatego T4 podaje pn–pt 9:00–18:00 tylko dla Włocławka, a dla Torunia oznacza to jako wniosek. Wymaganie „pn–pt 9–18 w obu salonach” nie ma pokrycia w rozmowie.
- **Daty przeliczone.** Daty z wyrażeń względnych („do czwartku”, „w poniedziałek”, „wczoraj”) przeliczono od daty spotkania 6.10.2026. Daty przypomnień (9.10 i 13.10) oznaczono jako wnioski.
- **Kontrola ręczna.** Tę kontrolę zrobiono ręcznie. Automatycznie (`render.py --transkrypcja`) sprawdzana jest tylko dosłowność cytatów, a nie kompletność listy.
