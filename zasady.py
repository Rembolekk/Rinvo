#!/usr/bin/env python3
"""zasady.py – silnik zasad „AI-first: kto robi co” (reguły z ops/zasady.json).

Jedno miejsce prawdy dla linear_sync.py, przetworz.py (Slack), testów i podsumowania:
  przypisz(item, zasady, karta, wielu_klientow)  → komu trafia pozycja i dlaczego
  etykiety_pozycji(...)                          → pełna lista etykiet Lineara

Wynik przypisz():
  {"komu": "agent" | "czlowiek" | "weryfikacja" | "czeka",
   "powody": [{"regula": id, "powod": tekst}], "wymaga_szkicu": bool}
  agent       – domyślnie (Dla agenta)
  czlowiek    – spełniona choć jedna reguła z czlowiek_gdy (Decyzja człowieka + komentarz z powodem)
  weryfikacja – agent, ale bez kryteriów akceptacji (Do weryfikacji, powód „brak kryteriów”)
  czeka       – sekcja 2: czeka na klienta (przypisanie dopiero po wznowieniu)
"""

import json
import re
from pathlib import Path

ZASADY_PATH = Path("ops/zasady.json")
PROSBY_PATH = Path("ops/produkt/prosby.json")

TYP_DO_ETYKIETY = {
    "bug": "Błąd",
    "zmiana_konfiguracji": "Konfiguracja",
    "poprawka_bazy_wiedzy": "Konfiguracja",
    "finanse": "Finanse",
}


def wczytaj_zasady(path=None):
    p = Path(path) if path else ZASADY_PATH
    if not p.is_absolute() and not p.exists():
        p = Path(__file__).resolve().parent / p      # działa też spoza katalogu projektu
    return json.loads(p.read_text(encoding="utf-8"))


def wczytaj_prosby(path=None):
    p = Path(path) if path else PROSBY_PATH
    if not p.is_absolute() and not p.exists():
        p = Path(__file__).resolve().parent / p
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def etykieta(zasady, nazwa):
    return zasady["etykiety"][nazwa]


# ── dopasowanie słów ──────────────────────────────────────────────────────────

def _pasuje(slowa, tekst):
    """Pierwsze słowo z listy występujące w tekście od początku wyrazu (bez wielkości liter)."""
    for s in slowa:
        if re.search(r"\b" + re.escape(s), tekst, re.I):
            return s
    return None


def _tekst(item, pola):
    return " ".join(str(item.get(p, "") or "") for p in pola)


# ── elementy reguł ────────────────────────────────────────────────────────────

def kryteria_ok(item):
    k = item.get("kryteria_akceptacji")
    return isinstance(k, list) and any(isinstance(x, str) and x.strip() for x in k)


def decyzja_zastrzezona(karta, klucz):
    """Osoby, którym karta zastrzega decyzję w tej sprawie (albo [])."""
    osoby = []
    for d in (karta or {}).get("decyzje_zastrzezone", []):
        if klucz and klucz in d.get("klucze_spraw", []):
            z = d.get("zastrzezone_dla", [])
            osoby += [z] if isinstance(z, str) else list(z)
    return osoby


def liczba_klientow_funkcji(prosby, klucz_funkcji, klient=None):
    klienci = {p.get("klient") for p in prosby.get(klucz_funkcji, {}).get("prosby", [])} if klucz_funkcji else set()
    if klient and klucz_funkcji:
        klienci.add(klient)
    return len(klienci)


def wielu_klientow(prosby, zasady, item, klient=None):
    prog = zasady.get("produkt", {}).get("wielu_klientow_od", 2)
    return liczba_klientow_funkcji(prosby, item.get("klucz_funkcji"), klient) >= prog


def drobna_zmiana(item, zasady):
    p = zasady.get("produkt", {})
    return (item.get("rodzaj") in p.get("drobna_rodzaje", [])
            and item.get("pewnosc") == p.get("drobna_wymaga_pewnosci", "wysoka"))


# ── główna decyzja ────────────────────────────────────────────────────────────

