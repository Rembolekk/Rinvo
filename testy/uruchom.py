#!/usr/bin/env python3
"""uruchom.py – sprawdza wynik.json względem pliku oczekiwań.

Użycie:
  python3 testy/uruchom.py wyniki/<klient>/<nazwa>/wynik.json testy/oczekiwania/<klient>-<nazwa>.json

Wyjście:
  PASS X/Y  – jeśli wszystkie testy przeszły (exit code 0)
  FAIL X/Y  – jeśli któryś nie przeszedł (exit code 1)
"""

import json
import sys
from pathlib import Path

# ── replika logiki etykiet z linear_sync.py ──────────────────────────────────

TYP_DO_ETYKIETY = {
    "bug": "Blad",
    "zmiana_konfiguracji": "Konfiguracja",
    "poprawka_bazy_wiedzy": "Konfiguracja",
    "finanse": "Finanse",
}

ETYKIETA_POLSKA = {
    "Blad": "Błąd",
    "Konfiguracja": "Konfiguracja",
    "Finanse": "Finanse",
    "Zadanie": "Zadanie",
    "Produkt": "Produkt",
    "Czeka na klienta": "Czeka na klienta",
    "Ryzyko": "Ryzyko",
    "Dla agenta": "Dla agenta",
    "Do weryfikacji": "Do weryfikacji",
    "Zablokowane przez zakaz": "Zablokowane przez zakaz",
}

TYPY_DLA_AGENTA = {"bug", "zmiana_konfiguracji", "poprawka_bazy_wiedzy"}


def _should_get_agent_label(item):
    if item.get("konflikt_z_zakazem"):
        return False
    if item.get("pewnosc") == "niska":
        return False
    if item.get("rodzaj") == "nowa_funkcja":
        return False
    return item.get("typ") in TYPY_DLA_AGENTA


def compute_labels(item):
    sekcja = item.get("sekcja")
    blocked_by_ban = item.get("konflikt_z_zakazem")
    labels = []

    if sekcja == 1:
        typ = item.get("typ", "")
        base = TYP_DO_ETYKIETY.get(typ, "Zadanie")
        labels.append(base if base != "Blad" else "Błąd")
        if blocked_by_ban:
            labels.append("Zablokowane przez zakaz")
        elif _should_get_agent_label(item):
            labels.append("Dla agenta")
        if item.get("pewnosc") == "niska":
            labels.append("Do weryfikacji")
    elif sekcja == 2:
        labels.append("Czeka na klienta")
        if item.get("pewnosc") == "niska":
            labels.append("Do weryfikacji")
    elif sekcja == 3:
        labels.append("Produkt")
        if item.get("pewnosc") == "niska":
            labels.append("Do weryfikacji")
    elif sekcja == 5:
        labels.append("Ryzyko")
        if item.get("pewnosc") == "niska":
            labels.append("Do weryfikacji")

    return labels


# ── szukanie pozycji po cytacie ───────────────────────────────────────────────

def find_pozycja(pozycje, fragment):
    matches = []
    for p in pozycje:
        for c in p.get("cytat", []):
            if fragment in c:
                matches.append(p)
                break
    return matches


# ── sprawdzanie oczekiwania ───────────────────────────────────────────────────

