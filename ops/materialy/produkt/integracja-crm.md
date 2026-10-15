# Propozycja produktowa: Integracja Rinvo z CRM dealera

Wersja 1 · 2026-10-15 · status: do decyzji

## Problem

Grupa Auto Tama dziś przepisuje leady ręcznie z maili do swojego systemu, a to ich najbardziej irytuje. Konkurent oferuje bota do leadów, który łączy się z systemem dealera, więc leady trafiają prosto do handlowców. U nas takiej integracji nie ma, a właściciel zapowiada test z konkurentem, jeśli nie zobaczy czegoś konkretnego w tej sprawie. Brak połączenia wzmacnia też wrażenie, że rozwiązanie jest mniej wygodne, bo handlowiec widzi tylko część leadów i część z nich uznaje za nieaktualne.

## Kto prosi

- Klienci (1): Grupa Auto Tama
- Liczba próśb: 1 w 1 źródle (rozmowy i maile); pierwsza 2026-10-06, ostatnia 2026-10-06
- Dosłowne cytaty:
  - „Integracji z waszym systemem teraz nie mamy i nie chcę obiecywać, że będzie w tym kwartale.” (Grupa Auto Tama, 2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md)

## Wpływ

- Sygnał: może uratować klienta Grupa Auto Tama: ma aktywne ryzyko utraty, a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: konkurencja), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „Dwa tygodnie temu była u Pawła firma VoiceDesk. Też mają bota do leadów. Powiedzieli, że są tańsi i że łączą się z systemem, więc leady same wpadają handlowcom.” (2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: konkurencja), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „Bardziej go kręci to łączenie z systemem, bo dziewczyny teraz przepisują wszystko z maili.” (2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: grozba_rezygnacji), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „Paweł zobaczył tylko te dziewięć na siedemdziesiąt i chciał wszystko wyłączyć. Powiedziałam mu, że to trupy, a nie świeże leady.” (2026-10-06, źródło: ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md).
- Ryzyko utraty klienta: Grupa Auto Tama ma aktywne ryzyko (temat: grozba_rezygnacji), a prośba dotyczy tego, co oferuje konkurencja (integracja z systemem klienta). Zapisano: „jak w czwartek nie zobaczy czegoś konkretnego o połączeniu z systemem, to w listopadzie robią test z nimi.” (2026-10-13, źródło: ops/transkrypcje/auto-tama/2026-10-13-call-statusowy.md).
- Kwot, wartości kontraktów ani przychodów w źródłach nie ma, więc ich tu nie podajemy.

## Najmniejsza wersja rozwiązania

- Jednokierunkowe przekazywanie nowych leadów z Rinvo do systemu klienta, bez przepisywania z maili.
- Każdy lead trafia do systemu jako jeden rekord z danymi kontaktowymi, źródłem i wynikiem rozmowy.
- Przypisanie leada do konkretnego handlowca według prostej reguły ustawionej przez klienta.
- Oznaczenie w rekordzie, czy lead jest świeży, czy to starszy kontakt, żeby handlowiec od razu widział różnicę.
- Widoczny status przekazania i czytelna informacja, gdy rekord nie dotarł, żeby nic nie ginęło po cichu.
- Pierwsze uruchomienie z jednym klientem i jednym systemem, czyli Grupą Auto Tama.

## Pytania otwarte do klientów

- Jakiego systemu CRM używa dealer i jakie ma możliwości przyjmowania leadów z zewnątrz?
- Które dane z maila handlowcy dziś przepisują ręcznie i które są dla nich niezbędne w rekordzie?
- Według jakiej reguły lead ma trafiać do konkretnego handlowca?
- Jak ma wyglądać odróżnienie świeżych leadów od starych kontaktów w widoku handlowca?
- Co dokładnie klient chce zobaczyć na pokazie, żeby uznać, że połączenie z systemem jest realne?

## Ryzyka

- Klient używa konkretnego systemu, więc pierwsza integracja może nie pasować do innych dealerów i trzeba uważać, żeby nie budować rozwiązania pod jednego klienta.
- Czas jest krótki: klient oczekuje czegoś konkretnego do pokazania, a pełna integracja może okazać się większa niż wersja minimalna.
- Błędne lub zduplikowane rekordy w systemie klienta mogłyby zepsuć zaufanie bardziej niż obecne ręczne przepisywanie.
- Konkurent przekonuje też ceną, więc sama integracja może nie wystarczyć, jeśli klient porówna oferty całościowo.

## Proponowany następny krok

Ustalić z klientem, jakiego systemu używa i co dokładnie musi zobaczyć na pokazie, a następnie przygotować pokaz minimalnego przekazywania leadów do tego systemu.
