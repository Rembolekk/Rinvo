#!/usr/bin/env python3
"""zakazy_czas.py – zakazy ograniczone w czasie wygasają.

Zakaz z okresem w tytule albo cytacie („6–12.10”, „19–23.10”, „(2–6.11)”, „w tym tygodniu”, „od 19 do 23”) przestaje
obowiązywać po jego końcu: przechodzi do „Wygasłe” (w karcie: zakazy_wygasle, na stronie: sekcja „Wygasłe”), a strażnik
(wysyłka maili, agent) go nie stosuje. Okres liczy daty.py z tekstu zakazu i daty źródła (nazwa pliku rozmowy albo maila,
w którym padł cytat), nie model. Zakaz bez okresu (albo z warunkiem zamiast dat) obowiązuje, dopóki ktoś go nie uchyli.
"""

import re
from datetime import date
from pathlib import Path

import daty

_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*[–-]\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\d)")
_OD_DO = re.compile(r"\bod\s+[^.;()]{1,40}?\s+do\s+[^.;()]{1,40}", re.IGNORECASE)
_TYDZIEN = re.compile(r"w\s+tym\s+tygodniu", re.IGNORECASE)


def data_z_nazwy(sciezka):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(str(sciezka)).name)
    return date.fromisoformat(m.group(1)) if m else None


def data_zrodla_cytatu(klient, cytaty, root="."):
    """Data (z nazwy pliku) pierwszej rozmowy albo maila klienta, w której cytat występuje dosłownie."""
    root = Path(root)
    pliki = sorted((root / "ops/transkrypcje" / klient).glob("*.md")) + sorted((root / "ops/maile" / klient).glob("*.md"))
    for plik in pliki:
        tekst = re.sub(r"\s+", " ", plik.read_text(encoding="utf-8").replace("**", ""))
        if any(re.sub(r"\s+", " ", c) in tekst for c in (cytaty or []) if c):
            return data_z_nazwy(plik)
    return None


def okres(zakaz, data_zrodla, dzis=None):
    """{"od": date, "do": date, "skad": fragment} z tytułu albo cytatu zakazu, albo None (bez ograniczenia czasowego)."""
    d0 = data_zrodla or dzis or date.today()
    for tekst in [zakaz.get("tytul", "")] + list(zakaz.get("cytat") or []):
        m = _RANGE.search(tekst)
        if m:
            rok = int(m.group(4)) + (2000 if m.group(4) and len(m.group(4)) == 2 else 0) if m.group(4) else d0.year
            try:
                return {"od": date(rok, int(m.group(3)), int(m.group(1))), "do": date(rok, int(m.group(3)), int(m.group(2))), "skad": m.group(0)}
            except ValueError:
                continue
        if _TYDZIEN.search(tekst) and data_zrodla:
            r = daty.oblicz_wyrazenie("w tym tygodniu", data_zrodla)
            if r:
                return {"od": r["od"], "do": r["do"], "skad": "w tym tygodniu"}
        m = _OD_DO.search(tekst)
        if m and data_zrodla:
            r = daty.oblicz_wyrazenie(m.group(0), data_zrodla)
            if r and r.get("rodzaj") == "zakres":
                return {"od": r["od"], "do": r["do"], "skad": m.group(0)}
    return None


def _okres_zapisany(zakaz):
    o = zakaz.get("okres")
    if o and o.get("do"):
        return {"od": date.fromisoformat(o["od"]), "do": date.fromisoformat(o["do"]), "skad": o.get("skad", "")}
    return None


def okres_zakazu(zakaz, klient=None, root=".", dzis=None):
    """Zapisany okres albo policzony z tekstu i daty źródła (zakaz.zrodlo albo wyszukanie cytatu w rozmowach klienta)."""
    zapisany = _okres_zapisany(zakaz)
    if zapisany:
        return zapisany
    zrodlo = data_z_nazwy(zakaz["zrodlo"]) if zakaz.get("zrodlo") and data_z_nazwy(zakaz["zrodlo"]) else None
    if zrodlo is None and klient:
        zrodlo = data_zrodla_cytatu(klient, zakaz.get("cytat"), root)
    return okres(zakaz, zrodlo, dzis)


