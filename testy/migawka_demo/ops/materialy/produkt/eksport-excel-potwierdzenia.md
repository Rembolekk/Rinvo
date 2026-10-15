# Propozycja produktowa: Eksport listy potwierdzeń do Excela

Wersja 1 · 2026-10-15 · status: do decyzji

## Problem

Osoby obsługujące kontakty po stronie dwóch klientów muszą ręcznie przepisywać dane z panelu, żeby dostać listę zainteresowanych albo listę potwierdzeń. Auto Tama potrzebuje takiej listy, żeby podzielić zainteresowanych między handlowców. Klinika Uśmiech chce widzieć, kto potwierdził, a kto nie. Ręczne przepisywanie zabiera czas i naraża na pomyłki.

## Kto prosi

- Klienci (2): Grupa Auto Tama, Klinika Uśmiech
- Liczba próśb: 2 w 2 źródłach (rozmowy i maile); pierwsza 2026-10-13, ostatnia 2026-10-13
- Dosłowne cytaty:
  - „Dziewczyny chcą eksportu listy kontaktów do Excela. Żeby wyciągnąć tych zainteresowanych i rozdzielić między handlowców. Teraz przepisują ręcznie.” (Grupa Auto Tama, 2026-10-13, źródło: ops/transkrypcje/auto-tama/2026-10-13-call-statusowy.md)
  - „Chciałabym mieć w panelu przycisk eksportu do Excela, z listą kto potwierdził, a kto nie. Teraz przepisuję ręcznie.” (Klinika Uśmiech, 2026-10-13, źródło: ops/transkrypcje/klinika-usmiech/2026-10-13-call-statusowy.md)

## Wpływ

- Sygnał: prosi 2 klientów: Grupa Auto Tama, Klinika Uśmiech.
- W kartach klientów nie ma zapisanego ryzyka utraty związanego z tą prośbą.
- Kwot, wartości kontraktów ani przychodów w źródłach nie ma, więc ich tu nie podajemy.

## Najmniejsza wersja rozwiązania

- Przycisk eksportu w panelu, który pobiera listę kontaktów jako plik w formacie Excela.
- Każdy wiersz zawiera dane kontaktu oraz status potwierdzenia: potwierdził lub nie potwierdził.
- Eksport obejmuje listę widoczną w panelu, z możliwością wyboru zakresu, np. według kampanii lub dat.
- Możliwość odfiltrowania przed eksportem samych zainteresowanych lub samych potwierdzonych, żeby dało się je od razu rozdzielić między handlowców.
- Eksport bez dodatkowych ustawień, bez automatycznego podziału kontaktów między osoby.

## Pytania otwarte do klientów

- Jakie kolumny są niezbędne w pliku, a jakich nie potrzebujecie?
- Jak definiujecie osobę zainteresowaną i jak potwierdzoną, czy to ten sam status, czy dwa różne?
- Jak często eksportujecie listę i jak duże są zwykle te listy?
- Co dzieje się z plikiem po eksporcie, czy trafia do kolejnego systemu, czy jest rozsyłany ręcznie?
- Czy dzielenie kontaktów między handlowców ma pozostać po Waszej stronie, czy oczekujecie tego w produkcie?

## Ryzyka

- Po pobraniu pliku dane osobowe kontaktów opuszczają panel, więc trzeba ustalić, kto ma prawo eksportować.
- Dwóch klientów może rozumieć status potwierdzenia i zainteresowania inaczej, co da niespójne wyniki w pliku.
- Prośby pochodzą z dwóch różnych zastosowań, więc zbyt wąska wersja może nie pasować żadnemu z nich.
- Eksport rozwiązuje przepisywanie, ale nie obejmuje dalszego podziału kontaktów, więc część ręcznej pracy może zostać.

## Proponowany następny krok

Porozmawiać z obiema osobami o tym, jak dziś wygląda ich lista i jakie kolumny są im potrzebne, a następnie dopracować zakres najmniejszej wersji.
