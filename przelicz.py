#!/usr/bin/env python3
"""przelicz.py – stosuje zasady AI-first (ops/zasady.json) do ISTNIEJĄCYCH zgłoszeń w Linearze.

Użycie:
  python3 przelicz.py                  # raport: kto zmieniłby przypisanie i dlaczego (nic nie zmienia)
  python3 przelicz.py --zastosuj       # przelicza etykiety i opisy w Linearze, dopisuje zadania przygotowawcze
  python3 przelicz.py --klient auto-tama

Dla każdej otwartej sprawy z karty bierze NAJNOWSZĄ pozycję z wyników (wyniki/<klient>/*/wynik.json),
liczy etykiety silnikiem zasady.py (tym samym co linear_sync.py), podmienia etykiety routingu
(Dla agenta, Decyzja człowieka, Do weryfikacji, Zablokowane przez zakaz, Wielu klientów), buduje opis w
stałym układzie i dodaje komentarz z powodem. Nie tworzy duplikatów: zgłoszenia są wiązane z kartą po
kluczu sprawy, a zadania przygotowawcze do ryzyk mają własny klucz (przygotowanie-<klucz>).
Zgłoszeń zamkniętych (Done/Cancelled) nie rusza.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import copy

import czlowiek
import dla_czlowieka
import linear_sync
import notatki
import zasady

ROUTING = ("agent", "czlowiek", "weryfikacja", "zablokowane", "wielu_klientow", "wstrzymane")


najnowsze_pozycje = notatki.najnowsze_pozycje


def stare_przypisanie(etykiety, Z):
    E = Z["etykiety"]
    if E["agent"] in etykiety:
        return "agent"
    if E["czlowiek"] in etykiety:
        return "czlowiek"
    return "brak"


def nowe_przypisanie_nazwa(przyp):
    return przyp["komu"]


def licz(klient, karta, Z, prosby, najnowsze, stan_linear):
    """Lista wierszy raportu (bez zapisu). stan_linear: identyfikator → {labels:[{id,name}], type, name}."""
    wiersze = []
    for klucz, wpis in karta.get("otwarte_sprawy", {}).items():
        if not isinstance(wpis, dict) or klucz not in najnowsze:
            continue
        item, zrodlo = najnowsze[klucz]
        st = stan_linear.get(wpis.get("identifier"))
        if st is None:
            continue
        obecne = {l["name"] for l in st["labels"]}
        sekcja = item.get("sekcja")
        if sekcja == 2 and Z["etykiety"]["czeka"] not in obecne:
            sekcja = 1                                # sprawa wznowiona: oceniamy jak zadanie do wykonania
        eff = dict(item, sekcja=sekcja)
        wielu = sekcja == 3 and zasady.wielu_klientow(prosby, Z, eff, klient)
        nowe_et = zasady.etykiety_pozycji(eff, Z, karta, wielu)
        przyp = zasady.przypisz(eff, Z, karta, wielu)
        routing = {Z["etykiety"][r] for r in ROUTING}
        repo_wszystkie = set(Z["repo_etykiety"].values())
        repo_et = zasady.etykieta_repo(eff, Z)
        wiersze.append({
            "klucz": klucz, "wpis": wpis, "item": eff, "zrodlo": zrodlo, "przyp": przyp, "wielu": wielu,
            "identifier": wpis.get("identifier"), "tytul": item.get("tytul", ""),
            "stare": stare_przypisanie(obecne, Z), "nowe": nowe_przypisanie_nazwa(przyp),
            "dodaj": sorted(((set(nowe_et) & routing) - obecne) | ({repo_et} - obecne if repo_et else set())),
            "usun": sorted(((obecne & routing) - set(nowe_et)) | ((obecne & repo_wszystkie) - {repo_et})),
            "powody": zasady.powody_tekst(przyp),
        })
        if czlowiek.etykiety_reczne(wpis.get("identifier")):      # człowiek zmienił etykiety: przeliczenie ich nie cofa
            wiersze[-1]["dodaj"], wiersze[-1]["usun"] = [], []
            wiersze[-1]["reczne_etykiety"] = True
    return wiersze


def raport(wiersze):
    zmienione = [w for w in wiersze if w["stare"] != w["nowe"] and not (w["stare"] == "brak" and w["nowe"] in ("czeka", "ryzyko"))]
    przejscia = Counter((w["stare"], w["nowe"]) for w in zmienione)
    print(f"\nPrzeliczono zgłoszeń: {len(wiersze)}; zmieniło przypisanie: {len(zmienione)}")
    for (a, b), n in sorted(przejscia.items()):
        print(f"  {a:>8} → {b:<11} {n}")
    print("\nSzczegóły zmian przypisania:")
    for w in sorted(zmienione, key=lambda x: (x["stare"], x["nowe"], x["identifier"])):
        powod = "; ".join(w["powody"]) or ("domyślnie agent" if w["nowe"] == "agent" else "")
        print(f"  {w['identifier']:7} {w['stare']:>8} → {w['nowe']:<11} {w['tytul'][:55]}\n"
              f"{'':9}powód: {powod}")
    zmiany_et = [w for w in wiersze if w["dodaj"] or w["usun"]]
    print(f"\nZgłoszeń z inną listą etykiet routingu: {len(zmiany_et)}")
    return zmienione


def zastosuj(api_key, klient, karta, Z, wiersze, team, label_map, todo_id, najnowsze):
    for w in wiersze:
        wpis, przyp, item = w["wpis"], w["przyp"], w["item"]
        linear_id = wpis["linear_id"]
        st = linear_sync.get_issue_state_and_labels(api_key, linear_id)
        ids = [l["id"] for l in st["labels"] if l["name"] not in w["usun"]]
        ids += [label_map[n] for n in w["dodaj"] if n in label_map and label_map[n] not in ids]
        opis = linear_sync.build_description(item, w["zrodlo"], karta, przyp, Z)
        # blok „Co masz zrobić” (w tym mail poprawiony przez człowieka) przeliczenie zachowuje; nowy układ dopisuje dla_czlowieka.przelicz
        stary = (linear_sync.gql(api_key, 'query { issue(id: "%s") { description } }' % linear_id).get("issue") or {}).get("description") or ""
        blok_zgloszenia = dla_czlowieka.rozdziel(stary)[0]
        if blok_zgloszenia:
            opis = dla_czlowieka.zloz_opis(blok_zgloszenia, opis)
        wejscie = {"labelIds": ids, "description": opis}
        if item.get("termin_modelu"):                 # kod poprawił termin: tytuł z błędną datą też
            wejscie["title"] = f"[{klient}] {item.get('tytul', '')}"
        linear_sync.gql(api_key, linear_sync.M_UPDATE_ISSUE, {"id": linear_id, "input": wejscie})
        stare_przyp = wpis.get("przypisanie", {})
        linear_sync.zapisz_przypisanie(wpis, item, Z, karta, w["wielu"])
        nowe_przyp = wpis["przypisanie"]
        if (stare_przyp.get("komu"), stare_przyp.get("powody")) != (nowe_przyp["komu"], nowe_przyp["powody"]):
            kom = linear_sync.komentarz_przypisania(przyp["komu"], zasady.powody_tekst(przyp),
                                                    przyp["wymaga_szkicu"])
            if kom:
                linear_sync.gql(api_key, linear_sync.M_ADD_COMMENT, {"issueId": linear_id, "body": kom})
        print(f"  ✓ {w['identifier']} ({w['klucz']}): {w['stare']} → {w['nowe']}")

    return None


def przelicz_terminy(api_key, klient, karta, najnowsze, zastosuj_zmiany):
    """Termin w Linearze = termin najnowszej pozycji (po przeliczeniu dat względnych przez kod).
    Zwraca listę zmian [(identyfikator, klucz, stary, nowy)]."""
    zmiany = []
    for klucz, wpis in karta.get("otwarte_sprawy", {}).items():
        if not isinstance(wpis, dict) or klucz not in najnowsze or not wpis.get("linear_id"):
            continue
        nowy = linear_sync.parse_due_date(najnowsze[klucz][0].get("termin"))
        if not nowy:
            continue
        stary = (linear_sync.gql(api_key, 'query { issue(id: "%s") { dueDate } }' % wpis["linear_id"])
                 .get("issue") or {}).get("dueDate")
        if stary != nowy:
            zmiany.append((wpis.get("identifier"), klucz, stary, nowy))
            if zastosuj_zmiany:
                linear_sync.gql(api_key, linear_sync.M_UPDATE_ISSUE,
                                {"id": wpis["linear_id"], "input": {"dueDate": nowy}})
    return zmiany


def raport_terminow(zmiany):
    print(f"\nTerminy w Linearze, które się zmieniają: {len(zmiany)}")
    for ident, klucz, stary, nowy in zmiany:
        print(f"  {ident:7} ({klucz}): {stary or 'brak'} → {nowy}")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Stosuje zasady AI-first do istniejących zgłoszeń.")
    ap.add_argument("--zastosuj", action="store_true", help="zmień Linear (bez tej flagi tylko raport)")
    ap.add_argument("--klient", help="tylko ten klient")
    args = ap.parse_args()

    from przetworz import load_env
    from sekrety import wyczysc_srodowisko
    load_env()
    wyczysc_srodowisko()

    Z = zasady.wczytaj_zasady()
    prosby = zasady.wczytaj_prosby()
    api_key = linear_sync.load_api_key()
    team = linear_sync.get_team(api_key)
    label_map = linear_sync.ensure_labels(api_key, team["id"])
    todo_id = linear_sync.find_state(linear_sync.get_workflow_states(api_key, team["id"]), "Todo", "unstarted")

    klienci = [args.klient] if args.klient else sorted(p.parent.name for p in Path("ops/klienci").glob("*/karta.json"))
    wszystkie = []
    for klient in klienci:
        karta = linear_sync.load_karta(klient)
        najnowsze = najnowsze_pozycje(klient)
        stan = {}
        for wpis in karta.get("otwarte_sprawy", {}).values():
            if isinstance(wpis, dict) and wpis.get("linear_id"):
                stan[wpis["identifier"]] = linear_sync.get_issue_state_and_labels(api_key, wpis["linear_id"])
        wiersze = licz(klient, karta, Z, prosby, najnowsze, stan)
        print(f"\n===== {klient} =====")
        wszystkie += raport(wiersze)
        zmiany_terminow = przelicz_terminy(api_key, klient, karta, najnowsze, args.zastosuj)
        raport_terminow(zmiany_terminow)
        stany = {"anulowana": linear_sync.find_state(
            linear_sync.get_workflow_states(api_key, team["id"]), "Cancelled", "cancelled")}
        zrodlo_notatek = max((v[1] for v in najnowsze.values()), default="")
        zdarzenia = notatki.synchronizuj_notatki(
            linear_sync, api_key, team["id"], karta if args.zastosuj else copy.deepcopy(karta), klient, najnowsze, Z,
            label_map, todo_id, stany, zrodlo_notatek, "", date.today(),
            dry_run=not args.zastosuj)
        print(f"\nNotatki przed spotkaniem ({'zmiany' if args.zastosuj else 'plan'}):")
        for z in zdarzenia or ["(bez zmian)"]:
            print(f"  {z}")
        if args.zastosuj:
            zastosuj(api_key, klient, karta, Z, wiersze, team, label_map, todo_id, najnowsze)
            linear_sync.save_karta(klient, karta)
            linear_sync.write_karta_md(klient, karta)
    if args.zastosuj:                                  # zgłoszenia dla człowieka: tytuł od czynności i blok na górze opisu
        import karta_klienta
        import wyslij
        srodowisko = wyslij.zbuduj_srodowisko()
        for klient in klienci:                         # nowy klient: JEDNO zgłoszenie „Potwierdź kartę klienta …”, reszta wstrzymana
            zg_karty = karta_klienta.zapewnij_zgloszenie(srodowisko, klient, srodowisko.wczytaj_karte(klient))
            if zg_karty:
                print(f"  ✓ {zg_karty['identifier']}: Potwierdź kartę klienta ({klient})")
        zmiany_ukladu = dla_czlowieka.przelicz(srodowisko, zastosuj=True)
        print(f"\nZgłoszenia dla człowieka przeliczone do nowego układu: {len(zmiany_ukladu)}")
    print(f"\nRAZEM zmieniło przypisanie: {len(wszystkie)}" + ("" if args.zastosuj else "  (raport; nic nie zmieniono)"))


if __name__ == "__main__":
    main()
