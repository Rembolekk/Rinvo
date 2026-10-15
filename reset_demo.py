#!/usr/bin/env python3
"""reset_demo.py – próba generalna od czystego stanu.

Użycie (bez --tak nic nie robi, tylko wypisuje plan):
  python3 reset_demo.py --tak [--app ../Rinvo-app] [--baza-app b2556d6] [--bez-linear] [--bez-app]

Co robi:
  Linear   – archiwizuje WSZYSTKIE zgłoszenia zespołu RIN. Etykiety i widok „Dla mnie dziś” zostają.
  Rinvo    – usuwa wygenerowany stan: wyniki/, materiały, maile, rejestry rozmów i maili, prosby.json, propozycje, sygnały, zdarzenia,
             stan Lineara, liczniki, logi przebiegów; strony generuje od nowa (puste).
             Transkrypcje auto-tama przenosi do proba/transkrypcje/auto-tama/ (poza ścieżką, która uruchamia workflow),
             transkrypcję kliniki do proba/archiwum/klinika-usmiech/ (w tej próbie nieużywana).
  Karty    – auto-tama zostaje tylko z konfiguracją spoza rozmów: nazwa, domena, kontakt Kasi (potwierdzony) i zakres jej decyzji.
             Karta kliniki jest usuwana.
  Rinvo-app – config i wiedza wracają do stanu sprzed poprawek agenta (commit na main + push), otwarte PR-y są zamykane
             (wymaga AGENT_GITHUB_TOKEN w środowisku; bez niego skrypt tylko wypisuje, które PR-y zamknąć ręcznie).
  Maile    – rejestr maili dostaje datę włączenia = dziś, żeby stare maile nie wróciły.
Tagi „przed-proba” w obu repozytoriach pozwalają wrócić do stanu sprzed resetu (git checkout przed-proba -- .).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

KLIENT_PROBY = "auto-tama"
KLIENCI_ARCHIWUM = ["klinika-usmiech"]
KATALOG_PROBY = Path("proba")

# wygenerowany stan do usunięcia (pliki i katalogi względem katalogu głównego repo)
USUWANE = [
    "wyniki", "ops/materialy", "ops/maile", "logi/przebiegi",
    "ops/.sygnaly.json", "ops/.zdarzenia.json", "ops/.stan_linear.json", "ops/.reczne_zmiany.json", "ops/.zmiany_automatu.json",
    "ops/.zuzycie_modelu.json", "ops/.kolejka_limit.json", "ops/.podsumowanie.json", "ops/.przetworzone.json", "ops/.maile.json",
    "ops/produkt/prosby.json", "ops/produkt/propozycje.json", "klienci",
]
POLA_KARTY_Z_KONFIGURACJI = ("klient", "nazwa", "domeny")
POLA_KONTAKTU = ("imie", "email", "rola", "zakres_decyzji", "potwierdzony", "status")


# ── Linear ────────────────────────────────────────────────────────────────────

def archiwizuj_zgloszenia(api_key, gql, team_key="RIN"):
    """Archiwizuje wszystkie (nie zarchiwizowane) zgłoszenia zespołu. Zwraca liczbę. Etykiety i widoki nie są ruszane."""
    ids, po = [], None
    while True:
        kursor = f', after: "{po}"' if po else ""
        q = ('query { issues(first: 100%s, filter: { team: { key: { eq: "%s" } } }) { nodes { id identifier } '
             'pageInfo { hasNextPage endCursor } } }' % (kursor, team_key))
        dane = gql(api_key, q)["issues"]
        ids += [(n["id"], n["identifier"]) for n in dane["nodes"]]
        if not dane["pageInfo"]["hasNextPage"]:
            break
        po = dane["pageInfo"]["endCursor"]
    for iid, _ in ids:
        gql(api_key, "mutation($id: String!) { issueArchive(id: $id) { success } }", {"id": iid})
    return len(ids)


# ── pliki Rinvo ───────────────────────────────────────────────────────────────

def karta_minimalna(karta):
    """Karta tylko z konfiguracji spoza rozmów: nazwa, domena, kontakt Kasi (potwierdzony) i zakres jej decyzji.
    Zakazy, otwarte i zamknięte sprawy, ryzyka, nieobecności, historia wysyłek i założenia demo znikają."""
    nowa = {k: karta[k] for k in POLA_KARTY_Z_KONFIGURACJI if k in karta}
    kontakt = next((k for k in karta.get("kontakty", []) if k.get("potwierdzony") is True), None)
    if kontakt:
        nowa["kontakty"] = [{k: kontakt[k] for k in POLA_KONTAKTU if k in kontakt}]
        nowa["decydenci"] = [{"imie": kontakt["imie"], "rola": kontakt.get("rola", "")}]
    nowa["zakazy"] = []
    nowa["otwarte_sprawy"] = {}
    return nowa


def usun(root, sciezka):
    p = Path(root) / sciezka
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    else:
        return False
    return True


def przenies_transkrypcje(root):
    """auto-tama → proba/transkrypcje/auto-tama/, klinika → proba/archiwum/<klient>/. Zwraca [(skąd, dokąd)]."""
    root = Path(root)
    ruchy = []
    for klient, cel_baza in [(KLIENT_PROBY, KATALOG_PROBY / "transkrypcje")] + [(k, KATALOG_PROBY / "archiwum") for k in KLIENCI_ARCHIWUM]:
        zrodlo = root / "ops/transkrypcje" / klient
        if not zrodlo.is_dir():
            continue
        cel = root / cel_baza / klient
        cel.mkdir(parents=True, exist_ok=True)
        for plik in sorted(zrodlo.glob("*.md")):
            shutil.move(str(plik), str(cel / plik.name))
            ruchy.append((str(plik.relative_to(root)), str((cel / plik.name).relative_to(root))))
        shutil.rmtree(zrodlo, ignore_errors=True)
    return ruchy


def reset_kart(root):
    """Karta auto-tama → minimalna; karty innych klientów (klinika) usunięte. Zwraca (zostawione, usuniete)."""
    root = Path(root)
    zostalo, usuniete = [], []
    for plik in sorted((root / "ops/klienci").glob("*/karta.json")):
        klient = plik.parent.name
        if klient == KLIENT_PROBY:
            plik.write_text(json.dumps(karta_minimalna(json.loads(plik.read_text(encoding="utf-8"))), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            zostalo.append(klient)
        else:
            shutil.rmtree(plik.parent)
            usuniete.append(klient)
    return zostalo, usuniete


def rejestr_maili_pusty(dzis):
    """Pusty rejestr maili z datą włączenia = dziś: maile sprzed dziś nie wrócą."""
    return {"przetworzone": {}, "nieznani": {}, "oczekujace": {}, "wlaczono": dzis.isoformat()}


def reset_stanu(root, dzis):
    """Usuwa wygenerowany stan i zapisuje puste rejestry. Zwraca listę usuniętych ścieżek."""
    root = Path(root)
    usuniete = [s for s in USUWANE if usun(root, s)]
    (root / "ops").mkdir(parents=True, exist_ok=True)
    (root / "ops/.maile.json").write_text(json.dumps(rejestr_maili_pusty(dzis), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "ops/.przetworzone.json").write_text("{}\n", encoding="utf-8")
    (root / "ops/produkt").mkdir(parents=True, exist_ok=True)
    (root / "ops/produkt/prosby.json").write_text("{}\n", encoding="utf-8")
    # sygnały: pusty stan (a nie brak pliku), żeby pierwsze sygnały z próby zostały OGŁOSZONE na Slacku, a nie wzięte za bazę
    (root / "ops/.sygnaly.json").write_text(json.dumps({"widziane": []}, indent=1) + "\n", encoding="utf-8")
    (root / "logi/przebiegi").mkdir(parents=True, exist_ok=True)
    (root / "logi/przebiegi/.gitkeep").write_text("", encoding="utf-8")
    return usuniete


# ── Rinvo-app ─────────────────────────────────────────────────────────────────

def _git(app, *args, sprawdz=True):
    r = subprocess.run(["git", *args], cwd=app, capture_output=True, text=True)
    if sprawdz and r.returncode != 0:
        raise RuntimeError(f"git {args[0]} nie powiódł się: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def sprawdz_baze(app, baza):
    """Baza ma być stanem SPRZED poprawek agenta: Toruń sobota do 14:00 i dzwonienie do 20:00."""
    tekst = _git(app, "show", f"{baza}:config/auto-tama.yaml")
    if 'sobota: {od: "09:00", do: "14:00"}' not in tekst or 'godziny_dzwonienia_do: "20:00"' not in tekst:
        raise RuntimeError(f"commit {baza} nie wygląda na stan sprzed poprawek agenta (Toruń sobota 14:00, dzwonienie do 20:00)")


def reset_app(app, baza, push=True, komunikat="Reset demo: config i wiedza sprzed poprawek agenta"):
    """Przywraca config/ i wiedza/ (oraz wszystko, co zmieniono po bazie) do stanu z commita bazowego. Commit na main + push.
    Zwraca {"zmienione": [...], "commit": sha albo None, "galezie": [...usuniete zdalne gałęzie agenta]}."""
    app = str(app)
    _git(app, "fetch", "-q", "origin")
    _git(app, "checkout", "-q", "main")
    _git(app, "pull", "-q", "--ff-only", "origin", "main")
    sprawdz_baze(app, baza)
    zmiany = [l.split("\t") for l in _git(app, "diff", "--name-status", baza, "HEAD").splitlines() if l.strip()]
    for status, *sciezki in zmiany:
        sciezka = sciezki[-1]
        if status.startswith("A"):
            _git(app, "rm", "-q", "-f", sciezka)
        else:
            _git(app, "checkout", baza, "--", sciezka)
    wynik = {"zmienione": [z[-1] for z in zmiany], "commit": None, "galezie": []}
    if _git(app, "status", "--porcelain"):
        _git(app, "-c", "user.name=Rinvo reset", "-c", "user.email=reset@rinvo.invalid", "commit", "-q", "-m",
             komunikat + "\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        wynik["commit"] = _git(app, "rev-parse", "--short", "HEAD")
        if push:
            _git(app, "push", "-q", "origin", "main")
    if push:
        # zdalne gałęzie agenta (rin-<numer>-…): PR-y są już zamknięte albo scalone (squash nie jest „merged” dla gita), więc usuwamy wszystkie
        for g in _git(app, "branch", "-r", "--list", "origin/rin-*").split():
            nazwa = g.replace("origin/", "", 1)
            if re.match(r"^rin-\d+-", nazwa) and subprocess.run(["git", "push", "-q", "origin", "--delete", nazwa], cwd=app, capture_output=True).returncode == 0:
                wynik["galezie"].append(nazwa)
    return wynik


def _otworz(req, timeout=30):
    """urlopen z certyfikatami certifi (python z macOS nie ma własnych)."""
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def otwarte_pr(repo, token=None, otworz=None):
    """Otwarte PR-y repozytorium (publiczne repo: bez tokenu też działa). [(numer, tytuł)]"""
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "rinvo-reset",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with (otworz or _otworz)(req, timeout=30) as r:
        return [(p["number"], p["title"]) for p in json.loads(r.read().decode("utf-8"))]


def zamknij_pr(repo, numer, token, otworz=None):
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/pulls/{numer}", method="PATCH",
                                 data=json.dumps({"state": "closed"}).encode("utf-8"),
                                 headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                                          "User-Agent": "rinvo-reset", "Content-Type": "application/json"})
    with (otworz or _otworz)(req, timeout=30):
        return True


# ── main ──────────────────────────────────────────────────────────────────────

PLAN = """Plan (nic nie zostało zmienione, bo brakuje flagi --tak):
  1. Linear: archiwizacja wszystkich zgłoszeń zespołu RIN (etykiety i widok „Dla mnie dziś” zostają)
  2. Rinvo: usunięcie wygenerowanego stanu: {usuwane}
  3. Transkrypcje: auto-tama → proba/transkrypcje/auto-tama/, klinika-usmiech → proba/archiwum/klinika-usmiech/
  4. Karty: auto-tama tylko z konfiguracją (nazwa, domena, kontakt Kasi, zakres decyzji); karta kliniki usunięta
  5. Rinvo-app ({app}): config i wiedza z commita {baza}, commit na main, push, zamknięcie otwartych PR-ów
  6. Rejestr maili: data włączenia = dziś
  7. Strony: wygenerowane od nowa (puste)
