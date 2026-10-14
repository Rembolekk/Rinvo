#!/usr/bin/env python3
"""podsumowanie.py – codzienne podsumowanie dla ludzi (jedna wiadomość na Slacku).

Użycie:
  python3 podsumowanie.py              # tylko w oknie 8:00–12:00 czasu polskiego i raz dziennie
  python3 podsumowanie.py --wymus      # niezależnie od godziny i od tego, czy dziś już wysłano
  python3 podsumowanie.py --sucho      # pokaż wiadomość, nic nie wysyłaj i nie zapisuj

Wiadomość (Block Kit) jest do przeczytania w 10 sekund: zdanie „Dziś potrzebujemy Cię w N sprawach”,
sekcja „Wymaga człowieka” (max 5 linijek: tytuł jako link, klient, jedno słowo powodu), „Uwaga” (powtarzające się
ryzyka i sprawy po terminie, tylko jeśli są), linijka o agentach, linijka o czekaniu na klientów i link do widoku
wszystkich otwartych zgłoszeń w Linearze. Bez list „nowe od wczoraj” i bez technicznych nazw w tekście.

PRZYPOMNIENIA: gdy termin sprawy czekającej minął, limit przypomnień z rozmowy nie jest wyczerpany
i klient nie prosił o brak przypomnień, podsumowanie przygotowuje SZKIC przypomnienia w komentarzu
zgłoszenia i podaje go na Slacku. NIGDY nie wysyła nic do klienta. Każdy szkic liczy się w karcie jako
wykorzystane przypomnienie, więc limit nie zostanie przekroczony.

Strefa czasowa: cron GitHuba działa w UTC, więc workflow odpala skrypt o 06:00 i 07:00 UTC, a skrypt
sam sprawdza czas w Europe/Warsaw (lato/zima) i wysyła raz dziennie.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import slack_widok as sw
import zasady
from maile import slack_bezpiecznie
from sekrety import wyczysc_srodowisko

STAN_PATH = Path("ops/.podsumowanie.json")
KLIENCI_DIR = Path("ops/klienci")
DNI = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
LIMIT_POZYCJI = 5


# ── czas: strefa polska ───────────────────────────────────────────────────────

def _ostatnia_niedziela(rok, miesiac):
    d = date(rok, miesiac, 31 if miesiac in (3, 10) else 30)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def czas_polski(teraz_utc):
    """UTC → czas w Polsce (CET/CEST). Używa zoneinfo, a bez bazy stref liczy regułę UE ręcznie
    (czas letni od ostatniej niedzieli marca 01:00 UTC do ostatniej niedzieli października 01:00 UTC)."""
    if teraz_utc.tzinfo is None:
        teraz_utc = teraz_utc.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return teraz_utc.astimezone(ZoneInfo("Europe/Warsaw"))
    except Exception:  # noqa: BLE001  (brak bazy stref)
        r = teraz_utc.year
        start = datetime.combine(_ostatnia_niedziela(r, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
        koniec = datetime.combine(_ostatnia_niedziela(r, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
        offset = 2 if start <= teraz_utc < koniec else 1
        return teraz_utc.astimezone(timezone(timedelta(hours=offset)))


def czy_pora(teraz_utc, stan, Z, wymus=False):
    """Wysyłamy w oknie od godziny podsumowania (domyślnie 8:00 czasu polskiego) do 12:00 i tylko raz dziennie.
    Okno (a nie dokładna godzina) znosi opóźnienia crona GitHuba i podwójny cron na zmianę czasu."""
    if wymus:
        return True
    lokalny = czas_polski(teraz_utc)
    godzina = Z.get("podsumowanie", {}).get("godzina", 8)
    return godzina <= lokalny.hour < 12 and stan.get("ostatnie_wyslane") != lokalny.date().isoformat()


# ── dane z Lineara ────────────────────────────────────────────────────────────

_POLA = "id identifier url title createdAt dueDate state { name type } labels { nodes { name } }"


def _pobierz(api_key, filtr):
    import linear_sync
    wynik, po = [], None
    while True:
        kursor = f', after: "{po}"' if po else ""
        q = (f"query {{ issues(first: 100{kursor}, filter: {{ team: {{ key: {{ eq: \"{linear_sync.TEAM_KEY}\" }} }}, "
             f"{filtr} }}) {{ nodes {{ {_POLA} }} pageInfo {{ hasNextPage endCursor }} }} }}")
        dane = linear_sync.gql(api_key, q).get("issues", {})
        wynik += dane.get("nodes", [])
        info = dane.get("pageInfo", {})
        if not info.get("hasNextPage"):
            return wynik
        po = info.get("endCursor")


def pobierz_zgloszenia(api_key, teraz_utc, okno_h):
    """(otwarte, skończone_przez_agentów_w_oknie)."""
    otwarte = _pobierz(api_key, 'state: { type: { nin: ["completed", "canceled"] } }')
    od = (teraz_utc - timedelta(hours=okno_h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    skonczone = _pobierz(api_key, f'state: {{ type: {{ eq: "completed" }} }}, completedAt: {{ gte: "{od}" }}, '
                                  f'labels: {{ name: {{ eq: "Dla agenta" }} }}')
    return otwarte, skonczone


# ── logika (bez sieci) ────────────────────────────────────────────────────────

def klient_z_tytulu(tytul):
    m = re.match(r"^\[([^\]]+)\]\s*", tytul or "")
    return m.group(1) if m else None


def _etykiety(z):
    return {l["name"] for l in (z.get("labels") or {}).get("nodes", [])}


def _data(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def _tytul_bez_prefiksu(z):
    return re.sub(r"^\[[^\]]+\]\s*", "", z.get("title", ""))


def szukaj_sprawy(karty, identyfikator):
    """(klient, klucz, wpis) z kart po identyfikatorze zgłoszenia (RIN-49)."""
    for klient, karta in karty.items():
        for klucz, wpis in karta.get("otwarte_sprawy", {}).items():
            if isinstance(wpis, dict) and wpis.get("identifier") == identyfikator:
                return klient, klucz, wpis
    return None, None, None


def imie_kontaktu(karta):
    for k in (karta or {}).get("kontakty", []):
        if k.get("potwierdzony", True) is not False and k.get("imie"):
            return k["imie"].split()[0]
    return ""


def szkic_przypomnienia(zgloszenie, termin, karta, Z):
    """Szkic z szablonu w ops/zasady.json. Niczego nie wysyła."""
    t = Z["przypomnienia"]["szablon"].format(
        imie=imie_kontaktu(karta), tytul=_tytul_bez_prefiksu(zgloszenie),
        termin=termin.strftime("%d.%m.%Y"))
    return re.sub(r"Cześć ,", "Cześć,", t)


def przypomnienie_stan(wpis, klucz, karta, Z):
    """Stan przypomnień sprawy z karty; dla starszych wpisów liczony z zakazów i limitu domyślnego."""
    if isinstance(wpis.get("przypomnienie"), dict):
        return wpis["przypomnienie"]
    import linear_sync
    return linear_sync.przypomnienie_z_pozycji({"klucz_sprawy": klucz, "przypomnienie": {}}, Z, karta)


def zbierz(otwarte, nowe, karty, Z, dzis):
    """Struktura podsumowania per klient + lista szkiców przypomnień do przygotowania."""
    E = Z["etykiety"]
    klienci = {k: {"nowe": [], "agent": [], "czlowiek": [], "weryfikacja": [], "czeka": [], "po_terminie": [],
                   "ryzyka": [], "szkice": []} for k in karty}
    for z in nowe:
        k = klient_z_tytulu(z.get("title"))
        if k in klienci:
            klienci[k]["nowe"].append(z)
    for z in otwarte:
        k = klient_z_tytulu(z.get("title"))
        if k not in klienci:
            continue
        et, d = _etykiety(z), klienci[k]
        if E["agent"] in et:
            d["agent"].append(z)
        if E["czlowiek"] in et:
            d["czlowiek"].append(z)
        if E["weryfikacja"] in et:
            d["weryfikacja"].append(z)
        if "Powtarzające się ryzyko" in et:
            d["ryzyka"].append(z)
        if E["czeka"] in et:
            termin = _data(z.get("dueDate"))
            if termin and termin < dzis:
                d["po_terminie"].append(z)
            else:
                d["czeka"].append(z)
            if termin and termin < dzis:
                _, klucz, wpis = szukaj_sprawy({k: karty[k]}, z.get("identifier"))
                if wpis is not None:
                    st = przypomnienie_stan(wpis, klucz, karty[k], Z)
                    if not st.get("nie_przypominac") and st.get("wykorzystane", 0) < st.get("limit", 0):
                        d["szkice"].append({"zgloszenie": z, "klucz": klucz, "termin": termin,
                                            "tekst": szkic_przypomnienia(z, termin, karty[k], Z)})
    return klienci


# ── wiadomość: do przeczytania w 10 sekund ────────────────────────────────────

KOLEJNOSC_POWODOW = ["zakaz", "pieniądze", "decyzja", "klient", "weryfikacja"]


def przygotuj(otwarte, skonczone, karty, Z, dzis):
    """Dane do wiadomości (jedna lista dla wszystkich klientów, bez powtórzeń)."""
    klienci = zbierz(otwarte, [], karty, Z, dzis)
    widziane, human, uwaga, szkice = set(), [], [], []

    def wpis_i_powod(klient, z):
        _, _, wpis = szukaj_sprawy({klient: karty[klient]}, z.get("identifier"))
        return sw.slowo_powodu((wpis or {}).get("przypisanie"), _etykiety(z), Z)

    for klient, d in klienci.items():
        for z in d["czlowiek"] + d["weryfikacja"]:
            if z["identifier"] in widziane:
                continue
            widziane.add(z["identifier"])
            human.append({"z": z, "klient": klient, "powod": wpis_i_powod(klient, z)})
        for sz in d["szkice"]:
            z = sz["zgloszenie"]
            widziane.add(z["identifier"])
            human.append({"z": z, "klient": klient, "powod": "klient", "przypomnienie": True})
            szkice.append({**sz, "klient": klient})
    human.sort(key=lambda h: (KOLEJNOSC_POWODOW.index(h["powod"]) if h["powod"] in KOLEJNOSC_POWODOW else 9,
                              h["z"]["identifier"]))

    for klient, d in klienci.items():
        for z in d["ryzyka"]:
            if z["identifier"] not in widziane:
                widziane.add(z["identifier"])
                uwaga.append({"z": z, "klient": klient, "powod": "ryzyko"})
        for z in d["po_terminie"]:
            if z["identifier"] not in widziane:
                widziane.add(z["identifier"])
                uwaga.append({"z": z, "klient": klient, "powod": "po terminie",
                              "termin": _data(z.get("dueDate"))})

    agenci = {z["identifier"] for d in klienci.values() for z in d["agent"]}
    czeka = [(klient, z) for klient, d in klienci.items() for z in d["czeka"] + d["po_terminie"]]
    przyszle = sorted(((_data(z.get("dueDate")), klient, z) for klient, z in czeka
                       if _data(z.get("dueDate")) and _data(z["dueDate"]) >= dzis), key=lambda x: (x[0], x[2]["identifier"]))
    return {
        "human": human, "uwaga": uwaga, "szkice": szkice,
        "agenci_otwarte": len(agenci), "agenci_skonczone": len({z["identifier"] for z in skonczone}),
        "czeka_n": len(czeka), "czeka_najblizsze": przyszle[0] if przyszle else None,
        "widok": sw.widok_linear_url([z.get("url") for z in otwarte]),
    }


def buduj_wiadomosc(dane, dzis):
    """(tekst, bloki) wiadomości Slack."""
    n = len(dane["human"])
    sekcje = []
    if n == 0:
        sekcje.append("*Dziś nic nie wymaga człowieka.*")
    else:
        sekcje.append(f"*Dziś potrzebujemy Cię w {n} {'sprawie' if n == 1 else 'sprawach'}*")
        linie = [sw.linia_pozycji(h["z"].get("url"), h["z"].get("title"), h["klient"], h["powod"])
                 for h in dane["human"]]
        sekcje.append("*Wymaga człowieka*\n" + "\n".join(sw.ogranicz(linie)))
    if dane["uwaga"]:
        linie = []
        for u in dane["uwaga"]:
            dod = f"termin {u['termin'].strftime('%d.%m')}" if u.get("termin") else None
            linie.append(sw.linia_pozycji(u["z"].get("url"), u["z"].get("title"), u["klient"], u["powod"], dod))
        sekcje.append("*Uwaga*\n" + "\n".join(sw.ogranicz(linie)))
    for sz in dane["szkice"]:
        tresc = "\n".join("> " + slack_bezpiecznie(l, 200) for l in sz["tekst"].splitlines() if l.strip())
        sekcje.append(f"*Szkic przypomnienia* (do wysłania przez człowieka, pełny w komentarzu): "
                      f"{sw.link(sz['zgloszenie'].get('url'), sz['zgloszenie'].get('title'))}\n{tresc}")

    x, y, z = dane["agenci_otwarte"], dane["agenci_skonczone"], dane["czeka_n"]
    linia_agentow = (f"Agenci pracują nad {x} {sw.forma(x, 'zadaniem', 'zadaniami', 'zadaniami')}, "
                     f"{y} {sw.forma(y, 'skończone', 'skończone', 'skończonych')} od wczoraj.")
    if z == 0:
        linia_czekania = "Nie czekamy teraz na żadnego klienta."
    else:
        naj = dane["czeka_najblizsze"]
        termin = (f"najbliższy termin: {naj[0].strftime('%d.%m')}, {sw.link(naj[2].get('url'), naj[2].get('title'), 45)}"
                  if naj else "najbliższy termin: brak")
        linia_czekania = f"Czekamy na klientów w {z} {'sprawie' if z == 1 else 'sprawach'}, {termin}."
    sekcje.append(linia_agentow + "\n" + linia_czekania)
    if dane["widok"]:
        sekcje.append(f"<{dane['widok']}|Wszystkie otwarte zgłoszenia w Linearze>")
    kontekst = f"{DNI[dzis.weekday()]} {dzis.strftime('%d.%m.%Y')}"
    return sw.tekst_zapasowy(sekcje, kontekst), sw.bloki(sekcje, kontekst)


# ── główny przebieg ───────────────────────────────────────────────────────────

def wczytaj_karty(katalog=KLIENCI_DIR):
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(katalog).glob("*/karta.json"))}


def wczytaj_stan(path=STAN_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}


def zapisz_stan(stan, path=STAN_PATH):
    Path(path).write_text(json.dumps(stan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def zapisz_szkice(api_key, klienci, karty, dzis_str):
    """Szkic jako komentarz w zgłoszeniu + licznik wykorzystanych przypomnień w karcie."""
    import linear_sync
    zmienione = set()
    for klient, d in klienci.items():
        for s in d["szkice"]:
            tresc = ("**Szkic przypomnienia dla klienta** (przygotowany automatycznie, niczego nie wysłano; "
                     "człowiek wysyła):\n\n" + "\n".join(f"> {l}" for l in s["tekst"].splitlines()))
            linear_sync.gql(api_key, linear_sync.M_ADD_COMMENT, {"issueId": s["zgloszenie"]["id"], "body": tresc})
            wpis = karty[klient]["otwarte_sprawy"][s["klucz"]]
            st = wpis.setdefault("przypomnienie", przypomnienie_stan(wpis, s["klucz"], karty[klient],
                                                                     zasady.wczytaj_zasady()))
            st["wykorzystane"] = st.get("wykorzystane", 0) + 1
            st["ostatni_szkic"] = dzis_str
            zmienione.add(klient)
    return zmienione


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Codzienne podsumowanie na Slacka.")
    ap.add_argument("--wymus", action="store_true", help="pomiń kontrolę godziny i „raz dziennie”")
    ap.add_argument("--sucho", action="store_true", help="tylko pokaż; bez Slacka, komentarzy i zapisów")
    args = ap.parse_args()

    from przetworz import load_env, send_slack
    import linear_sync
    load_env()
    wyczysc_srodowisko()

    Z = zasady.wczytaj_zasady()
    stan = wczytaj_stan()
    teraz = datetime.now(timezone.utc)
    if not czy_pora(teraz, stan, Z, args.wymus):
        print(f"Pominięto: poza oknem {Z['podsumowanie']['godzina']}:00–12:00 czasu polskiego albo już wysłano dziś "
              f"(teraz w Polsce: {czas_polski(teraz).strftime('%Y-%m-%d %H:%M')}).")
        return

    api_key = linear_sync.load_api_key()
    karty = wczytaj_karty()
    dzis = czas_polski(teraz).date()
    otwarte, skonczone = pobierz_zgloszenia(api_key, teraz, Z["podsumowanie"].get("okno_nowych_godzin", 26))
    klienci = zbierz(otwarte, [], karty, Z, dzis)
    tekst, bloki = buduj_wiadomosc(przygotuj(otwarte, skonczone, karty, Z, dzis), dzis)
    print(tekst)

    if args.sucho:
        return
    zmienione = zapisz_szkice(api_key, klienci, karty, dzis.isoformat())
    for klient in zmienione:
        linear_sync.save_karta(klient, karty[klient])
    ok, blad = send_slack(tekst, blocks=bloki)
    if not ok:
        print(f"BŁĄD Slack: {blad}", file=sys.stderr)
        sys.exit(1)
    stan["ostatnie_wyslane"] = czas_polski(teraz).date().isoformat()
    zapisz_stan(stan)
    print("Slack: wysłano.")


if __name__ == "__main__":
    main()
