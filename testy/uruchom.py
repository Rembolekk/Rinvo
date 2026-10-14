#!/usr/bin/env python3
"""uruchom.py – sprawdza wynik analizy i stan po rozmowie względem pliku oczekiwań.

Użycie:
  python3 testy/uruchom.py wyniki/<klient>/<nazwa>/wynik.json testy/oczekiwania/<klient>-<nazwa>.json
  python3 testy/uruchom.py <wynik.json> <oczekiwania.json> --online    # także stan w Linearze

Bez --online testy działają offline (wynik.json, karta klienta, prosby.json); testy
rodzaju "linear" są wtedy pomijane i liczone osobno. Wymaga LINEAR_API_KEY przy --online.

Rodzaje testów (pole typ_sprawdzania, domyślnie "pozycje"):
  pozycje        pozycja znaleziona po fragmencie cytatu: sekcja, status, rodzaj, pewność,
                 termin, przypomnienia, etykiety (wyliczone jak w linear_sync), okna czasowe
  zmiany_zdania  fragment w zmiany_zdania
  aktualizacja   wpis w aktualizacje_spraw (klucz_sprawy, oczekiwany_nowy_status)
  karta_sprawa   stan sprawy w karcie klienta (zamknieta / otwarta)
  karta_zakaz    aktywny zakaz w karcie klienta (po fragmencie cytatu)
  karta_ryzyka   licznik ryzyk w karcie (temat, min_zrodel)
  prosby         prośba produktowa w ops/produkt/prosby.json (min_klientow, klienci)
  okno_w         pierwsze okno sprawy: start (od_rowne), zasięg (do_min), przedział [od, do]
  okna_dokladnie okna sprawy są dokładnie takie
  mail_nie_zawiera  szkic maila nie zawiera podanych fraz
  linear         (tylko --online) stan, etykiety, priorytet i termin zgłoszenia w Linearze

Wyjście: ostatnia linia "PASS X/Y" albo "FAIL X/Y" (kod 0 tylko gdy wszystkie wykonane
testy przeszły). Y nie obejmuje testów pominiętych (offline).
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── etykiety: ten sam silnik zasad co w linear_sync.py (ops/zasady.json) ──────

import zasady  # noqa: E402

ZASADY = zasady.wczytaj_zasady()


def compute_labels(item, karta=None, prosby=None, klient=None):
    wielu = item.get("sekcja") == 3 and zasady.wielu_klientow(prosby or {}, ZASADY, item, klient)
    return zasady.etykiety_pozycji(item, ZASADY, karta, wielu)


# ── kontekst: wynik + karta + prosby (+ Linear) ───────────────────────────────

class Kontekst:
    def __init__(self, wynik_path, online):
        self.wynik = json.loads(Path(wynik_path).read_text(encoding="utf-8"))
        parts = Path(wynik_path).resolve().parts
        # wyniki/<klient>/<nazwa>/wynik.json
        self.klient = parts[-3] if len(parts) >= 3 else None
        self.karta = self._wczytaj(ROOT / "ops" / "klienci" / str(self.klient) / "karta.json")
        self.prosby = self._wczytaj(ROOT / "ops" / "produkt" / "prosby.json")
        self.online = online
        self._api_key = None
        self._linear_cache = {}

    @staticmethod
    def _wczytaj(path):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    # -- Linear
    def issue_linear(self, klucz):
        """Zwraca (dane_zgloszenia | None, błąd | None) dla klucza_sprawy z karty klienta."""
        info = self.karta.get("otwarte_sprawy", {}).get(klucz) \
            or self.karta.get("zamkniete_sprawy", {}).get(klucz)
        if not isinstance(info, dict) or not info.get("identifier"):
            return None, f"sprawa {klucz!r} nie ma zgłoszenia w karcie klienta"
        ident = info["identifier"]
        if ident in self._linear_cache:
            return self._linear_cache[ident], None
        try:
            import linear_sync
            if self._api_key is None:
                self._api_key = linear_sync.load_api_key()
            numer = int(ident.split("-")[1])
            zapytanie = (
                'query { issues(filter: { team: { key: { eq: "%s" } }, number: { eq: %d } }) { '
                'nodes { identifier priority dueDate state { name type } '
                'labels { nodes { name } } } } }' % (linear_sync.TEAM_KEY, numer))
            data = linear_sync.gql(self._api_key, zapytanie)
        except SystemExit as exc:
            return None, f"błąd połączenia z Linear: {exc}"
        except Exception as exc:  # noqa: BLE001
            return None, f"błąd zapytania do Linear: {exc}"
        nodes = data.get("issues", {}).get("nodes", [])
        if not nodes:
            return None, f"w Linearze nie ma {ident}"
        self._linear_cache[ident] = nodes[0]
        return nodes[0], None


# ── szukanie pozycji po cytacie ───────────────────────────────────────────────

def find_pozycja(pozycje, fragment):
    matches = []
    for p in pozycje:
        if any(fragment in c for c in p.get("cytat", [])):
            matches.append(p)
    return matches


def _pierwsza_liczba(tekst):
    m = re.search(r"\d+", str(tekst))
    return int(m.group()) if m else None


# ── sprawdzanie: pozycje ──────────────────────────────────────────────────────

def _sprawdz_pozycje_jedna(ctx, p, exp):
    """Zwraca komunikat błędu albo None, gdy pozycja spełnia oczekiwania."""
    if "oczekiwana_sekcja" in exp and p.get("sekcja") != exp["oczekiwana_sekcja"]:
        return f"sekcja: oczekiwano {exp['oczekiwana_sekcja']}, jest {p.get('sekcja')} (id={p.get('id')})"
    if "oczekiwana_sekcja_jedna_z" in exp and p.get("sekcja") not in exp["oczekiwana_sekcja_jedna_z"]:
        return (f"sekcja: oczekiwano jednej z {exp['oczekiwana_sekcja_jedna_z']}, "
                f"jest {p.get('sekcja')} (id={p.get('id')})")
    if "oczekiwany_status" in exp and p.get("status") != exp["oczekiwany_status"]:
        return f"status: oczekiwano {exp['oczekiwany_status']!r}, jest {p.get('status')!r} (id={p.get('id')})"
    if "oczekiwany_rodzaj" in exp and p.get("rodzaj") != exp["oczekiwany_rodzaj"]:
        return f"rodzaj: oczekiwano {exp['oczekiwany_rodzaj']!r}, jest {p.get('rodzaj')!r} (id={p.get('id')})"
    if "oczekiwana_pewnosc" in exp and p.get("pewnosc") != exp["oczekiwana_pewnosc"]:
        return f"pewność: oczekiwano {exp['oczekiwana_pewnosc']!r}, jest {p.get('pewnosc')!r} (id={p.get('id')})"
    if "oczekiwany_termin" in exp and str(p.get("termin")) != exp["oczekiwany_termin"]:
        return f"termin: oczekiwano {exp['oczekiwany_termin']!r}, jest {p.get('termin')!r} (id={p.get('id')})"

    if "oczekiwane_przypomnienia" in exp:
        pr = p.get("przypomnienie") or {}
        limit = pr.get("limit", "brak")
        n = _pierwsza_liczba(limit)
        if n is None:
            # brak liczby: "brak"/"nie ustalono" bez daty = brak przypomnień
            n = 0 if (not pr or str(pr.get("data", "brak")) in ("brak", "nie ustalono")) else None
        if n != exp["oczekiwane_przypomnienia"]:
            return (f"przypomnienia: oczekiwano {exp['oczekiwane_przypomnienia']}, "
                    f"jest {pr!r} (id={p.get('id')})")

    labels = compute_labels(p, ctx.karta, ctx.prosby, ctx.klient)
    for lbl in exp.get("oczekiwane_etykiety", []):
        if lbl not in labels:
            return (f"brakuje etykiety {lbl!r} (jest: {labels}, typ={p.get('typ')}, "
                    f"rodzaj={p.get('rodzaj')}, pewnosc={p.get('pewnosc')}, "
                    f"zakaz={bool(p.get('konflikt_z_zakazem'))}, id={p.get('id')})")
    for lbl in exp.get("zakazane_etykiety", []):
        if lbl in labels:
            return (f"niedozwolona etykieta {lbl!r} (jest: {labels}, typ={p.get('typ')}, "
                    f"rodzaj={p.get('rodzaj')}, id={p.get('id')})")

    if "oczekiwane_okna_min" in exp:
        klucz = p.get("klucz_sprawy")
        entry = next((o for o in ctx.wynik.get("okna_czasowe", []) if o.get("klucz_sprawy") == klucz), None)
        if not entry:
            return f"brak okna_czasowe dla {klucz!r}"
        n = len(entry.get("okna", []))
        if n < exp["oczekiwane_okna_min"]:
            return f"za mało okien dla {klucz!r}: {n} < {exp['oczekiwane_okna_min']}"
    return None


def check_pozycje(ctx, exp):
    fragment = exp.get("fragment_cytatu", "")
    matches = find_pozycja(ctx.wynik.get("pozycje", []), fragment)
    if not matches:
        return "fail", f"brak pozycji z cytatem: {fragment!r}"

    if exp.get("wszystkie_pasujace"):
        # każda pozycja z tym cytatem musi spełniać oczekiwania (np. "w żadnym wypadku Dla agenta")
        for p in matches:
            err = _sprawdz_pozycje_jedna(ctx, p, exp)
            if err:
                return "fail", err
        return "pass", ""

    if len(matches) > 1 and "oczekiwana_sekcja" in exp:
        filtered = [p for p in matches if p.get("sekcja") == exp["oczekiwana_sekcja"]]
        if filtered:
            matches = filtered
    if len(matches) > 1:
        ids = [p.get("id", "?") for p in matches]
        return "fail", f"niejednoznaczne dopasowanie ({len(matches)} pozycji: {ids}) dla: {fragment!r}"

    err = _sprawdz_pozycje_jedna(ctx, matches[0], exp)
    return ("fail", err) if err else ("pass", "")


# ── pozostałe rodzaje ─────────────────────────────────────────────────────────

def check_zmiany_zdania(ctx, exp):
    fragment = exp.get("fragment_cytatu", "")
    for z in ctx.wynik.get("zmiany_zdania", []):
        if fragment in z.get("cytat", "") or any(fragment in str(v) for v in z.values()):
            return "pass", ""
    return "fail", f"nie znaleziono w zmiany_zdania: {fragment!r}"


def check_aktualizacja(ctx, exp):
    if "nie_ma_kluczy" in exp:
        # odrzucona informacja: żadna aktualizacja_spraw nie może dotyczyć tych kluczy/zakazów
        for a in ctx.wynik.get("aktualizacje_spraw", []):
            if a.get("klucz_sprawy") in exp["nie_ma_kluczy"]:
                return "fail", f"aktualizacja dotyczy {a['klucz_sprawy']!r} → {a.get('nowy_status')!r}, a miała być odrzucona"
        return "pass", ""
    klucz = exp["klucz_sprawy"]
    wpisy = [a for a in ctx.wynik.get("aktualizacje_spraw", []) if a.get("klucz_sprawy") == klucz]
    if not wpisy:
        return "fail", f"brak aktualizacji_spraw dla {klucz!r}"
    oczek = exp.get("oczekiwany_nowy_status")
    if oczek and not any(a.get("nowy_status") == oczek for a in wpisy):
        return "fail", (f"aktualizacja {klucz!r}: oczekiwano {oczek!r}, "
                        f"jest {[a.get('nowy_status') for a in wpisy]}")
    return "pass", ""


def check_karta_sprawa(ctx, exp):
    klucz = exp["klucz_sprawy"]
    otwarte = ctx.karta.get("otwarte_sprawy", {})
    zamkniete = ctx.karta.get("zamkniete_sprawy", {})
    stan = exp["oczekiwany_stan"]
    if stan == "zamknieta":
        if klucz in otwarte:
            return "fail", f"{klucz!r} nadal w otwarte_sprawy karty ({otwarte[klucz].get('identifier')})"
        wpis = zamkniete.get(klucz)
        if not wpis:
            return "fail", f"{klucz!r} nie ma w zamkniete_sprawy karty"
        if wpis.get("status_koncowy") != "zamknieta":
            return "fail", f"status_koncowy {klucz!r}: {wpis.get('status_koncowy')!r}"
        return "pass", ""
    if stan == "otwarta":
        if klucz not in otwarte:
            return "fail", f"{klucz!r} nie ma w otwarte_sprawy karty"
        return "pass", ""
    return "fail", f"nieznany oczekiwany_stan: {stan!r}"


def check_karta_zakaz(ctx, exp):
    fragment = exp["fragment_cytatu"]
    for z in ctx.karta.get("zakazy", []):
        if any(fragment in c for c in z.get("cytat", [])):
            return "pass", ""
    return "fail", f"brak aktywnego zakazu w karcie z cytatem: {fragment!r}"


def check_karta_ryzyka(ctx, exp):
    wpisy = ctx.karta.get("ryzyka", {}).get(exp["temat"], [])
    n = len({r.get("zrodlo") for r in wpisy})
    if n < exp.get("min_zrodel", 2):
        return "fail", f"ryzyko {exp['temat']!r}: {n} różnych rozmów w karcie, oczekiwano ≥ {exp.get('min_zrodel', 2)}"
    return "pass", ""


def check_prosby(ctx, exp):
    matches = find_pozycja(ctx.wynik.get("pozycje", []), exp["fragment_cytatu"])
    if not matches:
        return "fail", f"brak pozycji z cytatem: {exp['fragment_cytatu']!r}"
    klucz_f = matches[0].get("klucz_funkcji")
    if not klucz_f:
        return "fail", f"pozycja {matches[0].get('id')} nie ma klucz_funkcji"
    klienci = {p.get("klient") for p in ctx.prosby.get(klucz_f, {}).get("prosby", [])}
    if len(klienci) < exp.get("min_klientow", 2):
        return "fail", f"prosby.json[{klucz_f!r}]: klienci {sorted(klienci)}, oczekiwano ≥ {exp.get('min_klientow', 2)}"
    for k in exp.get("klienci", []):
        if k not in klienci:
            return "fail", f"prosby.json[{klucz_f!r}]: brak klienta {k!r} (są: {sorted(klienci)})"
    return "pass", ""


def _okna(ctx, klucz):
    entry = next((o for o in ctx.wynik.get("okna_czasowe", []) if o.get("klucz_sprawy") == klucz), None)
    return entry.get("okna", []) if entry else None


def check_okno_w(ctx, exp):
    """Pierwsze okno sprawy (to, w którym ma ruszyć) spełnia warunki: od_rowne, do_min,
    oraz mieści się w [od, do]. Kolejne okna (np. po urlopie) są zapasowe i nie są oceniane."""
    okna = _okna(ctx, exp["klucz_sprawy"])
    if not okna:
        return "fail", f"brak okien czasowych dla {exp['klucz_sprawy']!r}"
    o = okna[0]
    opis = f"pierwsze okno {o['od']}–{o.get('do')}"
    if "od_rowne" in exp and o["od"] != exp["od_rowne"]:
        return "fail", f"{opis}: start powinien być {exp['od_rowne']}"
    if "do_min" in exp and (o.get("do") is None or o["do"] < exp["do_min"]):
        return "fail", f"{opis}: powinno sięgać co najmniej {exp['do_min']}"
    if "od" in exp and o["od"] < exp["od"]:
        return "fail", f"{opis}: zaczyna się przed {exp['od']}"
    if "do" in exp and (o.get("do") is None or o["do"] > exp["do"]):
        return "fail", f"{opis}: wychodzi poza {exp['do']}"
    return "pass", ""


def check_okna_dokladnie(ctx, exp):
    okna = _okna(ctx, exp["klucz_sprawy"])
    if okna is None:
        return "fail", f"brak okien czasowych dla {exp['klucz_sprawy']!r}"
    jest = [{"od": o["od"], "do": o.get("do")} for o in okna]
    if jest != exp["okna"]:
        return "fail", f"okna {exp['klucz_sprawy']!r}: oczekiwano {exp['okna']}, jest {jest}"
    return "pass", ""


def check_mail_nie_zawiera(ctx, exp):
    mail = ctx.wynik.get("szkic_maila", "").lower()
    for fraza in exp["frazy"]:
        if fraza.lower() in mail:
            return "fail", f"szkic maila zawiera zakazaną frazę: {fraza!r}"
    return "pass", ""


def check_linear(ctx, exp):
    if not ctx.online:
        return "skip", "wymaga --online"
    issue, err = ctx.issue_linear(exp["klucz_sprawy"])
    if err:
        return "fail", err
    ident = issue.get("identifier")
    stan = issue.get("state", {}).get("name")
    etykiety = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]
    if "oczekiwany_stan_linear" in exp and stan != exp["oczekiwany_stan_linear"]:
        return "fail", f"{ident}: stan {stan!r}, oczekiwano {exp['oczekiwany_stan_linear']!r}"
    if "zakazany_stan_linear" in exp and stan == exp["zakazany_stan_linear"]:
        return "fail", f"{ident}: stan {stan!r} jest niedozwolony"
    for lbl in exp.get("oczekiwane_etykiety", []):
        if lbl not in etykiety:
            return "fail", f"{ident}: brakuje etykiety {lbl!r} (jest: {etykiety})"
    for lbl in exp.get("zakazane_etykiety", []):
        if lbl in etykiety:
            return "fail", f"{ident}: niedozwolona etykieta {lbl!r} (jest: {etykiety})"
    if "oczekiwany_priorytet" in exp and issue.get("priority") != exp["oczekiwany_priorytet"]:
        return "fail", f"{ident}: priorytet {issue.get('priority')}, oczekiwano {exp['oczekiwany_priorytet']} (1 = Urgent)"
    if "oczekiwany_termin_linear" in exp and issue.get("dueDate") != exp["oczekiwany_termin_linear"]:
        return "fail", f"{ident}: termin {issue.get('dueDate')!r}, oczekiwano {exp['oczekiwany_termin_linear']!r}"
    return "pass", ""


SPRAWDZENIA = {
    "pozycje": check_pozycje,
    "zmiany_zdania": check_zmiany_zdania,
    "aktualizacja": check_aktualizacja,
    "karta_sprawa": check_karta_sprawa,
    "karta_zakaz": check_karta_zakaz,
    "karta_ryzyka": check_karta_ryzyka,
    "prosby": check_prosby,
    "okno_w": check_okno_w,
    "okna_dokladnie": check_okna_dokladnie,
    "mail_nie_zawiera": check_mail_nie_zawiera,
    "linear": check_linear,
}


def check(ctx, exp):
    rodzaj = exp.get("typ_sprawdzania", "pozycje")
    fn = SPRAWDZENIA.get(rodzaj)
    if not fn:
        return "fail", f"nieznany typ_sprawdzania: {rodzaj!r}"
    try:
        return fn(ctx, exp)
    except KeyError as exc:
        return "fail", f"w oczekiwaniu brakuje pola {exc}"


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    args = [a for a in sys.argv[1:] if a != "--online"]
    online = "--online" in sys.argv[1:]
    if len(args) != 2:
        print("Użycie: python3 testy/uruchom.py wynik.json oczekiwania.json [--online]", file=sys.stderr)
        sys.exit(2)

    wynik_path, oczekiwania_path = Path(args[0]), Path(args[1])
    for pth in (wynik_path, oczekiwania_path):
        if not pth.exists():
            print(f"Błąd: brak {pth}", file=sys.stderr)
            sys.exit(2)

    # linear_sync czyta .env względem bieżącego katalogu: pracujemy z katalogu projektu
    wynik_path, oczekiwania_path = wynik_path.resolve(), oczekiwania_path.resolve()
    os.chdir(ROOT)

    ctx = Kontekst(wynik_path, online)
    oczekiwania = json.loads(oczekiwania_path.read_text(encoding="utf-8"))

    passed = failed = skipped = 0
    failures = []

    for i, exp in enumerate(oczekiwania, 1):
        opis = exp.get("opis", f"test {i}")
        status, reason = check(ctx, exp)
        if status == "pass":
            passed += 1
            print(f"  PASS  {opis}")
        elif status == "skip":
            skipped += 1
            print(f"  SKIP  {opis}  ({reason})")
        else:
            failed += 1
            print(f"  FAIL  {opis}")
            print(f"        {reason}")
            failures.append((opis, reason))

    total = passed + failed
    wynik_linia = f"{'PASS' if failed == 0 else 'FAIL'} {passed}/{total}"
    if skipped:
        wynik_linia += f" (pominięto offline: {skipped})"

    if failures:
        print(f"\nNiepowodzenia ({len(failures)}):")
        for opis, reason in failures:
            print(f"  - {opis}: {reason}")
    print(f"\n{wynik_linia}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
