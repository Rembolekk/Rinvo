#!/usr/bin/env python3
"""notatki.py – jedna notatka przed spotkaniem zamiast zadania na każde ryzyko.

Reguła (ops/zasady.json, sekcja notatki): agent dostaje JEDNO zadanie na każde zaplanowane spotkanie
z klientem; zawiera wszystkie ryzyka i otwarte tematy tego klienta. Gdy spotkania nie ma, jedno zadanie
na klienta (o ile klient ma ryzyka). Opis zadania odświeża się przy każdej zmianie; dawne zadania
„przygotowanie-ryzyko-…” są scalane: jedno przekształcane w notatkę, reszta archiwizowana z komentarzem,
gdzie przeniesiono treść.

Funkcje czyste (zbierz_zadania, opis_pakietu) nie dotykają sieci; synchronizuj_notatki dostaje moduł
linear_sync jako argument (unikamy importu cyklicznego).
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import daty as dw

PREFIKS = "notatka-"
STARE_PREFIKSY = ("przygotowanie-",)


def najnowsze_pozycje(klient, katalog=Path("wyniki")):
    """klucz_sprawy → (pozycja, zrodlo) z najnowszego wyniku klienta (data spotkania, potem nazwa folderu)."""
    wyniki = []
    for f in sorted((Path(katalog) / klient).glob("*/wynik.json")):
        w = json.loads(f.read_text(encoding="utf-8"))
        wyniki.append(((w.get("spotkanie", {}).get("data", ""), f.parent.name), w))
    najnowsze = {}
    for _, w in sorted(wyniki, key=lambda x: x[0]):
        for p in w.get("pozycje", []):
            if p.get("sekcja") in (1, 2, 3, 5) and p.get("klucz_sprawy"):
                najnowsze[p["klucz_sprawy"]] = (p, w.get("zrodlo", ""))
    return najnowsze


def data_spotkania(item, dzis):
    """Data zaplanowanego spotkania: z terminu pozycji, a gdy go brak, z jawnej daty w tytule lub opisie."""
    termin = str(item.get("termin", ""))
    m = re.search(r"\d{4}-\d{2}-\d{2}", termin)
    if m:
        return date.fromisoformat(m.group())
    return dw.znajdz_date(f"{item.get('tytul', '')} {item.get('opis', '')}", dzis)


def _status_tematu(item, wpis):
    if item.get("sekcja") == 2:
        return "czeka na klienta"
    komu = (wpis.get("przypisanie") or {}).get("komu")
    return {"agent": "u agenta", "czlowiek": "wymaga człowieka", "weryfikacja": "do weryfikacji"}.get(komu, "otwarte")


def _link(tytul, url):
    return f"[{tytul}]({url})" if url else tytul


def opis_pakietu(spotkanie, ryzyka, tematy, max_cytat=160):
    """Markdown: spotkanie, wszystkie ryzyka (z cytatem) i wszystkie otwarte tematy (ze statusem i terminem).
    Bloki są oddzielone pustymi liniami, żeby listy renderowały się poprawnie."""
    bloki = []
    if spotkanie:
        bloki.append(f"**Spotkanie:** {_link(spotkanie['tytul'], spotkanie.get('url'))}, "
                     f"{spotkanie['data'].strftime('%d.%m.%Y')}")
    linie = [f"**Ryzyka ({len(ryzyka)}):**", ""]
    for r in ryzyka:
        cyt = (r.get("cytat") or "").strip()
        cyt = cyt if len(cyt) <= max_cytat else cyt[: max_cytat - 1].rstrip() + "…"
        linie.append(f"- {_link(r['tytul'], r.get('url'))}" + (f": „{cyt}”" if cyt else ""))
    if not ryzyka:
        linie.append("- (brak)")
    bloki.append("\n".join(linie))
    linie = [f"**Otwarte tematy ({len(tematy)}):**", ""]
    for t in tematy:
        dod = f", termin {t['termin'].strftime('%d.%m')}" if t.get("termin") else ""
        linie.append(f"- {_link(t['tytul'], t.get('url'))} ({t['status']}{dod})")
    if not tematy:
        linie.append("- (brak)")
    bloki.append("\n".join(linie))
    return "\n\n".join(bloki)


def zbierz_zadania(klient, karta, najnowsze, Z, dzis):
    """Zadania notatek klienta: [{"klucz", "tytul", "item"}]. Jedno na zaplanowane spotkanie; bez spotkania
    jedno na klienta, o ile są ryzyka."""
    N = Z["notatki"]
    otwarte = karta.get("otwarte_sprawy", {})
    ryzyka, spotkania, tematy = [], [], []
    for klucz, wpis in otwarte.items():
        if not isinstance(wpis, dict) or klucz.startswith((PREFIKS,) + STARE_PREFIKSY) or klucz not in najnowsze:
            continue
        item, _ = najnowsze[klucz]
        if item.get("sekcja") == 5:
            ryzyka.append({"tytul": item.get("tytul", ""), "url": wpis.get("url"),
                           "cytat": (item.get("cytat") or [""])[0]})
        elif (item.get("typ") == "spotkanie" and item.get("sekcja") in (1, 2) and
              not any(w.lower() in f"{item.get('tytul', '')} {item.get('opis', '')}".lower()
                      for w in N.get("pomijaj_spotkania_slowa", []))):
            d = data_spotkania(item, dzis)
            if d and d >= dzis:
                # nazwa spotkania z tytułu zgłoszenia w karcie (np. „Potwierdzenie spotkania…”), a nie z tytułu
                # ostatniej czynności („Wysłać zaproszenie…”)
                spotkania.append({"klucz": klucz, "tytul": wpis.get("tytul") or item.get("tytul", ""),
                                  "url": wpis.get("url"), "data": d})
        elif item.get("sekcja") in (1, 2, 3):
            termin = None
            m = re.search(r"\d{4}-\d{2}-\d{2}", str(item.get("termin", "")))
            if m:
                termin = date.fromisoformat(m.group())
            tematy.append({"tytul": item.get("tytul", ""), "url": wpis.get("url"),
                           "status": _status_tematu(item, wpis), "termin": termin})
    if not ryzyka and not spotkania:
        return []

    def zadanie(klucz, tytul, cel, spotkanie, termin):
        pakiet = opis_pakietu(spotkanie, ryzyka, tematy, N.get("max_cytat", 160))
        item = {
            "sekcja": 1, "typ": "zobowiazanie_nasze", "przygotowawcze": True, "klucz_sprawy": klucz,
            "tytul": tytul, "cel": cel, "opis": pakiet, "wlasciciel": "", "warunek": "brak",
            "termin": termin.isoformat() if termin else "brak", "pewnosc": "wysoka", "cytat": [],
            "kryteria_akceptacji": list(N["kryteria_akceptacji"]), "jak_sprawdzic": N["jak_sprawdzic"],
            "repo": N["repo"], "konflikt_z_zakazem": None,
        }
        return {"klucz": klucz, "tytul": tytul, "item": item, "termin": termin}

    if spotkania:
        return [zadanie(PREFIKS + s["klucz"], N["spotkanie"]["tytul"].format(spotkanie=s["tytul"]),
                        N["spotkanie"]["cel"].format(spotkanie=s["tytul"], data=s["data"].strftime("%d.%m.%Y")),
                        s, s["data"])
                for s in sorted(spotkania, key=lambda s: (s["data"], s["klucz"]))]
    return [zadanie(PREFIKS + klient, N["klient"]["tytul"], N["klient"]["cel"], None, None)]


M_ARCHIWUM = "mutation($id: String!) { issueArchive(id: $id) { success } }"


def _hash(tytul, opis):
    return hashlib.sha256(f"{tytul}\n{opis}".encode("utf-8")).hexdigest()[:16]


def synchronizuj_notatki(ls, api_key, team_id, karta, klient, najnowsze, Z, label_map, todo_id, state_ids,
                         source, meeting_date, dzis, dry_run=False):
    """Tworzy/odświeża zadania notatek w Linearze i scala dawne zadania na ryzyka. Zwraca listę zdarzeń (tekst)."""
    import zasady
    zdarzenia = []
    zadania = zbierz_zadania(klient, karta, najnowsze, Z, dzis)
    otwarte = karta.setdefault("otwarte_sprawy", {})
    docelowe = {z["klucz"] for z in zadania}
    stare = [k for k in list(otwarte) if k.startswith(STARE_PREFIKSY) or (k.startswith(PREFIKS) and k not in docelowe)]

    def opis(z):
        return ls.build_description(z["item"], source, karta, zasady.przypisz(z["item"], Z, karta), Z)

    pierwszy_klucz = zadania[0]["klucz"] if zadania else None
    cele = {}                                   # klucz notatki → wpis (też w podglądzie, gdzie nic nie zapisujemy)
    for z in zadania:
        tresc = opis(z)
        h = _hash(f"[{klient}] {z['tytul']}", tresc)
        wpis = otwarte.get(z["klucz"])
        if wpis is None and stare:                               # przekształć dawne zadanie w notatkę
            stary_klucz = stare.pop(0)
            wpis = otwarte.pop(stary_klucz)
            zdarzenia.append(f"↪ {wpis.get('identifier')} ({stary_klucz}) przekształcone w {z['klucz']}")
            if not dry_run:
                otwarte[z["klucz"]] = wpis
                wpis["opis_hash"] = None
        if wpis is not None:
            cele[z["klucz"]] = wpis
        if wpis is None:
            zdarzenia.append(f"+ nowe zadanie {z['klucz']}")
            cele[z["klucz"]] = {"identifier": "(nowe zadanie)", "url": ""}
            if dry_run:
                continue
            wejscie = {"teamId": team_id, "title": f"[{klient}] {z['tytul']}", "description": tresc,
                       "stateId": todo_id,
                       "labelIds": [label_map[n] for n in (Z["etykiety"]["agent"], "Zadanie") if n in label_map]}
            if z["termin"]:
                wejscie["dueDate"] = z["termin"].isoformat()
            issue = ((ls.gql(api_key, ls.M_CREATE_ISSUE, {"input": wejscie}).get("issueCreate") or {}).get("issue"))
            if not issue:
                zdarzenia.append(f"⚠ nie udało się utworzyć {z['klucz']}")
                continue
            otwarte[z["klucz"]] = {
                "linear_id": issue["id"], "identifier": issue["identifier"], "url": issue["url"],
                "tytul": z["tytul"], "zrodla": [source], "data_spotkania": meeting_date, "opis_hash": h,
                "przypisanie": {"komu": "agent", "powody": [], "reguly": []}}
            cele[z["klucz"]] = otwarte[z["klucz"]]
            zdarzenia.append(f"✓ {issue['identifier']} ({z['klucz']}): {z['tytul'][:50]}")
        elif wpis.get("opis_hash") != h:
            zdarzenia.append(f"↻ {wpis.get('identifier')} ({z['klucz']}): odświeżony opis notatki")
            if dry_run:
                continue
            wejscie = {"title": f"[{klient}] {z['tytul']}", "description": tresc}
            if z["termin"]:
                wejscie["dueDate"] = z["termin"].isoformat()
            ls.gql(api_key, ls.M_UPDATE_ISSUE, {"id": wpis["linear_id"], "input": wejscie})
            wpis["tytul"] = z["tytul"]
            wpis["opis_hash"] = h
            otwarte[z["klucz"]] = wpis

    # nadmiarowe: komentarz, gdzie przeniesiono treść, stan Anulowane i archiwizacja
    cel_wpis = cele.get(pierwszy_klucz) or (otwarte.get(pierwszy_klucz) if pierwszy_klucz else None)
    for klucz in stare:
        wpis = otwarte.get(klucz)
        if not isinstance(wpis, dict):
            continue
        if cel_wpis:
            gdzie = f"{cel_wpis.get('identifier')} ({cel_wpis.get('url', '')})"
            komentarz = (f"Treść tego zadania przeniesiono do {gdzie}. Zamiast osobnego zadania na każde ryzyko "
                         f"jest jedna notatka na spotkanie z klientem, ze wszystkimi ryzykami i otwartymi tematami.")
        else:
            komentarz = ("Zadanie nie jest już potrzebne: klient nie ma teraz ryzyk ani zaplanowanego spotkania, "
                         "więc nie ma czego przygotowywać.")
        zdarzenia.append(f"⊘ {wpis.get('identifier')} ({klucz}) zarchiwizowane → "
                         f"{cel_wpis.get('identifier') if cel_wpis else 'brak zastępnika'}")
        if dry_run:
            continue
        ls.gql(api_key, ls.M_ADD_COMMENT, {"issueId": wpis["linear_id"], "body": komentarz})
        if state_ids.get("anulowana"):
            ls.gql(api_key, ls.M_UPDATE_ISSUE, {"id": wpis["linear_id"], "input": {"stateId": state_ids["anulowana"]}})
        ls.gql(api_key, M_ARCHIWUM, {"id": wpis["linear_id"]})
        otwarte.pop(klucz, None)
        karta.setdefault("zamkniete_sprawy", {})[klucz] = {
            **wpis, "status_koncowy": "anulowana", "przeniesiono_do": pierwszy_klucz}
    return zdarzenia
