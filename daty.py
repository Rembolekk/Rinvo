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


# ── daty względne liczone przez kod ───────────────────────────────────────────
# Model podaje obok daty także dosłowne wyrażenie ("do piątku", "przyszły czwartek", "dwudziesty siódmy"),
# a kod liczy z niego datę względem daty źródła (rozmowy albo maila). Gdy kod umie policzyć, jego data
# wygrywa; gdy nie umie, zostaje data modelu z oznaczeniem "wniosek".

import calendar
import re

_MIESIACE = {
    "stycznia": 1, "styczeń": 1, "lutego": 2, "luty": 2, "marca": 3, "marzec": 3, "kwietnia": 4,
    "kwiecień": 4, "maja": 5, "maj": 5, "czerwca": 6, "czerwiec": 6, "lipca": 7, "lipiec": 7,
    "sierpnia": 8, "sierpień": 8, "września": 9, "wrzesień": 9, "października": 10, "październik": 10,
    "listopada": 11, "listopad": 11, "grudnia": 12, "grudzień": 12,
}

# dzień tygodnia → wzorzec (wszystkie odmiany); 0 = poniedziałek
_DNI = [
    (0, r"poniedział(?:ek|ku|kiem|kowi)"), (1, r"wtor(?:ek|ku|kiem|kowi)"), (2, r"środ(?:a|ę|y|zie|ą)"),
    (3, r"czwart(?:ek|ku|kiem|kowi)"), (4, r"piąt(?:ek|ku|kiem|kowi)"), (5, r"sob(?:ota|oty|otę|ocie|otą)"),
    (6, r"niedziel(?:a|ę|i|ą)"),
]

# liczebniki porządkowe 1–31 (mianownik, dopełniacz, narzędnik/miejscownik, celownik)
_POR = {}
for _rdzen, _n in (("pierwsz", 1), ("czwart", 4), ("piąt", 5), ("szóst", 6), ("siódm", 7), ("ósm", 8),
                   ("dziewiąt", 9), ("dziesiąt", 10), ("jedenast", 11), ("dwunast", 12), ("trzynast", 13),
                   ("czternast", 14), ("piętnast", 15), ("szesnast", 16), ("siedemnast", 17),
                   ("osiemnast", 18), ("dziewiętnast", 19), ("dwudziest", 20), ("trzydziest", 30)):
    for _koncowka in ("y", "ego", "ym", "emu"):
        _POR[_rdzen + _koncowka] = _n
for _slowo in ("drugi", "drugiego", "drugim", "drugiemu"):
    _POR[_slowo] = 2
for _slowo in ("trzeci", "trzeciego", "trzecim", "trzeciemu"):
    _POR[_slowo] = 3

_SLOWA_FUNKCYJNE = {"do", "od", "na", "w", "we", "po", "przed", "dnia", "około", "ok", "dzień"}