def stan_zakazow(karta, dzis, klient=None, root="."):
    """(aktywne, wygasłe): czysta funkcja, niczego nie zapisuje. Wygasłe = już zapisane w karcie + te, którym minął okres."""
    klient = klient or (karta or {}).get("klient")
    aktywne, wygasle = [], list((karta or {}).get("zakazy_wygasle") or [])
    for z in (karta or {}).get("zakazy") or []:
        o = okres_zakazu(z, klient, root, dzis)
        if o and o["do"] < dzis:
            wygasle.append({**z, "okres": {"od": o["od"].isoformat(), "do": o["do"].isoformat(), "skad": o["skad"]},
                            "wygasl": (o["do"]).isoformat()})
        else:
            aktywne.append(z)
    return aktywne, wygasle


def aktywne_zakazy(karta, dzis=None, klient=None, root="."):
    """Zakazy, które nadal obowiązują (do użycia przez strażników)."""
    return stan_zakazow(karta, dzis or date.today(), klient, root)[0]


def przenies_wygasle(karta, dzis, klient=None, root="."):
    """Zapisuje w karcie okresy zakazów czasowych i przenosi wygasłe do karta["zakazy_wygasle"]. Zwraca listę przeniesionych id."""
    klient = klient or karta.get("klient")
    zostaja, przeniesione = [], []
    wygasle = karta.setdefault("zakazy_wygasle", [])
    for z in karta.get("zakazy") or []:
        o = okres_zakazu(z, klient, root, dzis)
        if o:
            z["okres"] = {"od": o["od"].isoformat(), "do": o["do"].isoformat(), "skad": o["skad"]}
        if o and o["do"] < dzis:
            wygasle.append({**z, "wygasl": o["do"].isoformat()})
            przeniesione.append(z.get("id"))
        else:
            zostaja.append(z)
    karta["zakazy"] = zostaja
    if not wygasle:
        karta.pop("zakazy_wygasle", None)
    return przeniesione


# ── blokady typu „nic nowego nie startuje” ────────────────────────────────────

def czy_blokada(zakaz, Z):
    """Zakaz-blokada: tytuł pasuje do wzorców z ops/zasady.json → blokady.wzorce_zakazu (np. „Nic nowego nie startuje 19–23.10”)."""
    return any(re.search(w, zakaz.get("tytul", ""), re.IGNORECASE) for w in Z["blokady"]["wzorce_zakazu"])


def aktywne_blokady(karta, dzis, klient, Z, root="."):
    """Blokady, których okres obejmuje dzisiaj (przed początkiem okresu jeszcze nie blokują)."""
    wynik = []
    for z in aktywne_zakazy(karta, dzis, klient, root):
        o = okres_zakazu(z, klient, root, dzis)
        if o and czy_blokada(z, Z) and o["od"] <= dzis <= o["do"]:
            wynik.append(z)
    return wynik


def zadanie_nowe(zg_tekst, etykiety, Z):
    """True dla zadania „nowego” (kampania, marka, funkcja, tekst), False dla poprawki błędu albo korekty istniejącej konfiguracji.
    Etykieta Błąd i słowa korekty wygrywają; nierozpoznane zadanie uznajemy za poprawkę (blokada dotyczy tylko jawnie nowych rzeczy)."""
    B = Z["blokady"]
    t = zg_tekst.lower()
    if set(etykiety) & set(B["dozwolone_etykiety"]):
        return False
    korekta = [s for s in B["dozwolone_slowa"] if s not in ("godzin", "adres")]
    if any(s in t for s in korekta):
        return False
    if any(s in t for s in B["blokowane_slowa"]):
        return True
    return False


def powod_blokady(karta, dzis, klient, zg_tekst, etykiety, Z, root="."):
    """Powód odłożenia zadania przez aktywną blokadę (tekst) albo None. Poprawki błędów i korekty istniejącej konfiguracji przechodzą."""
    bl = aktywne_blokady(karta, dzis, klient, Z, root)
    if bl and zadanie_nowe(zg_tekst, etykiety, Z):
        o = okres_zakazu(bl[0], klient, root, dzis)
        return f"blokada {bl[0].get('id', '?')}: {bl[0].get('tytul', '')} (do {o['do'].isoformat()}); to nowa rzecz, poprawki błędów nie są blokowane"
    return None
