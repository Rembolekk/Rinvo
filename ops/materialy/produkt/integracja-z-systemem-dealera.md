# Propozycja produktowa: Integracja z systemem (CRM) dealera, żeby leady same trafiały do handlowców

Wersja 1 · 2026-10-15 · status: do decyzji

## Problem

W Grupie Auto Tama pracownice ręcznie przenoszą informacje o leadach z wiadomości e-mail do systemu dealera, co jest żmudne i angażuje ludzi w pracę, którą powinna wykonywać automatyzacja. Decydent w firmie jest szczególnie zainteresowany połączeniem z własnym systemem. Konkurent, który już oferuje taki mechanizm, zwrócił na siebie jego uwagę, a klient ma jednocześnie aktywne ryzyko rezygnacji. Brak integracji osłabia naszą pozycję właśnie w obszarze, który klient uznaje za najważniejszy.

## Kto prosi

- Klienci (1): Grupa Auto Tama
- Liczba próśb: 1 w 1 źródle (rozmowy i maile); pierwsza 2026-10-06, ostatnia 2026-10-06
- Dosłowne cytaty:
  - „Bardziej go kręci to łączenie z systemem, bo dziewczyny teraz przepisują wszystko z maili.” (Grupa Auto Tama, 2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md)

## Wpływ

- Sygnał: może uratować klienta Grupa Auto Tama: ma aktywne ryzyko utraty, a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: grozba_rezygnacji), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „Paweł zobaczył tylko te dziewięć na siedemdziesiąt i chciał wszystko wyłączyć. Powiedziałam mu, że to trupy, a nie świeże leady.” (2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: konkurencja), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „Dwa tygodnie temu była u Pawła firma VoiceDesk. Też mają bota do leadów. Powiedzieli, że są tańsi i że łączą się z systemem, więc leady same wpadają handlowcom. Paweł się tym zainteresował.” (2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md).
- Kwot, wartości kontraktów ani przychodów w źródłach nie ma, więc ich tu nie podajemy.

## Najmniejsza wersja rozwiązania

- Każdy lead z rozmowy trafia automatycznie do systemu dealera jako nowy rekord, bez przepisywania z e-maili.
- Rekord zawiera podstawowe dane kontaktowe, wynik rozmowy i krótkie podsumowanie.
- Lead jest przypisywany do właściwego handlowca według prostej reguły ustalonej z klientem.
- Dla każdego leada widać, czy został przekazany do systemu, a w razie błędu handlowiec lub opiekun dostaje informację.
- E-mail z leadem pozostaje jako zapasowy kanał na czas, gdy przekazanie do systemu się nie powiedzie.

## Pytania otwarte do klientów

- Jakiego systemu dealerskiego używa dziś Grupa Auto Tama i czy ma on otwarty sposób przyjmowania danych z zewnątrz?
- Jakie dokładnie dane z e-maili pracownice obecnie przepisują i które pola są dla nich najważniejsze?
- Według jakiej zasady lead ma trafiać do konkretnego handlowca?
- Czy inni klienci korzystają z tego samego systemu, czy każdy ma inny?
- Czy rozmowa o świeżości leadów i ich liczbie wymaga osobnego raportowania, żeby decydent nie oceniał wyników po samych liczbach?

## Ryzyka

- Różne systemy dealerskie u różnych klientów mogą sprawić, że integracja zrobiona pod jednego klienta nie będzie nadawała się dla pozostałych.
- Jeśli przekazanie leada do systemu zawiedzie po cichu, handlowcy mogą stracić kontakt z klientem, a zaufanie do rozwiązania spadnie.
- Samo połączenie z systemem nie rozwiąże wątpliwości decydenta co do jakości leadów, które wynikały z mało świeżych kontaktów, więc ryzyko utraty klienta może pozostać.
- Konkurent już komunikuje integrację jako swoją przewagę, więc częściowa lub niestabilna wersja może zostać odebrana jako gorsza od oferty rywala.

## Proponowany następny krok

Ustalić z Grupą Auto Tama, z jakiego systemu korzystają i jakie dane mają trafiać do handlowców, a następnie sprawdzić możliwości technicznego połączenia.
