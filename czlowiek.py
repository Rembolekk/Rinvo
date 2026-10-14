#!/usr/bin/env python3
"""czlowiek.py – zmiany człowieka w Linearze mają pierwszeństwo przed automatem.

Automat i człowiek działają na tym samym koncie Lineara, więc autora zmiany nie da się odczytać z API. Rozpoznajemy ją tak:
  * każda zapisująca mutacja automatu (issueUpdate, issueArchive) zapisuje id zgłoszenia w ops/.zmiany_automatu.json,
  * na końcu przebiegu stan_linear porównuje świeży stan z poprzednią migawką; zgłoszenie, które się zmieniło (stan albo etykiety)
    albo zniknęło (usunięte, zarchiwizowane), a NIE było dotknięte przez automat, to zmiana człowieka,
  * zmiany człowieka zostają w ops/.reczne_zmiany.json (kiedy, nowy stan, dodane i usunięte etykiety, usunięte).
Zasady: automat nie cofa zamknięcia, anulowania ani etykiet; ponowne otwarcie tylko przez źródło PÓŹNIEJSZE niż zmiana człowieka;
zgłoszenie usunięte lub zarchiwizowane przez człowieka jest odrzucone: nie tworzymy go ponownie, wpis w karcie (odrzucone).
"""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

PLIK_RECZNE = Path("ops/.reczne_zmiany.json")
PLIK_DOTKNIETE = Path("ops/.zmiany_automatu.json")
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")
STANY_ZAMKNIETE_TYP = {"completed", "canceled"}


def _json(p, domyslnie):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else domyslnie


# ── dotknięcia automatu ───────────────────────────────────────────────────────

def zapisz_dotkniecie(linear_id, plik=None):
    """Automat zmienia zgłoszenie o tym id (mutacja zapisująca). Zapisywane są tylko prawdziwe id (UUID)."""
    if not isinstance(linear_id, str) or not _UUID.match(linear_id):
        return False
    p = Path(plik) if plik else PLIK_DOTKNIETE
    lista = set(_json(p, []))
    if linear_id in lista:
        return True
    lista.add(linear_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(lista), indent=1) + "\n", encoding="utf-8")
    return True


def wczytaj_dotkniete(plik=None):
    return set(_json(plik or PLIK_DOTKNIETE, []))


def wyczysc_dotkniete(plik=None):
    p = Path(plik) if plik else PLIK_DOTKNIETE
    if p.exists():
        p.write_text("[]\n", encoding="utf-8")


# ── wykrywanie zmian człowieka ────────────────────────────────────────────────

def wykryj(stare, nowe, dotkniete, teraz=None):
    """{identyfikator: zmiana} dla zgłoszeń zmienionych albo usuniętych bez udziału automatu. Czysta funkcja.
    stare, nowe: migawki {identyfikator: {"id", "stan", "typ_stanu", "etykiety", "zmieniono"}}; dotkniete: zbiór id Lineara."""
    teraz = teraz or datetime.now(timezone.utc).isoformat(timespec="seconds")
    wynik = {}
    for ident, s in (stare or {}).items():
        n = (nowe or {}).get(ident)
        lid = (n or s).get("id") or s.get("id")
        if lid and lid in dotkniete:
            continue
        if n is None:
            wynik[ident] = {"usuniete": True, "kiedy": teraz}
            continue
        dod = sorted(set(n.get("etykiety", [])) - set(s.get("etykiety", [])))
        usu = sorted(set(s.get("etykiety", [])) - set(n.get("etykiety", [])))
        if n.get("stan") != s.get("stan") or dod or usu:
            wynik[ident] = {"kiedy": n.get("zmieniono") or teraz, "stan": n.get("stan"), "typ_stanu": n.get("typ_stanu"),
                            "poprzedni_stan": s.get("stan"), "zamkniete": n.get("typ_stanu") in STANY_ZAMKNIETE_TYP,
                            "etykiety_dodane": dod, "etykiety_usuniete": usu}
    return wynik


