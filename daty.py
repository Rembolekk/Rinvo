#!/usr/bin/env python3
"""daty.py – oblicza okna robocze z fakty_czasowe i zapisuje okna_czasowe do wynik.json.

Użycie:
  python -I daty.py wyniki/<klient>/<nazwa>/wynik.json

Czyta pole fakty_czasowe z wynik.json, oblicza wolne okna robocze (Pn–Pt) dla każdej
sprawy z sekcji 1 i 2 (i dla każdego klucza z fakty_czasowe), uwzględniając blokady
specyficzne i globalne (dotyczy="wszystko_nowe"). Zapisuje okna_czasowe i ostrzezenia_dat.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path


# Frazy sugerujące ograniczenie przyszłego działania — siatka bezpieczeństwa.
# Celowo nie zawierają samodzielnych nazw dni (wtorek, środa…) ani słów opisujących
# przeszłość (tydzień temu, w sobotę ktoś zadzwonił), bo te wywołują fałszywe alarmy.
TEMPORAL_WORDS = [
    # Urlop = zawsze ograniczenie
    "urlop", "urlopu", "urlopie", "urlopem",
    # Frazy wskazujące na przyszłe ograniczenie
    "po urlopie", "po powrocie",
    "nie wcześniej",
    # Konkretny tydzień / miesiąc / kwartał jako ograniczenie
    "w tym tygodniu", "przyszłym tygodniu", "następnym tygodniu", "tego tygodnia",
    "w tym miesiącu", "w tym kwartale", "w przyszłym kwartale",
    # Terminy z przyimkiem "do" + okres (deadline)
    "do końca tygodnia", "do końca miesiąca", "do końca dnia",
    "do jutra",
    "do czwartku", "do piątku", "do środy", "do wtorku", "do poniedziałku",
    "do soboty", "do niedzieli",
    # Starty z przyimkiem "od" + dzień tygodnia (start constraint)
    "od wtorku", "od środy", "od czwartku", "od piątku",
    "od poniedziałku", "od soboty",
    # Rozliczenia cykliczne
    "miesięcznie",
]


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def is_workday(d):
    return d.weekday() < 5  # Mon=0..Fri=4, Sat=5, Sun=6


def next_workday_from(d):
    while not is_workday(d):
        d += timedelta(days=1)
    return d


def merge_blocks(blocks):
    if not blocks:
        return []
    sorted_b = sorted(blocks, key=lambda x: x[0])
    merged = [list(sorted_b[0])]
    for od, do in sorted_b[1:]:
        if od <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], do)
        else:
            merged.append([od, do])
    return [(od, do) for od, do in merged]


def compute_windows(start_date, blocks, deadline=None):
    """
    Compute free Mon-Fri windows from start_date.
    blocks: list of (od_date, do_date) pairs (inclusive)
    deadline: optional last date to consider (inclusive)
    Returns list of {"od": "YYYY-MM-DD", "do": "YYYY-MM-DD or None"}
    """
    HORIZON = start_date + timedelta(days=365)
    end = min(deadline, HORIZON) if deadline else HORIZON
    merged = merge_blocks(blocks)

    windows = []
    current = next_workday_from(start_date)

    while current <= end:
        # Skip blocked ranges
        blocked = False
        skip_to = None
        for od, do in merged:
            if od <= current <= do:
                blocked = True
                skip_to = do
                break
        if blocked:
            current = next_workday_from(skip_to + timedelta(days=1))
            continue

        # Extend window through consecutive free workdays
        window_start = current
        window_end = current

        while True:
            candidate = window_end + timedelta(days=1)
            # Skip weekends
            while candidate <= end and not is_workday(candidate):
                candidate += timedelta(days=1)
            if candidate > end:
                break
            if any(od <= candidate <= do for od, do in merged):
                break
            window_end = candidate

        # Mark as open-ended if no deadline and window reaches the horizon
        if deadline is None and window_end >= HORIZON - timedelta(days=14):
            windows.append({"od": window_start.isoformat(), "do": None})
            break
        else:
            windows.append({"od": window_start.isoformat(), "do": window_end.isoformat()})

        current = next_workday_from(window_end + timedelta(days=1))

    return windows


def has_temporal_word(text):
    t = text.lower()
    return any(w in t for w in TEMPORAL_WORDS)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    if len(sys.argv) != 2:
        print("Użycie: python -I daty.py wynik.json", file=sys.stderr)
        sys.exit(1)

    wynik_path = Path(sys.argv[1])
    if not wynik_path.exists():
        print(f"Błąd: plik nie istnieje: {wynik_path}", file=sys.stderr)
        sys.exit(1)

    try:
        d = json.loads(wynik_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Błąd JSON: {e}", file=sys.stderr)
        sys.exit(1)

    fakty = d.get("fakty_czasowe", [])
    pozycje = d.get("pozycje", [])

    # Validate fakty
    VALID_TYPES = {"blokada", "urlop", "termin", "start_nie_wczesniej"}
    for f in fakty:
        if f.get("typ") not in VALID_TYPES:
            print(f"Błąd: nieznany typ '{f.get('typ')}' w fakty_czasowe. "
                  f"Dozwolone: {', '.join(sorted(VALID_TYPES))}", file=sys.stderr)
            sys.exit(1)
        if not f.get("cytat"):
            print(f"Błąd: fakt bez pola 'cytat': {f}", file=sys.stderr)
            sys.exit(1)
        if not parse_date(f.get("od")):
            print(f"Błąd: brak lub nieprawidłowe pole 'od' w fakcie: {f}", file=sys.stderr)
            sys.exit(1)

    meeting_date = parse_date(d.get("spotkanie", {}).get("data"))
    if not meeting_date:
        print("Błąd: brak daty spotkania (spotkanie.data) w wynik.json", file=sys.stderr)
        sys.exit(1)

    # Global blocks: urlop/blokada with dotyczy="wszystko_nowe"
    global_blocks = []
    for f in fakty:
        if f.get("dotyczy") == "wszystko_nowe" and f.get("typ") in ("blokada", "urlop"):
            od = parse_date(f["od"])
            do = parse_date(f.get("do")) or od
            global_blocks.append((od, do))

    # Keys from fakty_czasowe (specific constraints)
    keys_from_fakty = set()
    for f in fakty:
        k = f.get("dotyczy", "")
        if k and k != "wszystko_nowe":
            keys_from_fakty.add(k)

    # Keys from pozycje sekcja 1+2 (always included when global blocks exist)
    keys_from_pozycje = set()
    for p in pozycje:
        if p.get("sekcja") in (1, 2):
            k = p.get("klucz_sprawy")
            if k:
                keys_from_pozycje.add(k)

    all_keys = keys_from_fakty | keys_from_pozycje

    okna_czasowe = []

    for klucz in sorted(all_keys):
        specific_blocks = []
        deadlines = []
        start_nie_wczesniej = None

        for f in fakty:
            if f.get("dotyczy") != klucz:
                continue
            od = parse_date(f.get("od"))
            do = parse_date(f.get("do"))
            typ = f.get("typ")

            if typ in ("blokada", "urlop") and od:
                specific_blocks.append((od, do or od))
            elif typ == "termin" and od:
                # termin z zakresem („środa i czwartek", od–do) kończy się na końcu zakresu
                deadlines.append(do if do and do >= od else od)
            elif typ == "start_nie_wczesniej" and od:
                if start_nie_wczesniej is None or od > start_nie_wczesniej:
                    start_nie_wczesniej = od

        all_blocks = global_blocks + specific_blocks

        # Start date
        if start_nie_wczesniej:
            start = max(start_nie_wczesniej, meeting_date)
        else:
            start = meeting_date + timedelta(days=1)

        # If there are no constraints at all, skip (nothing useful to show)
        if not all_blocks and not deadlines and start_nie_wczesniej is None:
            continue

        # Deadline: use only if it's reachable (after all blocks end).
        # If all deadlines fall within blocks, drop them to avoid empty windows.
        merged_for_check = merge_blocks(all_blocks)
        reachable_deadlines = []
        for dl in deadlines:
            in_block = any(od <= dl <= do for od, do in merged_for_check)
            if not in_block:
                reachable_deadlines.append(dl)
        deadline = min(reachable_deadlines) if reachable_deadlines else None

        windows = compute_windows(start, all_blocks, deadline)

        if windows:
            okna_czasowe.append({
                "klucz_sprawy": klucz,
                "okna": windows,
                "adnotacja": "policzone przez kod"
            })

    d["okna_czasowe"] = okna_czasowe

    # ── ostrzezenia_dat: pozycje z cytatami o czasie bez faktu czasowego ─────
    # Sekcja 1+2 objęte blokadą ogólną są już w okna_czasowe — nie flagujemy ich.
    keys_with_facts = keys_from_fakty  # keys that have their own fakty entry
    has_global_blocks = len(global_blocks) > 0
    ostrzezenia = []
    for p in pozycje:
        sekcja = p.get("sekcja")
        if sekcja not in (1, 2, 3):
            continue
        klucz = p.get("klucz_sprawy", "")
        if klucz in keys_with_facts:
            continue
        # Sekcja 1+2 items covered by global blocks already have windows computed
        if sekcja in (1, 2) and has_global_blocks:
            continue
        cytaty = " ".join(p.get("cytat", []))
        if has_temporal_word(cytaty):
            ostrzezenia.append({
                "id": p.get("id", "?"),
                "klucz_sprawy": klucz,
                "tytul": p.get("tytul", ""),
                "uwaga": "cytat zawiera słowa czasowe, brak wpisu w fakty_czasowe",
            })

    d["ostrzezenia_dat"] = ostrzezenia

    wynik_path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: okna_czasowe dla {len(okna_czasowe)} spraw → {wynik_path}")
    for o in okna_czasowe:
        ws = "; ".join(
            f'{w["od"]} – {w["do"] or "→"}' for w in o["okna"]
        )
        print(f"  {o['klucz_sprawy']}: {ws}")

    if ostrzezenia:
        print(f"\nOstrzeżenia (brak faktu czasowego): {len(ostrzezenia)}")
        for w in ostrzezenia:
            print(f"  {w['id']} {w['klucz_sprawy']}")


if __name__ == "__main__":
    main()