def _powody_czlowieka(item, zasady, karta, sekcja, wielu):
    cg = zasady["czlowiek_gdy"]
    powody = []

    def dodaj(regula, szczegol=""):
        powod = cg[regula]["powod"] + (f" ({szczegol})" if szczegol else "")
        powody.append({"regula": regula, "powod": powod})

    if item.get("konflikt_z_zakazem"):
        k = item["konflikt_z_zakazem"]
        dodaj("zakaz", f"zakaz {k.get('zakaz', '?')}: {k.get('uzasadnienie', '')}".strip(": "))
    osoby = decyzja_zastrzezona(karta, item.get("klucz_sprawy"))
    if osoby:
        dodaj("decyzja_zastrzezona", "decyduje: " + ", ".join(osoby))
    if item.get("pewnosc") == "niska":
        dodaj("pewnosc_niska")

    r = cg["pieniadze"]
    trafione = _pasuje(r.get("slowa", []), _tekst(item, r.get("szukaj_w", ["tytul", "opis"])))
    if item.get("typ") in r.get("typy", []):
        dodaj("pieniadze", f"typ: {item['typ']}")
    elif trafione:
        dodaj("pieniadze", f"słowo: „{trafione}”")

    r = cg["nieodwracalne"]
    trafione = _pasuje(r.get("slowa", []), _tekst(item, r.get("szukaj_w", ["tytul", "opis"])))
    if trafione:
        dodaj("nieodwracalne", f"słowo: „{trafione}”")

    r = cg["do_klienta"]
    trafione = _pasuje(r.get("slowa", []), _tekst(item, r.get("szukaj_w", ["tytul"])))
    if trafione:
        dodaj("do_klienta", f"słowo: „{trafione}”")

    if sekcja == 3 and item.get("typ") in zasady.get("produkt", {}).get("typy", []):
        if not (wielu or drobna_zmiana(item, zasady)):
            powody.append({"regula": "produkt", "powod": zasady["produkt"]["powod_czlowieka"]})
    return powody


def powody_flag(item, zasady):
    """Powody wynikające ze znaczników kontroli pozycji (niepełna transkrypcja, pomyłka mówcy, inny klient…)."""
    mapa = zasady.get("flagi_powody", {})
    return [{"regula": f"flaga_{f}", "powod": mapa[f]} for f in item.get("flagi", []) if f in mapa]


def przypisz(item, zasady, karta=None, wielu_klientow=False, sekcja=None):
    """Komu trafia pozycja. sekcja: nadpisuje item["sekcja"] (np. 1 przy ocenie „po wznowieniu”)."""
    sekcja = sekcja if sekcja is not None else item.get("sekcja")
    klucz = item.get("klucz_sprawy")
    if sekcja == 2:
        return {"komu": "czeka", "powody": [], "wymaga_szkicu": False}
    if sekcja == 5:
        # ryzyko prowadzą ludzie (etykieta Ryzyko); agent dostaje osobne zadanie przygotowawcze
        return {"komu": "ryzyko", "powody": [], "wymaga_szkicu": False}
    if item.get("przygotowawcze"):
        # zadanie przygotowawcze do ryzyka (notatka): z definicji dla agenta, ma kryteria z szablonu
        return {"komu": "agent" if kryteria_ok(item) else "weryfikacja",
                "powody": [] if kryteria_ok(item) else
                [{"regula": "brak_kryteriow", "powod": zasady["agent"]["powod_braku_kryteriow"]}],
                "wymaga_szkicu": False}

    powody = _powody_czlowieka(item, zasady, karta, sekcja, wielu_klientow)
    wymaga_szkicu = any(p["regula"] == "do_klienta" for p in powody) and \
        zasady["czlowiek_gdy"]["do_klienta"].get("wymaga_szkicu", False)

    nadpisanie = (zasady.get("nadpisania") or {}).get(klucz) if klucz else None
    if nadpisanie == "czlowiek" and not powody:
        powody = [{"regula": "nadpisanie", "powod": "ręczny wyjątek w ops/zasady.json"}]
    if nadpisanie == "agent":
        powody = []

    flagowe = powody_flag(item, zasady)
    if powody:
        return {"komu": "czlowiek", "powody": powody + flagowe, "wymaga_szkicu": wymaga_szkicu}
    if flagowe:                                  # znaczniki kontroli (higiena.py): nigdy Dla agenta, tylko Do weryfikacji
        return {"komu": "weryfikacja", "powody": flagowe, "wymaga_szkicu": False}
    if zasady["agent"].get("wymagaj_kryteriow", True) and not kryteria_ok(item):
        return {"komu": "weryfikacja",
                "powody": [{"regula": "brak_kryteriow", "powod": zasady["agent"]["powod_braku_kryteriow"]}],
                "wymaga_szkicu": False}
    return {"komu": "agent", "powody": [], "wymaga_szkicu": False}