Uruchom z flagą --tak, żeby wykonać."""


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Próba generalna od czystego stanu.")
    ap.add_argument("--tak", action="store_true", help="wykonaj reset (bez tej flagi tylko plan)")
    ap.add_argument("--app", default="../Rinvo-app", help="lokalny klon Rinvo-app")
    ap.add_argument("--baza-app", default="b2556d6", help="commit Rinvo-app sprzed poprawek agenta")
    ap.add_argument("--repo-app", default="Rembolekk/rinvo-app")
    ap.add_argument("--bez-linear", action="store_true")
    ap.add_argument("--bez-app", action="store_true")
    args = ap.parse_args()
    if not args.tak:
        print(PLAN.format(usuwane=", ".join(USUWANE), app=args.app, baza=args.baza_app))
        sys.exit(2)

    from przetworz import load_env
    from sekrety import wyczysc_srodowisko
    load_env()
    wyczysc_srodowisko()
    dzis = date.today()

    if not args.bez_linear:
        import linear_sync
        n = archiwizuj_zgloszenia(linear_sync.load_api_key(), linear_sync.gql)
        print(f"Linear: zarchiwizowano {n} zgłoszeń.")
    root = Path(".")
    ruchy = przenies_transkrypcje(root)
    for skad, dokad in ruchy:
        print(f"  {skad} → {dokad}")
    zostalo, usuniete_karty = reset_kart(root)
    print(f"Karty: zostaje {zostalo}, usunięte {usuniete_karty}.")
    usuniete = reset_stanu(root, dzis)
    print(f"Usunięto: {', '.join(usuniete)}")
    import linear_sync as ls
    for klient in zostalo:
        ls.write_karta_md(klient, ls.load_karta(klient))

    if not args.bez_app:
        token = os.environ.get("AGENT_GITHUB_TOKEN", "")
        try:
            pr = otwarte_pr(args.repo_app, token or None)
        except Exception as exc:  # noqa: BLE001
            pr = []
            print(f"Uwaga: nie sprawdzono otwartych PR-ów ({type(exc).__name__}).")
        for numer, tytul in pr:
            if token:
                zamknij_pr(args.repo_app, numer, token)
                print(f"Rinvo-app: zamknięto PR #{numer}: {tytul}")
            else:
                print(f"UWAGA: PR #{numer} ({tytul}) jest otwarty. Zamknij go ręcznie (brak AGENT_GITHUB_TOKEN w środowisku).")
        w = reset_app(args.app, args.baza_app)
        print(f"Rinvo-app: przywrócono {w['zmienione'] or 'nic (już czysto)'}, commit {w['commit'] or 'brak'}, usunięte gałęzie: {w['galezie'] or 'brak'}")

    import generuj_strony
    dane = generuj_strony.wczytaj_dane(".")
    n = generuj_strony.zapisz(generuj_strony.buduj(dane))
    print(f"Strony: wygenerowane od nowa ({n} zmienionych).")
    print("Gotowe. Sprawdź: git status, uruchom testy offline, zrób commit i push.")


if __name__ == "__main__":
    main()
