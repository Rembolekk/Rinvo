#!/usr/bin/env python3
"""stan_linear.py – stan zgłoszeń z Lineara zapisany do pliku, żeby strony generowały się bez zapytań.

Plik ops/.stan_linear.json: {"zapisano": ISO, "zgloszenia": {"RIN-41": {...}}}. Odświeżają go linear_sync, agent,
podsumowanie i pozostałe skrypty na końcu przebiegu (stan_linear.po_przebiegu). generuj_strony.py tylko czyta ten plik.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PLIK = Path("ops/.stan_linear.json")

ZAPYTANIE = """
query($after: String) {
  issues(first: 100, after: $after, filter: { team: { key: { eq: "%s" } } }) {
    nodes { id identifier title url priority createdAt updatedAt completedAt dueDate
            state { name type } labels { nodes { name } } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def pobierz(api_key, gql, team_key="RIN"):
    """Wszystkie zgłoszenia zespołu (strony po 100) jako {identyfikator: dane}."""
    wynik, po = {}, None
    while True:
        dane = gql(api_key, ZAPYTANIE % team_key, {"after": po})["issues"]
        for n in dane["nodes"]:
            wynik[n["identifier"]] = {
                "id": n.get("id"), "tytul": n["title"], "url": n["url"], "stan": (n.get("state") or {}).get("name", ""),
                "typ_stanu": (n.get("state") or {}).get("type", ""),
                "etykiety": sorted(l["name"] for l in (n.get("labels") or {}).get("nodes", [])),
                "priorytet": n.get("priority"), "utworzono": n.get("createdAt"), "zmieniono": n.get("updatedAt"),
                "zamknieto": n.get("completedAt"), "termin": n.get("dueDate")}
        if not dane["pageInfo"]["hasNextPage"]:
            return wynik
        po = dane["pageInfo"]["endCursor"]


def zapisz(zgloszenia, plik=PLIK, teraz=None):
    teraz = teraz or datetime.now(timezone.utc)
    Path(plik).parent.mkdir(parents=True, exist_ok=True)
    Path(plik).write_text(json.dumps({"zapisano": teraz.isoformat(timespec="seconds"), "zgloszenia": zgloszenia},
                                     ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def wczytaj(plik=PLIK):
    p = Path(plik)
    if not p.exists():
        return {"zapisano": None, "zgloszenia": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def odswiez(api_key, gql, plik=PLIK):
    """Pobiera świeży stan, rejestruje zmiany człowieka od poprzedniej migawki (czlowiek.py) i zapisuje migawkę."""
    import czlowiek
    stare = wczytaj(plik)["zgloszenia"]
    zgl = pobierz(api_key, gql)
    zm = czlowiek.wykryj(stare, zgl, czlowiek.wczytaj_dotkniete())
    if zm:
        czlowiek.zarejestruj(zm)
        usuniete = {i for i, z in zm.items() if z.get("usuniete")}
        if usuniete:
            czlowiek.zastosuj_usuniete_do_kart(usuniete)
        print(f"Zmiany człowieka w Linearze: {', '.join(sorted(zm))}")
    czlowiek.wyczysc_dotkniete()
    zapisz(zgl, plik)
    return len(zgl)


def po_przebiegu():
    """Odświeża plik stanu na końcu przebiegu skryptu. Nigdy nie przerywa przebiegu: błąd tylko się wypisuje."""
    try:
        import linear_sync
        n = odswiez(linear_sync.load_api_key(), linear_sync.gql)
        print(f"Stan Lineara zapisany do {PLIK} ({n} zgłoszeń).")
    except BaseException as exc:  # noqa: BLE001  (także SystemExit z load_api_key)
        print(f"Uwaga: nie udało się zapisać stanu Lineara ({type(exc).__name__}); strony użyją poprzedniego stanu.")


if __name__ == "__main__":
    po_przebiegu()