def etykiety_pozycji(item, zasady, karta=None, wielu=False):
    """Pełna lista etykiet pozycji (sekcje 1, 2, 3, 5), taka sama w Linearze i w testach."""
    E = zasady["etykiety"]
    sekcja = item.get("sekcja")
    niska = item.get("pewnosc") == "niska" or bool(powody_flag(item, zasady))
    labels = []
    if sekcja == 1 or sekcja == 3:
        labels.append(TYP_DO_ETYKIETY.get(item.get("typ", ""), "Zadanie") if sekcja == 1 else E["produkt"])
        p = przypisz(item, zasady, karta, wielu)
        if item.get("konflikt_z_zakazem"):
            labels.append(E["zablokowane"])
        if p["komu"] == "czlowiek":
            labels.append(E["czlowiek"])
        elif p["komu"] == "agent":
            labels.append(E["agent"])
        if sekcja == 3 and wielu:
            labels.append(E["wielu_klientow"])
        if p["komu"] == "weryfikacja" or niska:
            labels.append(E["weryfikacja"])
    elif sekcja == 2:
        labels.append(E["czeka"])
        if niska:
            labels.append(E["weryfikacja"])
    elif sekcja == 5:
        labels.append(E["ryzyko"])
        if niska:
            labels.append(E["weryfikacja"])
    return labels


def powody_tekst(przyp):
    return [p["powod"] for p in przyp.get("powody", [])]


def repo_pozycji(item, zasady):
    """Repo pozycji po zastosowaniu mapowania (repo_mapowanie): np. rinvo-ops + zmiana_konfiguracji → rinvo-app.
    Zwraca nazwę repo albo None (brak / nieznane)."""
    repo = item.get("repo")
    for r in zasady.get("repo_mapowanie", {}).get("reguly", []):
        if repo == r["z"] and item.get("typ") in r["typy"]:
            repo = r["na"]
            break
    return repo if repo in zasady.get("repo_etykiety", {}) else None


def etykieta_repo(item, zasady):
    """Etykieta Lineara „repo: …” dla pozycji (albo None)."""
    repo = repo_pozycji(item, zasady)
    return zasady["repo_etykiety"][repo] if repo else None


def zakazy_wg_tematu(item, karta, zasady_json):
    """Zakazy klienta podzielone na (powiązane z tą częścią konfiguracji, pozostałe); kolejność w grupach jak w karcie.
    Powiązanie: słowa kluczowe tematów z ops/zasady.json (tematy_konfiguracji) w zgłoszeniu i w zakazie."""
    tematy = {k: v for k, v in zasady_json.get("tematy_konfiguracji", {}).items() if not k.startswith("_")}
    tekst = " ".join([str(item.get("tytul", "")), str(item.get("cel", "")), str(item.get("opis", ""))]
                     + [str(k) for k in item.get("kryteria_akceptacji", [])]).lower()
    aktywne = [t for t, v in tematy.items() if any(w in tekst for w in v["zgloszenie"])]
    powiazane, pozostale = [], []
    for zk in (karta or {}).get("zakazy", []):
        t = zk.get("tytul", "").lower()          # tylko tytuł: opisy są długie i łapią przypadkowe słowa
        if any(w in t for a in aktywne for w in tematy[a]["zakaz"]):
            powiazane.append(zk)
        else:
            pozostale.append(zk)
    return powiazane, pozostale
