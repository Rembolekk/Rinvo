#!/usr/bin/env python3
"""sekrety.py – czyszczenie kluczy API z białych i niewidocznych znaków.

Klucz wklejony z Notatek (Mac) potrafi mieć na końcu enter, spację, \\u2028, \\u2029,
\\u00a0 albo znak zerowej szerokości. Taki klucz wygląda poprawnie, a serwer go odrzuca.
Prawdziwy klucz nie zawiera żadnych takich znaków, więc usuwamy je ze środka i z brzegów.

Użycie jako moduł:   from sekrety import czysc, wyczysc_srodowisko
Użycie z shella:     TOKEN="$(python3 sekrety.py CLAUDE_CODE_OAUTH_TOKEN)"
(drukuje oczyszczoną wartość zmiennej środowiskowej; nic nie drukuje, gdy zmiennej brak)
"""

import os
import sys
import unicodedata

NAZWY_SEKRETOW = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                  "LINEAR_API_KEY", "SLACK_WEBHOOK_URL")

# kategorie Unicode do usunięcia: separatory (Zs, Zl, Zp), znaki sterujące (Cc),
# formatujące (Cf: zero-width, BOM, kierunek pisma)
_USUWANE_KATEGORIE = {"Zs", "Zl", "Zp", "Cc", "Cf"}


def czysc(wartosc):
    """Zwraca wartość bez białych i niewidocznych znaków."""
    if wartosc is None:
        return ""
    return "".join(
        ch for ch in str(wartosc)
        if not ch.isspace() and unicodedata.category(ch) not in _USUWANE_KATEGORIE
    )


def wyczysc_srodowisko(nazwy=NAZWY_SEKRETOW, ostrzegaj=True):
    """Czyści sekrety w os.environ (dziedziczą je procesy potomne).
    Zwraca listę nazw, które zmieniono. Nigdy nie drukuje wartości."""
    zmienione = []
    for nazwa in nazwy:
        stara = os.environ.get(nazwa)
        if stara is None:
            continue
        nowa = czysc(stara)
        if nowa != stara:
            os.environ[nazwa] = nowa
            zmienione.append(nazwa)
            if ostrzegaj:
                print(f"Uwaga: {nazwa} zawierał białe/niewidoczne znaki "
                      f"({len(stara) - len(nowa)} usunięto) — wyczyszczono.", file=sys.stderr)
    return zmienione


if __name__ == "__main__":
    for nazwa in sys.argv[1:]:
        print(czysc(os.environ.get(nazwa, "")))
