#!/usr/bin/env python3
"""daty.py – oblicza okna robocze z fakty_czasowe i zapisuje okna_czasowe do wynik.json.

Użycie:
  python -I daty.py wyniki/<klient>/<nazwa>/wynik.json

Czyta pole fakty_czasowe z wynik.json, oblicza wolne okna robocze (Pn–Pt) dla każdej
sprawy uwzględniając blokady specyficzne i globalne (dotyczy="wszystko_nowe"),
i zapisuje wynik w polu okna_czasowe.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path


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
    if not fakty:
        print("Brak fakty_czasowe — okna_czasowe puste.")
        d["okna_czasowe"] = []
        wynik_path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sys.exit(0)

    # Validate
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

    # Collect keys referenced with specific constraints
    keys = set()
    for f in fakty:
        k = f.get("dotyczy", "")
        if k and k != "wszystko_nowe":
            keys.add(k)

    okna_czasowe = []

    for klucz in sorted(keys):
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
                deadlines.append(od)
            elif typ == "start_nie_wczesniej" and od:
                if start_nie_wczesniej is None or od > start_nie_wczesniej:
                    start_nie_wczesniej = od

        all_blocks = global_blocks + specific_blocks

        # Determine start
        if start_nie_wczesniej:
            start = max(start_nie_wczesniej, meeting_date)
        else:
            start = meeting_date + timedelta(days=1)

        deadline = min(deadlines) if deadlines else None

        # Skip keys with no temporal constraints at all
        if not all_blocks and deadline is None and start_nie_wczesniej is None:
            continue

        windows = compute_windows(start, all_blocks, deadline)

        if windows:
            okna_czasowe.append({
                "klucz_sprawy": klucz,
                "okna": windows,
                "adnotacja": "policzone przez kod"
            })

    d["okna_czasowe"] = okna_czasowe
    wynik_path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: okna_czasowe dla {len(okna_czasowe)} spraw → {wynik_path}")
    for o in okna_czasowe:
        ws = "; ".join(
            f'{w["od"]} – {w["do"] or "→"}' for w in o["okna"]
        )
        print(f"  {o['klucz_sprawy']}: {ws}")


if __name__ == "__main__":
    main()
