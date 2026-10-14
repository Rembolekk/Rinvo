#!/usr/bin/env python3
"""zdarzenia.py – dziennik zdarzeń agenta dla osi czasu na stronach (PR-y, notatki, materiały).

Plik ops/.zdarzenia.json to lista {"data", "typ", "klient", "zgloszenie", "tytul", "url"}. Skrypty zapisują do niego przez
obiekt Dziennik (s.zdarzenia w środowisku produkcyjnym); w testach go nie ma, więc testy niczego nie zapisują.
Typy: pr_otwarty, pr_scalony, pr_oddany, material, notatka.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PLIK = Path("ops/.zdarzenia.json")
TYPY = ("pr_otwarty", "pr_scalony", "pr_oddany", "material", "notatka")


def wczytaj(plik=PLIK):
    p = Path(plik)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


class Dziennik:
    def __init__(self, plik=PLIK):
        self.plik = Path(plik)

    def dodaj(self, typ, klient, zgloszenie, tytul, url=None, data=None):
        """Dopisuje zdarzenie; to samo (typ, zgłoszenie, url) drugi raz nie powstaje. Zwraca True, gdy dopisano."""
        assert typ in TYPY, typ
        lista = wczytaj(self.plik)
        if any(z["typ"] == typ and z.get("zgloszenie") == zgloszenie and z.get("url") == url for z in lista):
            return False
        lista.append({"data": data or datetime.now(timezone.utc).isoformat(timespec="seconds"), "typ": typ,
                      "klient": klient, "zgloszenie": zgloszenie, "tytul": tytul, "url": url})
        self.plik.parent.mkdir(parents=True, exist_ok=True)
        self.plik.write_text(json.dumps(lista, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return True


def zapisz_zdarzenie(s, typ, klient, zgloszenie, tytul, url=None):
    """Wygodny skrót dla logiki agenta: nic nie robi, gdy środowisko nie ma dziennika (testy)."""
    dziennik = getattr(s, "zdarzenia", None)
    if dziennik is not None:
        dziennik.dodaj(typ, klient, zgloszenie, tytul, url)