def _norm(tekst):
    t = re.sub(r"[„”\"'.,;:!?()\[\]]", lambda m: " " if m.group() != "." else m.group(), str(tekst or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _poniedzialek(d):
    return d - timedelta(days=d.weekday())


def _ostatni_dzien_miesiaca(rok, mies):
    return date(rok, mies, calendar.monthrange(rok, mies)[1])


def _dzien_miesiaca_od(dzien, baza):
    """Najbliższy dzień miesiąca `dzien` w dniu `baza` lub po nim (ten miesiąc, a jeśli minął, następny)."""
    rok, mies = baza.year, baza.month
    for _ in range(14):
        if dzien <= calendar.monthrange(rok, mies)[1]:
            kandydat = date(rok, mies, dzien)
            if kandydat >= baza:
                return kandydat
        mies += 1
        if mies > 12:
            rok, mies = rok + 1, 1
    return None


def _dzien_slowny(tokeny):
    """Liczebnik porządkowy dnia z listy słów: 'dwudziesty siódmy' → 27. Zwraca (dzień, ile_słów) albo None."""
    for i, tok in enumerate(tokeny):
        w = _POR.get(tok)
        if w is None:
            continue
        if w in (20, 30) and i + 1 < len(tokeny) and _POR.get(tokeny[i + 1], 99) <= 9:
            return w + _POR[tokeny[i + 1]], i, 2
        return w, i, 1
    return None


def _jeden(d):
    return {"od": d, "do": d, "rodzaj": "dzien"}


def _pojedyncze(t, d0, kompozyt=False):
    """Jedno wyrażenie (bez zakresu) → {"od","do","rodzaj"} albo None."""
    t = _norm(t)
    tokeny = t.split()
    while tokeny and tokeny[0] in _SLOWA_FUNKCYJNE:
        tokeny = tokeny[1:]
    t = " ".join(tokeny)
    if not t:
        return None

    # data jawna: 2026-10-27, 27.10, 27.10.2026
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return _jeden(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b", t)
    if m:
        rok = int(m.group(3)) if m.group(3) else d0.year
        rok += 2000 if rok < 100 else 0
        try:
            dat = date(rok, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and dat < d0:
            dat = date(rok + 1, dat.month, dat.day)
        return _jeden(dat)

    # dzień + nazwa miesiąca: "27 października", "dwudziestego siódmego października"
    mies = next((_MIESIACE[x] for x in tokeny if x in _MIESIACE), None)
    liczba = next((int(x) for x in tokeny if x.isdigit() and 1 <= int(x) <= 31), None)
    slowny = _dzien_slowny(tokeny)
    if mies and (liczba or slowny):
        dzien = liczba or slowny[0]
        try:
            dat = date(d0.year, mies, dzien)
        except ValueError:
            return None
        return _jeden(dat if dat >= d0 else date(d0.year + 1, mies, dzien))

    if kompozyt and not (slowny and any(re.search(r"\b" + wz + r"\b", t) for _, wz in _DNI)):
        return None        # „od jutra, środa i czwartek”: kilka fragmentów, nie umiemy jednoznacznie

    # słowa względne (także w krótkim wyrażeniu: „przekażę mu dziś”, „poprawię dzisiaj”)
    if re.search(r"\bpojutrze\b", t):
        return _jeden(d0 + timedelta(days=2))
    if re.search(r"\b(?:jutro|jutra)\b", t):
        return _jeden(d0 + timedelta(days=1))
    if re.search(r"\bwczoraj\b", t):
        return _jeden(d0 - timedelta(days=1))
    if re.search(r"\b(?:dziś|dzisiaj|dzisiejszego)\b", t):
        return _jeden(d0)

    # dni tygodnia (dokładnie jeden dzień; listy „środa i czwartek” są niejednoznaczne)
    znalezione = [(wd, mm) for wd, wz in _DNI for mm in re.finditer(r"\b" + wz + r"\b", t)]
    if len({wd for wd, _ in znalezione}) > 1:
        return None
    if znalezione and slowny:
        # „dwudziesty siódmy, wtorek”: data z liczebnika, a dzień tygodnia tylko ją potwierdza
        dat = _dzien_miesiaca_od(slowny[0], d0)
        return _jeden(dat) if dat and dat.weekday() == znalezione[0][0] else None
    przyszly = re.search(r"\b(?:przyszł\w+|następn\w+|kolejn\w+)\b", t) is not None
    if znalezione:
        wd = znalezione[0][0]
        if przyszly:
            return _jeden(_poniedzialek(d0) + timedelta(days=7 + wd))
        if re.search(r"\b(?:tego|bieżącego|tym)\s+tygodni\w*\b", t):
            dat = _poniedzialek(d0) + timedelta(days=wd)
            return _jeden(dat) if dat >= d0 else None
        delta = (wd - d0.weekday()) % 7 or 7          # najbliższy następny; to samo imię dnia = za tydzień
        return _jeden(d0 + timedelta(days=delta))

    # tydzień i miesiąc
    if re.search(r"\b(?:przyszł\w+|następn\w+)\s+tygodni\w*\b|\bna\s+przyszły\s+tydzień\b", t):
        pn = _poniedzialek(d0) + timedelta(days=7)
        return {"od": pn, "do": pn + timedelta(days=4), "rodzaj": "tydzien"}
    if re.search(r"\b(?:tym|tego|bieżącym|bieżącego)\s+tygodni\w*\b|\bkońca\s+tygodnia\b|\bkoniec\s+tygodnia\b", t):
        piatek = _poniedzialek(d0) + timedelta(days=4)
        return {"od": d0, "do": max(d0, piatek), "rodzaj": "tydzien"}
    if re.search(r"\b(?:przyszł\w+|następn\w+)\s+miesiąc\w*\b", t):
        rok, mies = (d0.year + 1, 1) if d0.month == 12 else (d0.year, d0.month + 1)
        return {"od": date(rok, mies, 1), "do": _ostatni_dzien_miesiaca(rok, mies), "rodzaj": "miesiac"}
    if re.search(r"\bkońca\s+miesiąca\b|\bkoniec\s+miesiąca\b|\b(?:tym|bieżącym)\s+miesiącu\b", t):
        return {"od": d0, "do": _ostatni_dzien_miesiaca(d0.year, d0.month), "rodzaj": "miesiac"}

    # sam dzień miesiąca: tylko gdy całe wyrażenie to liczebnik (inaczej „drugi raz” = 2. dnia)
    if slowny and slowny[2] == len(tokeny):
        dat = _dzien_miesiaca_od(slowny[0], d0)
        return _jeden(dat) if dat else None
    if len(tokeny) == 1 and tokeny[0].isdigit() and 1 <= int(tokeny[0]) <= 31:
        dat = _dzien_miesiaca_od(int(tokeny[0]), d0)
        return _jeden(dat) if dat else None
    return None


def oblicz_wyrazenie(wyrazenie, data_zrodla):
    """Data (albo zakres) z polskiego wyrażenia względem daty źródła.

    Zwraca {"od": date, "do": date, "rodzaj": "dzien"|"zakres"|"tydzien"|"miesiac"} albo None,
    gdy wyrażenia nie umie policzyć (wtedy zostaje data modelu z oznaczeniem „wniosek”).
    Reguły: dzień tygodnia = najbliższy NASTĘPNY (ten sam dzień co źródło = za tydzień); „przyszły
    czwartek” = czwartek następnego tygodnia; „w tym tygodniu” = do piątku; „w przyszłym tygodniu” =
    pon–pt następnego tygodnia; „do końca miesiąca” = ostatni dzień miesiąca; sam liczebnik dnia
    („dwudziesty siódmy”) = najbliższy taki dzień miesiąca."""
    d0 = data_zrodla if isinstance(data_zrodla, date) else parse_date(data_zrodla)
    t = _norm(wyrazenie)
    if d0 is None or not t:
        return None
    m = re.match(r"^(?:od\s+)?(.+?)\s+do\s+(.+)$", t)       # zakres: "od 19 do 23 października" itp.
    if m:
        a = _pojedyncze(m.group(1), d0)
        if a and a["rodzaj"] == "dzien":
            b = _pojedyncze(m.group(2), a["do"])
            if b is None:
                # "od 19 do 23 października": miesiąc tylko przy drugim końcu
                mies = next((x for x in m.group(2).split() if x in _MIESIACE), None)
                if mies:
                    a = _pojedyncze(f"{m.group(1)} {mies}", d0)
                    b = _pojedyncze(m.group(2), d0)
            if a and b and b["rodzaj"] == "dzien" and b["do"] >= a["od"]:
                return {"od": a["od"], "do": b["do"], "rodzaj": "zakres"}
        return None
    kompozyt = re.search(r"[,;]|\si\s|\soraz\s|\slub\s", " " + str(wyrazenie).lower() + " ") is not None
    return _pojedyncze(t, d0, kompozyt)


def znajdz_date(tekst, data_zrodla):
    """Pierwsza jawna data w tekście ("21.10", "21.10.2026", "21 października") albo None."""
    d0 = data_zrodla if isinstance(data_zrodla, date) else parse_date(data_zrodla)
    t = _norm(tekst)
    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b|\b\d{1,2}\s+(?:" +
                  "|".join(_MIESIACE) + r")\b", t)
    if not m or d0 is None:
        return None
    r = _pojedyncze(m.group(0), d0)
    return r["od"] if r else None


def data_zrodla_z_wyniku(d):
    """Data źródła: dla maila z pliku maila zapisanego przez maile.py (model mógł się pomylić),
    w pozostałych przypadkach spotkanie.data."""
    zrodlo = d.get("zrodlo", "")
    if "maile" in Path(str(zrodlo)).parts and Path(zrodlo).exists():
        m = re.search(r"^- \*\*Data:\*\* (\d{4}-\d{2}-\d{2})", Path(zrodlo).read_text(encoding="utf-8"), re.M)
        if m:
            return parse_date(m.group(1))
    return parse_date(d.get("spotkanie", {}).get("data"))


def _iso(x):
    return x.isoformat() if x else None


def _daty_faktu(typ, wyr, r, model_od, model_do):
    """Przekłada policzone wyrażenie na pola faktu zależnie od jego typu albo zwraca None („wniosek”),
    gdy nie da się tego zrobić jednoznacznie. Zwraca (od, do) jako teksty ISO."""
    if typ == "termin":
        return _iso(r["do"]), _iso(r["do"])
    if typ == "start_nie_wczesniej":
        if r["rodzaj"] in ("tydzien", "miesiac") and not re.search(r"przyszł|następn", _norm(wyr)):
            return None                       # „w tym tygodniu” (zakaz) nie mówi, kiedy start
        return _iso(r["od"]), model_do
    # blokada, urlop
    if r["rodzaj"] in ("zakres", "tydzien", "miesiac"):
        return _iso(r["od"]), _iso(r["do"])
    if _norm(wyr).startswith("od "):          # „od dziewiętnastego”: tylko początek
        return _iso(r["od"]), model_do
    return model_od, _iso(r["do"])            # „w czwartek”, „do czwartku”: koniec blokady


def _dd_mm(iso):
    d = parse_date(str(iso)[:10]) if iso else None
    return f"{d.day}.{d.month:02d}" if d else None


def _zamien_date(tekst, stara_iso, nowa_iso):
    """Zamienia w tekście „17.10” (i „17.10.2026”) na nową datę; reszta tekstu bez zmian."""
    stara, nowa = _dd_mm(stara_iso), _dd_mm(nowa_iso)
    if not stara or not nowa or stara == nowa or not isinstance(tekst, str):
        return tekst
    return re.sub(r"(?<![\d.])" + re.escape(stara).replace("0", "0?", 1) + r"(?:\.\d{4})?(?![\d])", nowa, tekst)


def popraw_teksty_pozycji(d, p, stary_termin, nowy_termin):
    """Gdy kod zmienił termin pozycji, poprawia tę samą datę w jej tytule, opisie, polach dla agenta,
    przypomnieniu i szkicu maila (model wpisywał w nie błędną datę, np. „do piątku 17.10”)."""
    for pole in ("tytul", "opis", "cel", "jak_sprawdzic", "szkic_klienta"):
        if p.get(pole):
            p[pole] = _zamien_date(p[pole], stary_termin, nowy_termin)
    if isinstance(p.get("kryteria_akceptacji"), list):
        p["kryteria_akceptacji"] = [_zamien_date(k, stary_termin, nowy_termin) for k in p["kryteria_akceptacji"]]
    pr = p.get("przypomnienie")
    if isinstance(pr, dict):
        for k in ("data", "limit", "uwagi"):
            if isinstance(pr.get(k), str):
                pr[k] = (nowy_termin if pr[k][:10] == str(stary_termin)[:10] else _zamien_date(pr[k], stary_termin, nowy_termin))
    if isinstance(d.get("szkic_maila"), str):
        d["szkic_maila"] = _zamien_date(d["szkic_maila"], stary_termin, nowy_termin)


def popraw_daty_wzgledne(d, data_zrodla):
    """Stosuje oblicz_wyrazenie do fakty_czasowe (pole "wyrazenie") i terminów pozycji ("termin_wyrazenie").
    Zwraca (ostrzeżenia_o_rozbieżnościach, lista_zmian). Idempotentne: pierwotna data modelu jest
    zapamiętana w "data_modelu"/"termin_modelu", więc kolejne uruchomienia nie gubią informacji."""
    ostrzezenia, zmiany = [], []
    for f in d.get("fakty_czasowe", []):
        wyr = f.get("wyrazenie")
        if f.get("data_modelu"):
            model_od, model_do = f["data_modelu"].get("od"), f["data_modelu"].get("do")
        else:
            model_od, model_do = f.get("od"), f.get("do")
        if not wyr:
            f["zrodlo_daty"] = "wniosek"
            continue
        r = oblicz_wyrazenie(wyr, data_zrodla)
        if r is None:
            f["zrodlo_daty"] = "wniosek"          # kod nie umie policzyć: zostaje data modelu
            continue
        typ = f.get("typ")
        nowe = _daty_faktu(typ, wyr, r, model_od, model_do)
        if nowe is None:
            f["zrodlo_daty"] = "wniosek"          # wyrażenie nie przekłada się jednoznacznie na ten typ faktu
            continue
        nowe_od, nowe_do = nowe
        f["zrodlo_daty"] = "kod"
        stare_ref = (model_od, model_do or model_od)
        nowe_ref = (nowe_od, nowe_do or nowe_od)
        # w tygodniach pn–pt model często kończy w niedzielę; to ten sam termin roboczy
        rownowazne = (r["rodzaj"] == "tydzien" and stare_ref[0] == nowe_ref[0] and
                      _ostatni_roboczy(parse_date(stare_ref[1])) == _ostatni_roboczy(parse_date(nowe_ref[1])))
        if nowe_ref != stare_ref and not rownowazne:
            f["data_modelu"] = {"od": model_od, "do": model_do}
            ostrzezenia.append({
                "id": "fakt", "klucz_sprawy": f.get("dotyczy", ""), "tytul": f"„{wyr}”",
                "uwaga": (f"model podał {model_od}"
                          + (f"–{model_do}" if model_do and model_do != model_od else "")
                          + f", kod policzył {nowe_od}"
                          + (f"–{nowe_do}" if nowe_do and nowe_do != nowe_od else "")
                          + f" (względem {data_zrodla.isoformat()}); użyto daty z kodu"),
            })
            zmiany.append((f.get("dotyczy", ""), wyr, f"{model_od}–{model_do}" if model_do else model_od,
                           f"{nowe_od}–{nowe_do}" if nowe_do and nowe_do != nowe_od else nowe_od))
        f["od"] = nowe_od
        if typ in ("termin", "blokada", "urlop") and nowe_do:
            f["do"] = nowe_do

    for p in d.get("pozycje", []):
        wyr = p.get("termin_wyrazenie")
        if not wyr:
            continue
        model = p.get("termin_modelu", p.get("termin"))
        r = oblicz_wyrazenie(wyr, data_zrodla)
        if r is None or (_norm(wyr).startswith("od ") and r["rodzaj"] != "zakres"):
            p["termin_zrodlo"] = "wniosek"        # np. „od jutra” to początek, nie termin: zostaje data modelu
            continue
        nowy = _iso(r["do"])                       # termin pozycji to jedna data: koniec (dnia, tygodnia, zakresu)
        p["termin_zrodlo"] = "kod"
        model_data = parse_date(str(model)[-10:]) if isinstance(model, str) else None
        rownowazny = (r["rodzaj"] in ("tydzien", "miesiac") and model_data is not None and
                      _ostatni_roboczy(model_data) == _ostatni_roboczy(r["do"]))
        if nowy != model and not rownowazny:
            p["termin_modelu"] = model
            ostrzezenia.append({
                "id": p.get("id", "?"), "klucz_sprawy": p.get("klucz_sprawy", ""), "tytul": f"„{wyr}”",
                "uwaga": f"termin: model podał {model}, kod policzył {nowy} (względem {data_zrodla.isoformat()}); "
                         f"użyto daty z kodu"})
            zmiany.append((p.get("klucz_sprawy", ""), wyr, str(model), nowy))
            p["termin"] = nowy
            if isinstance(model, str) and model_data is not None:
                popraw_teksty_pozycji(d, p, _iso(model_data), nowy)
    return ostrzezenia, zmiany


def _ostatni_roboczy(d):
    if d is None:
        return None
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d


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

    # Daty względne liczy kod: jego data wygrywa nad datą modelu, rozbieżność trafia do ostrzeżeń
    data_zrodla = data_zrodla_z_wyniku(d) or meeting_date
    rozbieznosci, zmiany_dat = popraw_daty_wzgledne(d, data_zrodla)
    fakty = d.get("fakty_czasowe", [])
    for f in fakty:
        if not parse_date(f.get("od")):
            print(f"Błąd: po przeliczeniu brak poprawnego pola 'od' w fakcie: {f}", file=sys.stderr)
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

    d["ostrzezenia_dat"] = rozbieznosci + ostrzezenia

    wynik_path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"OK: okna_czasowe dla {len(okna_czasowe)} spraw → {wynik_path}")
    for o in okna_czasowe:
        ws = "; ".join(
            f'{w["od"]} – {w["do"] or "→"}' for w in o["okna"]
        )
        print(f"  {o['klucz_sprawy']}: {ws}")

    if zmiany_dat:
        print(f"\nDaty względne przeliczone przez kod ({len(zmiany_dat)}):")
        for klucz, wyr, przed, po in zmiany_dat:
            print(f"  {klucz or '-'}: „{wyr}”: {przed} → {po}")
    if ostrzezenia:
        print(f"\nOstrzeżenia (brak faktu czasowego): {len(ostrzezenia)}")
        for w in ostrzezenia:
            print(f"  {w['id']} {w['klucz_sprawy']}")


if __name__ == "__main__":
    main()