def zarejestruj(zmiany, plik=None):
    """Dopisuje zmiany człowieka do ops/.reczne_zmiany.json (kumulacyjnie: etykiety się sumują, najnowszy stan wygrywa)."""
    if not zmiany:
        return {}
    p = Path(plik) if plik else PLIK_RECZNE
    reczne = _json(p, {})
    for ident, z in zmiany.items():
        stare = reczne.get(ident, {})
        scalone = {**stare, **{k: v for k, v in z.items() if k not in ("etykiety_dodane", "etykiety_usuniete")}}
        scalone["etykiety_dodane"] = sorted((set(stare.get("etykiety_dodane", [])) | set(z.get("etykiety_dodane", []))) - set(z.get("etykiety_usuniete", [])))
        scalone["etykiety_usuniete"] = sorted((set(stare.get("etykiety_usuniete", [])) | set(z.get("etykiety_usuniete", []))) - set(z.get("etykiety_dodane", [])))
        reczne[ident] = scalone
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reczne, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return reczne


def wczytaj_reczne(plik=None):
    return _json(plik or PLIK_RECZNE, {})


def zastosuj_usuniete_do_kart(identyfikatory, katalog="ops/klienci", dzis=None):
    """Zgłoszenia usunięte albo zarchiwizowane przez człowieka: wpis w karcie (odrzucone), zdjęcie z otwartych i zamkniętych spraw,
    żeby automat nie tworzył ich ponownie. Zwraca [(klient, klucz, identyfikator)]."""
    dzis = (dzis or date.today()).isoformat()
    wynik = []
    for p in sorted(Path(katalog).glob("*/karta.json")):
        karta = json.loads(p.read_text(encoding="utf-8"))
        zmiana = False
        for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):
            for klucz, wpis in list((karta.get(sekcja) or {}).items()):
                if isinstance(wpis, dict) and wpis.get("identifier") in identyfikatory:
                    karta.setdefault("odrzucone", {})[klucz] = {**wpis, "powod": "zgłoszenie usunięte lub zarchiwizowane przez człowieka",
                                                               "kiedy": dzis}
                    del karta[sekcja][klucz]
                    wynik.append((p.parent.name, klucz, wpis["identifier"]))
                    zmiana = True
        if zmiana:
            p.write_text(json.dumps(karta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return wynik


# ── pytania o prawo automatu ──────────────────────────────────────────────────

def _data(x):
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def zmiana(identyfikator, reczne=None):
    return (reczne if reczne is not None else wczytaj_reczne()).get(identyfikator)


def zmieniono_stan(identyfikator, reczne=None):
    z = zmiana(identyfikator, reczne)
    return bool(z and z.get("stan") and z.get("stan") != z.get("poprzedni_stan"))


def etykiety_reczne(identyfikator, reczne=None):
    """True, gdy człowiek zmienił etykiety zgłoszenia: automat ich nie dotyka."""
    z = zmiana(identyfikator, reczne)
    return bool(z and (z.get("etykiety_dodane") or z.get("etykiety_usuniete")))


def usuniete_przez_czlowieka(identyfikator, reczne=None):
    z = zmiana(identyfikator, reczne)
    return bool(z and z.get("usuniete"))


def wolno_zmienic_stan(identyfikator, data_zrodla, reczne=None):
    """Automat może zmienić stan zgłoszenia, gdy człowiek go nie ruszał albo gdy źródło jest PÓŹNIEJSZE niż zmiana człowieka."""
    z = zmiana(identyfikator, reczne)
    if not z:
        return True
    if z.get("usuniete"):
        return False
    if not zmieniono_stan(identyfikator, reczne):
        return True
    d, kiedy = _data(data_zrodla), _data(z.get("kiedy"))
    return bool(d and kiedy and d > kiedy)
