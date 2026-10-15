#!/usr/bin/env python3
"""widok.py – widok „Dla mnie dziś” w Linearze: tylko sprawy NA DZIŚ dla człowieka (bez produktu i bez spraw wstrzymanych do potwierdzenia karty).

Filtr: zespół RIN, stan nieskończony, etykieta Decyzja człowieka, Do weryfikacji albo Szkic gotowy, BEZ etykiet Produkt i Wstrzymane do potwierdzenia karty (ops/zasady.json → dla_czlowieka.widok).
Widok grupuje zgłoszenia po terminie (po terminie, dziś, później) i sortuje w grupie według priorytetu. Dokładną kolejność
„po terminie, termin dziś, reszta według priorytetu” liczy kod (dla_czlowieka.kolejnosc_dla_mnie) dla porannego podsumowania.
Idempotentne: jeśli widok o tej nazwie istnieje, zostaje (filtr jest aktualizowany); link zapisuje ops/widok_dla_mnie.json.

Użycie: python3 widok.py
"""

import json
import sys
from pathlib import Path

import linear_sync
import zasady

M_UTWORZ = """
mutation($input: CustomViewCreateInput!) {
  customViewCreate(input: $input) { success customView { id name slugId } }
}
"""
M_AKTUALIZUJ = """
mutation($id: String!, $input: CustomViewUpdateInput!) {
  customViewUpdate(id: $id, input: $input) { success customView { id name slugId } }
}
"""
M_PREFERENCJE = """
mutation($input: ViewPreferencesCreateInput!) {
  viewPreferencesCreate(input: $input) { success }
}
"""
PREFERENCJE = {"layout": "list", "issueGrouping": "dueDate", "viewOrdering": "priority", "viewOrderingDirection": "desc",
               "showCompletedIssues": "none"}


def filtr(Z):
    """filterData widoku (IssueFilter)."""
    W = Z["dla_czlowieka"]["widok"]
    return {"team": {"key": {"eq": linear_sync.TEAM_KEY}},
            "state": {"type": {"nin": ["completed", "canceled"]}},
            "and": [{"labels": {"name": {"in": list(W["etykiety"])}}},                          # szkice do wysłania, decyzje, weryfikacje, potwierdzenia kart
                    {"labels": {"every": {"name": {"nin": list(W.get("wyklucz_etykiety") or [])}}}}]}   # bez produktu (raz w tygodniu) i spraw wstrzymanych


def adres(url_key, slug_id, nazwa):
    return f"https://linear.app/{url_key}/view/{slug_id}"


def utworz_lub_zaktualizuj(api_key, Z, gql=None):
    """{"id","slugId","url","nazwa"} widoku. Najpierw szuka widoku po nazwie, żeby go nie dublować."""
    gql = gql or linear_sync.gql
    W = Z["dla_czlowieka"]["widok"]
    team = linear_sync.get_team(api_key) if gql is linear_sync.gql else {"id": "team"}
    org = gql(api_key, "query { organization { urlKey } }")["organization"]["urlKey"]
    istniejace = gql(api_key, "query { customViews(first: 100) { nodes { id name slugId } } }")["customViews"]["nodes"]
    widok = next((v for v in istniejace if v["name"] == W["nazwa"]), None)
    wejscie = {"filterData": filtr(Z), "description": "Tylko sprawy dla człowieka: po terminie, termin dziś, reszta według priorytetu."}
    if widok:
        gql(api_key, M_AKTUALIZUJ, {"id": widok["id"], "input": wejscie})
    else:
        r = gql(api_key, M_UTWORZ, {"input": {**wejscie, "name": W["nazwa"], "teamId": team["id"], "shared": True}})
        widok = r["customViewCreate"]["customView"]
        try:
            gql(api_key, M_PREFERENCJE, {"input": {"type": "organization", "viewType": "customView", "customViewId": widok["id"],
                                                   "preferences": PREFERENCJE}})
        except Exception as exc:  # noqa: BLE001  (preferencje to dodatek: widok działa i bez nich)
            print(f"Uwaga: preferencje widoku nie zapisane ({type(exc).__name__}).")
    wynik = {"id": widok["id"], "slugId": widok["slugId"], "nazwa": W["nazwa"], "url": adres(org, widok["slugId"], W["nazwa"])}
    return wynik


def zapisz(wynik, plik):
    Path(plik).parent.mkdir(parents=True, exist_ok=True)
    Path(plik).write_text(json.dumps(wynik, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wczytaj_url(Z, root="."):
    p = Path(root) / Z["dla_czlowieka"]["widok"]["plik"]
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("url")
    except (OSError, ValueError):
        return None


def main():
    from przetworz import load_env
    from sekrety import wyczysc_srodowisko
    load_env()
    wyczysc_srodowisko()
    Z = zasady.wczytaj_zasady()
    wynik = utworz_lub_zaktualizuj(linear_sync.load_api_key(), Z)
    zapisz(wynik, Z["dla_czlowieka"]["widok"]["plik"])
    print(f"Widok „{wynik['nazwa']}”: {wynik['url']}")


if __name__ == "__main__":
    main()