def check(wynik, exp):
    fragment = exp.get("fragment_cytatu", "")
    typ_sprawdzania = exp.get("typ_sprawdzania", "pozycje")

    if typ_sprawdzania == "zmiany_zdania":
        zmiany = wynik.get("zmiany_zdania", [])
        for z in zmiany:
            if fragment in z.get("cytat", "") or any(fragment in str(v) for v in z.values()):
                return True, ""
        return False, f"Nie znaleziono w zmiany_zdania: {fragment!r}"

    pozycje = wynik.get("pozycje", [])
    matches = find_pozycja(pozycje, fragment)

    if not matches:
        return False, f"Brak pozycji z cytatem: {fragment!r}"

    # Jeśli wiele pasuje, filtruj po sekcji
    if len(matches) > 1 and "oczekiwana_sekcja" in exp:
        filtered = [p for p in matches if p.get("sekcja") == exp["oczekiwana_sekcja"]]
        if filtered:
            matches = filtered

    if len(matches) > 1:
        ids = [p.get("id", "?") for p in matches]
        return False, f"Niejednoznaczne dopasowanie ({len(matches)} pozycji: {ids}) dla: {fragment!r}"

    p = matches[0]

    if "oczekiwana_sekcja" in exp:
        if p.get("sekcja") != exp["oczekiwana_sekcja"]:
            return False, (f"Sekcja: oczekiwano {exp['oczekiwana_sekcja']}, "
                           f"jest {p.get('sekcja')} (id={p.get('id')})")

    if "oczekiwany_status" in exp:
        if p.get("status") != exp["oczekiwany_status"]:
            return False, (f"Status: oczekiwano {exp['oczekiwany_status']!r}, "
                           f"jest {p.get('status')!r} (id={p.get('id')})")

    if "oczekiwana_pewnosc" in exp:
        if p.get("pewnosc") != exp["oczekiwana_pewnosc"]:
            return False, (f"Pewnosc: oczekiwano {exp['oczekiwana_pewnosc']!r}, "
                           f"jest {p.get('pewnosc')!r} (id={p.get('id')})")

    if "oczekiwane_etykiety" in exp:
        actual = compute_labels(p)
        for lbl in exp["oczekiwane_etykiety"]:
            if lbl not in actual:
                return False, (f"Brakuje etykiety {lbl!r} (jest: {actual}, "
                               f"typ={p.get('typ')}, rodzaj={p.get('rodzaj')}, "
                               f"pewnosc={p.get('pewnosc')}, zakaz={bool(p.get('konflikt_z_zakazem'))})")

    if "zakazane_etykiety" in exp:
        actual = compute_labels(p)
        for lbl in exp["zakazane_etykiety"]:
            if lbl in actual:
                return False, (f"Niedozwolona etykieta {lbl!r} obecna (jest: {actual}, "
                               f"typ={p.get('typ')}, rodzaj={p.get('rodzaj')})")

    if "oczekiwane_okna_min" in exp:
        klucz = p.get("klucz_sprawy")
        okna_list = wynik.get("okna_czasowe", [])
        entry = next((o for o in okna_list if o.get("klucz_sprawy") == klucz), None)
        if not entry:
            return False, f"Brak okna_czasowe dla {klucz!r}"
        n = len(entry.get("okna", []))
        if n < exp["oczekiwane_okna_min"]:
            return False, (f"Za mało okien dla {klucz!r}: "
                           f"{n} < {exp['oczekiwane_okna_min']}")

    return True, ""


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    if len(sys.argv) != 3:
        print("Użycie: python3 testy/uruchom.py wynik.json oczekiwania.json", file=sys.stderr)
        sys.exit(2)

    wynik_path = Path(sys.argv[1])
    oczekiwania_path = Path(sys.argv[2])

    if not wynik_path.exists():
        print(f"Błąd: brak {wynik_path}", file=sys.stderr)
        sys.exit(2)
    if not oczekiwania_path.exists():
        print(f"Błąd: brak {oczekiwania_path}", file=sys.stderr)
        sys.exit(2)

    wynik = json.loads(wynik_path.read_text(encoding="utf-8"))
    oczekiwania = json.loads(oczekiwania_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0
    failures = []

    for i, exp in enumerate(oczekiwania, 1):
        opis = exp.get("opis", f"test {i}")
        ok, reason = check(wynik, exp)
        if ok:
            passed += 1
            print(f"  PASS  {opis}")
        else:
            failed += 1
            print(f"  FAIL  {opis}")
            print(f"        {reason}")
            failures.append((opis, reason))

    total = passed + failed
    result_line = f"{'PASS' if failed == 0 else 'FAIL'} {passed}/{total}"
    print(f"\n{result_line}")

    if failures:
        print(f"\nNiepowodzenia ({len(failures)}):")
        for opis, reason in failures:
            print(f"  - {opis}: {reason}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
