#!/usr/bin/env python3
"""uzupelnij.py – scala pola dla zgłoszeń agentów (pola-agenta.json) z wynik.json.

Użycie:
  python3 uzupelnij.py wyniki/<klient>/<nazwa>/wynik.json [pola-agenta.json]
  python3 uzupelnij.py wyniki/<klient>/<nazwa>/wynik.json --wyrazenia [wyrazenia.json]

Model zapisuje tylko małe pola-agenta.json (id pozycji → pola), a kod dopisuje je do pozycji:
  * tylko dozwolone pola (cel, kryteria_akceptacji, jak_sprawdzic, repo, szkic_klienta,
    zadanie_przygotowawcze), z walidacją typów,
  * nigdy nie nadpisuje istniejących pól pozycji i nie dotyka niczego innego.
"""

import json
import sys
from pathlib import Path

DOZWOLONE = ("cel", "kryteria_akceptacji", "jak_sprawdzic", "repo", "szkic_klienta", "zadanie_przygotowawcze")
REPO = {"rinvo", "rinvo-ops", "brak"}


def _lista_tekstow(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def waliduj_pola(pola):
    """Zwraca oczyszczone pola albo podnosi ValueError z powodem."""
    czyste = {}
    for k, v in pola.items():
        if k not in DOZWOLONE:
            continue
        if k == "kryteria_akceptacji":
            if not _lista_tekstow(v):
                raise ValueError("kryteria_akceptacji: oczekiwano listy tekstów")
            v = [x.strip() for x in v if x.strip()]
        elif k == "repo":
            if v not in REPO:
                raise ValueError(f"repo: {v!r} spoza {sorted(REPO)}")
        elif k == "zadanie_przygotowawcze":
            if not isinstance(v, dict):
                raise ValueError("zadanie_przygotowawcze: oczekiwano obiektu")
            v = waliduj_pola({kk: vv for kk, vv in v.items() if kk != "zadanie_przygotowawcze"})
        elif not isinstance(v, str):
            raise ValueError(f"{k}: oczekiwano tekstu")
        czyste[k] = v
    return czyste


def scal(wynik, pola_wg_id):
    """Dopisuje pola do pozycji (po id). Zwraca (liczba_pozycji_uzupelnionych, ostrzezenia)."""
    ostrzezenia, n = [], 0
    po_id = {p.get("id"): p for p in wynik.get("pozycje", [])}
    for pid, pola in pola_wg_id.items():
        p = po_id.get(pid)
        if p is None:
            ostrzezenia.append(f"{pid}: brak takiej pozycji w wynik.json")
            continue
        try:
            czyste = waliduj_pola(pola)
        except ValueError as exc:
            ostrzezenia.append(f"{pid}: {exc}")
            continue
        dodano = False
        for k, v in czyste.items():
            if k not in p:           # nigdy nie nadpisujemy istniejących pól
                p[k] = v
                dodano = True
        n += dodano
    return n, ostrzezenia


def scal_wyrazenia(wynik, wyrazenia):
    """Dopisuje dosłowne wyrażenia dat: fakty_czasowe[i]["wyrazenie"] i pozycje[id]["termin_wyrazenie"].
    Nie nadpisuje istniejących wyrażeń. Zwraca (liczba_dopisanych, ostrzeżenia)."""
    ostrzezenia, n = [], 0
    fakty = wynik.get("fakty_czasowe", [])
    for indeks, wyr in (wyrazenia.get("fakty") or {}).items():
        try:
            f = fakty[int(indeks)]
        except (ValueError, IndexError):
            ostrzezenia.append(f"fakt {indeks}: brak takiego wpisu w fakty_czasowe")
            continue
        if not isinstance(wyr, str) or not wyr.strip():
            ostrzezenia.append(f"fakt {indeks}: wyrażenie musi być tekstem")
        elif "wyrazenie" not in f:
            f["wyrazenie"] = wyr.strip()
            n += 1
    po_id = {p.get("id"): p for p in wynik.get("pozycje", [])}
    for pid, wyr in (wyrazenia.get("terminy") or {}).items():
        p = po_id.get(pid)
        if p is None:
            ostrzezenia.append(f"{pid}: brak takiej pozycji")
        elif not isinstance(wyr, str) or not wyr.strip():
            ostrzezenia.append(f"{pid}: wyrażenie musi być tekstem")
        elif "termin_wyrazenie" not in p:
            p["termin_wyrazenie"] = wyr.strip()
            n += 1
    return n, ostrzezenia


def main():
    if len(sys.argv) < 2:
        sys.exit("Użycie: python3 uzupelnij.py wynik.json [pola-agenta.json]")
    wynik_path = Path(sys.argv[1])
    reszta = [a for a in sys.argv[2:] if a != "--wyrazenia"]
    tryb_wyrazen = "--wyrazenia" in sys.argv[2:]
    domyslny = "wyrazenia.json" if tryb_wyrazen else "pola-agenta.json"
    pola_path = Path(reszta[0]) if reszta else wynik_path.parent / domyslny
    wynik = json.loads(wynik_path.read_text(encoding="utf-8"))
    pola = json.loads(pola_path.read_text(encoding="utf-8"))
    n, ostrz = (scal_wyrazenia if tryb_wyrazen else scal)(wynik, pola)
    wynik_path.write_text(json.dumps(wynik, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Uzupełniono pozycji: {n}")
    for o in ostrz:
        print(f"  ⚠ {o}")


if __name__ == "__main__":
    main()
