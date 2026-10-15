#!/usr/bin/env python3
"""test_utwardzanie2.py – utwardzanie cz. 2 (9 przypadków): regresje, pierwszeństwo człowieka, rozmiar zmiany i konflikty plików agenta,
blokady a naprawy, wygasanie kluczy, limity i kredyty modelu, bezpiecznik kosztów, eskalacja decyzji człowieka.

Bez sieci i bez modelu. Nazwy testów zaczynają się od numeru punktu (cNN_). Uruchomienie: python3 testy/test_utwardzanie2.py
"""

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import agent
import agent_scal
import agent_srodowisko
import czlowiek
import klucze
import limity
import linear_sync
import maile
import podsumowanie
import stan_linear
import zakazy_czas
import zasady
import test_agent as ta
import test_strony as tst

Z = zasady.wczytaj_zasady()
A = Z["agent_wykonawczy"]


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._t.cleanup()

    def zapisz(self, sciezka, dane):
        p = self.root / sciezka
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dane if isinstance(dane, str) else json.dumps(dane, ensure_ascii=False), encoding="utf-8")
        return p


UUID = "6d340410-b31c-44ab-9657-d069f460cbea"


class GqlAtrapa:
    """Podmienia linear_sync.gql i get_issue_state_and_labels: zapisuje wywołania, stan zgłoszenia zadany z góry."""

    def __init__(self, typ_stanu="completed", etykiety=()):
        self.wywolania, self.typ, self.etykiety = [], typ_stanu, list(etykiety)

    def __enter__(self):
        self.o_gql, self.o_stan, self.o_dod = linear_sync.gql, linear_sync.get_issue_state_and_labels, linear_sync.dodaj_etykiete
        linear_sync.gql = lambda k, q, v=None, **kw: (self.wywolania.append((q, v)), {})[1]
        linear_sync.get_issue_state_and_labels = lambda k, i: {"type": self.typ, "name": "Done" if self.typ == "completed" else "Todo",
                                                               "labels": [{"id": "x", "name": n} for n in self.etykiety]}
        linear_sync.dodaj_etykiete = lambda k, lid, mapa, nazwa: self.wywolania.append(("etykieta", nazwa))
        return self

    def __exit__(self, *a):
        linear_sync.gql, linear_sync.get_issue_state_and_labels, linear_sync.dodaj_etykiete = self.o_gql, self.o_stan, self.o_dod
        return False

    def komentarze(self):
        return [v["body"] for q, v in self.wywolania if q == linear_sync.M_ADD_COMMENT]

    def zmiany_stanu(self):
        return [v["input"]["stateId"] for q, v in self.wywolania if q == linear_sync.M_UPDATE_ISSUE and "stateId" in v["input"]]


def item_bug(**kw):
    p = {"sekcja": 1, "typ": "bug", "status": "zrob_teraz", "tytul": "Toruń znowu podaje sobotę do 14:00", "klucz_sprawy": "godziny-torun",
         "cytat": ["Toruń znowu mówi, że w sobotę jest do czternastej."], "opis": "", "pewnosc": "wysoka"}
    p.update(kw)
    return p


def wpis_zamkniety(**kw):
    w = {"linear_id": UUID, "identifier": "RIN-41", "url": "https://linear.app/x/RIN-41", "tytul": "Toruń sobota", "zrodla": ["ops/transkrypcje/alfa/2026-10-06-call.md"],
         "status_koncowy": "zamknieta"}
    w.update(kw)
    return w


# ── c01. naprawiona sprawa wraca ──────────────────────────────────────────────

class C01Regresja(Tmp):

    def test_c01_regresja_otwiera_to_samo_zgloszenie_zamiast_tworzyc_nowe(self):
        karta = {"otwarte_sprawy": {}, "zamkniete_sprawy": {"godziny-torun": wpis_zamkniety()}}
        with GqlAtrapa() as g:
            r = linear_sync.sprawdz_regresje("k", karta, "godziny-torun", item_bug(), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20", "TODO_ID", {}, Z)
        self.assertTrue(r)
        self.assertEqual(g.zmiany_stanu(), ["TODO_ID"], "Todo")
        komentarz = g.komentarze()[0]
        self.assertIn("Wróciło", komentarz)
        self.assertIn("Toruń znowu mówi, że w sobotę jest do czternastej.", komentarz, "cytat")
        self.assertIn("2026-10-20-call.md", komentarz, "źródło")
        self.assertIn(("etykieta", "Regresja"), g.wywolania)
        self.assertIn("godziny-torun", karta["otwarte_sprawy"])
        self.assertNotIn("godziny-torun", karta["zamkniete_sprawy"])
        w = karta["otwarte_sprawy"]["godziny-torun"]
        self.assertEqual(w["regresje"][0]["data"], "2026-10-20")
        self.assertNotIn("status_koncowy", w)

    def test_c01_sprawa_nadal_w_otwartych_ale_zgloszenie_done_tez_wraca(self):
        """Typowo: agent scalił PR i zgłoszenie jest Done, a karta nadal ma je w otwartych."""
        karta = {"otwarte_sprawy": {"godziny-torun": {k: v for k, v in wpis_zamkniety().items() if k != "status_koncowy"}}}
        with GqlAtrapa(typ_stanu="completed") as g:
            self.assertTrue(linear_sync.sprawdz_regresje("k", karta, "godziny-torun", item_bug(), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20", "T", {}, Z))
        self.assertEqual(g.zmiany_stanu(), ["T"])

    def test_c01_otwarte_zgloszenie_to_nie_regresja(self):
        karta = {"otwarte_sprawy": {"godziny-torun": {k: v for k, v in wpis_zamkniety().items() if k != "status_koncowy"}}}
        with GqlAtrapa(typ_stanu="unstarted") as g:
            self.assertFalse(linear_sync.sprawdz_regresje("k", karta, "godziny-torun", item_bug(), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20", "T", {}, Z))
        self.assertEqual(g.zmiany_stanu(), [])

    def test_c01_to_samo_zrodlo_starsze_zrodlo_i_inne_typy_nie_otwieraja(self):
        karta = {"otwarte_sprawy": {}, "zamkniete_sprawy": {"godziny-torun": wpis_zamkniety()}}
        with GqlAtrapa():
            f = lambda it, src, d: linear_sync.sprawdz_regresje("k", copy.deepcopy(karta), "godziny-torun", it, src, d, "T", {}, Z)     # noqa: E731
            self.assertFalse(f(item_bug(), "ops/transkrypcje/alfa/2026-10-06-call.md", "2026-10-06"), "to samo źródło")
            self.assertFalse(f(item_bug(), "ops/transkrypcje/alfa/2026-10-01-call.md", "2026-10-01"), "źródło starsze niż sprawa")
            self.assertFalse(f(item_bug(typ="zobowiazanie_nasze"), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20"), "to nie problem do naprawy")
            self.assertFalse(f(item_bug(sekcja=2), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20"))
            self.assertFalse(f(item_bug(status="czeka"), "ops/transkrypcje/alfa/2026-10-20-call.md", "2026-10-20"))

    def test_c01_dry_run_pokazuje_regresje_i_nie_tworzy_nowego(self):
        self.zapisz("ops/klienci/alfa/karta.json", {"klient": "alfa", "otwarte_sprawy": {}, "zamkniete_sprawy": {"godziny-torun": wpis_zamkniety()}, "zakazy": []})
        wynik = {"zrodlo": "ops/transkrypcje/alfa/2026-10-20-call.md", "spotkanie": {"data": "2026-10-20", "uczestnicy": ["Kasia"]}, "wygenerowano": "2026-10-20",
                 "pozycje": [{**item_bug(), "id": "T1", "wlasciciel": "Marek", "termin": "brak", "warunek": "brak"}], "aktualizacje_spraw": []}
        self.zapisz("w.json", wynik)
        wyj = io.StringIO()
        with contextlib.redirect_stdout(wyj):
            sys.argv = ["linear_sync.py", "w.json", "--klient", "alfa", "--dry-run", "--zrodlo", "ops/transkrypcje/alfa/2026-10-20-call.md"]
            linear_sync.main()
        self.assertIn("[regresja] godziny-torun (RIN-41): wróciło", wyj.getvalue())
        self.assertNotIn("[utwórz]", wyj.getvalue())

    def test_c01_etykieta_regresja_i_oznaczenie_na_stronie_klienta(self):
        self.assertIn("Regresja", linear_sync.REQUIRED_LABELS)
        stan = {"RIN-41": tst.zg("[alfa] Toruń sobota", etykiety=["Konfiguracja", "Regresja"], url="https://linear.app/x/RIN-41")}
        wpis = {"identifier": "RIN-41", "url": "https://linear.app/x/RIN-41", "tytul": "Toruń sobota", "zrodla": [],
                "regresje": [{"data": "2026-10-20", "zrodlo": "ops/transkrypcje/alfa/2026-10-20-call.md", "cytat": "Toruń znowu mówi, że do czternastej."}]}
        r = tst.Repo(stan=stan, karta_a=tst.karta("alfa", otwarte_sprawy={"godziny-torun": wpis}))
        h = r.strony()["klienci/alfa.html"]
        self.assertIn('<span class="tag bad">regresja</span>', h, "oznaczenie przy zgłoszeniu w „Teraz”")
        t = tst.tekst(h)
        self.assertIn("Regresja", t)
        self.assertIn("Toruń znowu mówi, że do czternastej.", t)


# ── c02. zmiany człowieka mają pierwszeństwo ──────────────────────────────────

def mig(stan="Todo", typ="unstarted", etykiety=(), id_=UUID, zmieniono="2026-10-14T10:00:00Z"):
    return {"id": id_, "tytul": "[alfa] X", "url": "u", "stan": stan, "typ_stanu": typ, "etykiety": sorted(etykiety), "zmieniono": zmieniono}


class C02Czlowiek(Tmp):

    def test_c02_zamkniecie_anulowanie_i_zmiana_etykiet_bez_udzialu_automatu_to_zmiana_czlowieka(self):
        stare = {"RIN-1": mig(), "RIN-2": mig(id_="id-2"), "RIN-3": mig(id_="id-3", etykiety=["Dla agenta"]), "RIN-4": mig(id_="id-4")}
        nowe = {"RIN-1": mig("Done", "completed", zmieniono="2026-10-15T09:00:00Z"), "RIN-2": mig("Canceled", "canceled", id_="id-2"),
                "RIN-3": mig(id_="id-3", etykiety=["Decyzja człowieka"]), "RIN-4": mig(id_="id-4"), "RIN-5": mig(id_="id-5")}
        zm = czlowiek.wykryj(stare, nowe, set(), "2026-10-15T12:00:00+00:00")
        self.assertEqual(sorted(zm), ["RIN-1", "RIN-2", "RIN-3"], "RIN-4 bez zmian, RIN-5 nowe")
        self.assertTrue(zm["RIN-1"]["zamkniete"])
        self.assertEqual(zm["RIN-1"]["kiedy"], "2026-10-15T09:00:00Z")
        self.assertEqual((zm["RIN-3"]["etykiety_dodane"], zm["RIN-3"]["etykiety_usuniete"]), (["Decyzja człowieka"], ["Dla agenta"]))

    def test_c02_zmiana_automatu_nie_jest_zmiana_czlowieka(self):
        stare, nowe = {"RIN-1": mig()}, {"RIN-1": mig("Done", "completed")}
        self.assertEqual(czlowiek.wykryj(stare, nowe, {UUID}), {})

    def test_c02_usuniete_lub_zarchiwizowane_przez_czlowieka(self):
        zm = czlowiek.wykryj({"RIN-1": mig()}, {}, set(), "2026-10-15T12:00:00+00:00")
        self.assertEqual(zm["RIN-1"], {"usuniete": True, "kiedy": "2026-10-15T12:00:00+00:00"})
        self.assertEqual(czlowiek.wykryj({"RIN-1": mig()}, {}, {UUID}), {}, "usunięte przez automat (archiwizacja notatek)")

    def test_c02_mutacja_automatu_zapisuje_dotkniecie_a_nieprawdziwe_id_nie(self):
        oryginal = linear_sync.urllib.request.urlopen

        class Odp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"data": {}}'
        linear_sync.urllib.request.urlopen = lambda req, **kw: Odp()
        try:
            linear_sync.gql("k", linear_sync.M_UPDATE_ISSUE, {"id": UUID, "input": {"stateId": "s"}})
            linear_sync.gql("k", linear_sync.M_UPDATE_ISSUE, {"id": "i", "input": {"stateId": "s"}})
            linear_sync.gql("k", linear_sync.M_ADD_COMMENT, {"issueId": UUID, "body": "x"})
        finally:
            linear_sync.urllib.request.urlopen = oryginal
        self.assertEqual(czlowiek.wczytaj_dotkniete(), {UUID})

    def test_c02_odswiezenie_migawki_rejestruje_zmiany_czlowieka_i_czysci_dotkniecia(self):
        stan_linear.zapisz({"RIN-1": mig(), "RIN-2": mig(id_="id-2"), "RIN-3": mig(id_="id-3")}, "ops/.stan_linear.json")
        czlowiek.zapisz_dotkniecie("6d340410-b31c-44ab-9657-d069f460cbe0")
        nowe_wezly = [{"id": UUID, "identifier": "RIN-1", "title": "[alfa] X", "url": "u", "priority": 0, "createdAt": "c", "updatedAt": "2026-10-15T09:00:00Z",
                       "completedAt": "z", "dueDate": None, "state": {"name": "Done", "type": "completed"}, "labels": {"nodes": []}},
                      {"id": "id-2", "identifier": "RIN-2", "title": "[alfa] X", "url": "u", "priority": 0, "createdAt": "c", "updatedAt": "u", "completedAt": None,
                       "dueDate": None, "state": {"name": "Todo", "type": "unstarted"}, "labels": {"nodes": []}}]
        gql = lambda k, q, v=None: {"issues": {"nodes": nowe_wezly, "pageInfo": {"hasNextPage": False, "endCursor": None}}}      # noqa: E731
        stan_linear.odswiez("k", gql, "ops/.stan_linear.json")
        reczne = czlowiek.wczytaj_reczne()
        self.assertEqual(sorted(reczne), ["RIN-1", "RIN-3"], "RIN-1 zamknięte, RIN-3 zniknęło; RIN-2 bez zmian")
        self.assertTrue(reczne["RIN-1"]["zamkniete"])
        self.assertTrue(reczne["RIN-3"]["usuniete"])
        self.assertEqual(czlowiek.wczytaj_dotkniete(), set(), "okno dotknięć zamknięte")
        self.assertEqual(stan_linear.wczytaj("ops/.stan_linear.json")["zgloszenia"]["RIN-1"]["stan"], "Done")

    def test_c02_usuniete_przez_czlowieka_odrzucone_w_karcie_i_nie_tworzone_ponownie(self):
        self.zapisz("ops/klienci/alfa/karta.json", {"klient": "alfa", "zakazy": [], "otwarte_sprawy": {
            "plik-leadow": {"identifier": "RIN-49", "linear_id": "x", "url": "u", "tytul": "Plik leadów", "zrodla": ["ops/transkrypcje/alfa/2026-10-06-call.md"]}}})
        przeniesione = czlowiek.zastosuj_usuniete_do_kart({"RIN-49"}, "ops/klienci", date(2026, 10, 15))
        self.assertEqual(przeniesione, [("alfa", "plik-leadow", "RIN-49")])
        karta = json.loads((self.root / "ops/klienci/alfa/karta.json").read_text(encoding="utf-8"))
        self.assertNotIn("plik-leadow", karta["otwarte_sprawy"])
        self.assertEqual(karta["odrzucone"]["plik-leadow"]["kiedy"], "2026-10-15")
        self.assertIn("usunięte lub zarchiwizowane przez człowieka", karta["odrzucone"]["plik-leadow"]["powod"])
        wynik = {"zrodlo": "ops/transkrypcje/alfa/2026-10-20-call.md", "spotkanie": {"data": "2026-10-20", "uczestnicy": ["Kasia"]}, "wygenerowano": "2026-10-20",
                 "pozycje": [{**item_bug(), "id": "T1", "klucz_sprawy": "plik-leadow", "typ": "zobowiazanie_nasze", "wlasciciel": "Marek", "termin": "brak", "warunek": "brak"}],
                 "aktualizacje_spraw": []}
        self.zapisz("w.json", wynik)
        wyj = io.StringIO()
        with contextlib.redirect_stdout(wyj):
            sys.argv = ["linear_sync.py", "w.json", "--klient", "alfa", "--zrodlo", "ops/transkrypcje/alfa/2026-10-20-call.md", "--dry-run"]
            linear_sync.main()
        self.assertIn("[odrzucone przez człowieka] plik-leadow (RIN-49)", wyj.getvalue())
        self.assertNotIn("[utwórz]", wyj.getvalue())

    def test_c02_ponowne_otwarcie_tylko_przez_zrodlo_pozniejsze_niz_zmiana_czlowieka(self):
        czlowiek.zarejestruj({"RIN-41": {"kiedy": "2026-10-15T09:00:00Z", "stan": "Done", "poprzedni_stan": "Todo", "zamkniete": True,
                                          "etykiety_dodane": [], "etykiety_usuniete": []}})
        self.assertFalse(czlowiek.wolno_zmienic_stan("RIN-41", "2026-10-15"), "źródło z dnia zamknięcia nie wystarcza")
        self.assertFalse(czlowiek.wolno_zmienic_stan("RIN-41", "2026-10-10"))
        self.assertTrue(czlowiek.wolno_zmienic_stan("RIN-41", "2026-10-16"))
        self.assertTrue(czlowiek.wolno_zmienic_stan("RIN-99", "2026-10-10"), "zgłoszenie bez zmiany człowieka")
        karta = {"otwarte_sprawy": {}, "zamkniete_sprawy": {"godziny-torun": wpis_zamkniety()}}
        with GqlAtrapa() as g:
            self.assertFalse(linear_sync.sprawdz_regresje("k", copy.deepcopy(karta), "godziny-torun", item_bug(), "ops/transkrypcje/alfa/2026-10-15-call.md", "2026-10-15", "T", {}, Z))
            self.assertEqual(g.zmiany_stanu(), [])
            self.assertTrue(linear_sync.sprawdz_regresje("k", copy.deepcopy(karta), "godziny-torun", item_bug(), "ops/transkrypcje/alfa/2026-10-16-call.md", "2026-10-16", "T", {}, Z))

    def test_c02_zmiana_samych_etykiet_nie_blokuje_stanu_ale_blokuje_etykiety(self):
        czlowiek.zarejestruj({"RIN-7": {"kiedy": "2026-10-15T09:00:00Z", "stan": "Todo", "poprzedni_stan": "Todo", "zamkniete": False,
                                         "etykiety_dodane": ["Decyzja człowieka"], "etykiety_usuniete": ["Dla agenta"]}})
        self.assertTrue(czlowiek.etykiety_reczne("RIN-7"))
        self.assertTrue(czlowiek.wolno_zmienic_stan("RIN-7", "2026-10-10"))
        self.assertFalse(czlowiek.etykiety_reczne("RIN-8"))

    def test_c02_aktualizacja_sprawy_nie_cofa_zamkniecia_przez_czlowieka(self):
        czlowiek.zarejestruj({"RIN-49": {"kiedy": "2026-10-15T09:00:00Z", "stan": "Canceled", "poprzedni_stan": "Todo", "zamkniete": True,
                                           "etykiety_dodane": [], "etykiety_usuniete": []}})
        karta = {"zakazy": [], "otwarte_sprawy": {"plik": {"linear_id": UUID, "identifier": "RIN-49", "zrodla": ["ops/transkrypcje/alfa/2026-10-06-call.md"],
                                                         "data_spotkania": "2026-10-06"}}}
        wynik = {"aktualizacje_spraw": [{"klucz_sprawy": "plik", "nowy_status": "zrob_teraz", "cytat": "Plik już jest.", "uzasadnienie": "x", "pewnosc": "wysoka"}]}
        wyj = io.StringIO()
        with GqlAtrapa(typ_stanu="canceled") as g, contextlib.redirect_stdout(wyj):
            linear_sync.process_aktualizacje("k", wynik, karta, {"zrob_teraz": "T"}, {}, dry_run=False, meeting_date="2026-10-15",
                                             zrodlo_info={"typ": "rozmowa", "data": "2026-10-15", "imiona": ["Kasia"], "prawo": True, "powod_braku_prawa": ""},
                                             team_id="t", klient="alfa", source="ops/transkrypcje/alfa/2026-10-15-call.md")
        self.assertEqual(g.zmiany_stanu(), [], "automat nie cofnął anulowania")
        self.assertIn("człowiek zmienił stan zgłoszenia", wyj.getvalue())

    def test_c02_przelicz_i_ryzyko_nie_ruszaja_etykiet_zmienionych_przez_czlowieka(self):
        czlowiek.zarejestruj({"RIN-9": {"kiedy": "2026-10-15T09:00:00Z", "stan": "Todo", "poprzedni_stan": "Todo", "zamkniete": False,
                                         "etykiety_dodane": [], "etykiety_usuniete": ["Dla agenta"]}})
        karta = {"ryzyka": {"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "x"}]}}
        existing = {"linear_id": UUID, "identifier": "RIN-9", "tytul": "Ryzyko"}
        with GqlAtrapa() as g:
            linear_sync.eskaluj_istniejace_ryzyko("k", karta, existing, "k", {"temat_ryzyka": "konkurencja", "cytat": ["y"]}, {"Powtarzające się ryzyko": "L"}, "b.md", "2026-10-13")
        self.assertEqual([q for q, v in g.wywolania if q == linear_sync.M_UPDATE_ISSUE], [], "etykiety człowieka bez zmian")
        import przelicz
        kod = (ROOT / "przelicz.py").read_text(encoding="utf-8")
        self.assertIn("czlowiek.etykiety_reczne(", kod)


# ── c03. rozmiar zmiany agenta ────────────────────────────────────────────────

def pr_z(additions=2, deletions=2, sha="abc", **kw):
    return {**ta.pr(sha=sha), "additions": additions, "deletions": deletions, **kw}


class C03RozmiarZmiany(unittest.TestCase):

    def fakty(self, **kw):
        f = ta.fakty()
        f.update(kw)
        return f

    def test_c03_limity_w_zasadach(self):
        self.assertEqual((A["max_linii_auto_scalenia"], A["max_plikow_auto_scalenia"]), (40, 3))

    def test_c03_powyzej_limitu_linii_albo_plikow_oddanie_z_powodem_duza_zmiana(self):
        for kw in ({"linie": 41}, {"pliki": ["config/a.yaml", "config/b.yaml", "wiedza/c.md", "wiedza/d.md"]}):
            d = agent_scal.ocen_pr(self.fakty(**kw), A)
            self.assertEqual((d["akcja"], d["kategoria"]), ("oddaj", "duza_zmiana"), kw)
        self.assertEqual(agent_scal.ocen_pr(self.fakty(linie=40, pliki=["config/a.yaml", "config/b.yaml", "wiedza/c.md"]), A)["akcja"], "scal", "dokładnie na limicie")

    def test_c03_pr_zostaje_otwarty_bez_scalenia_z_etykieta_i_powodem_duza_zmiana(self):
        zg = ta.zgloszenie(41, stan="In Progress")
        s = ta.Srodowisko([zg], github=ta.AtrapaGitHub(prs=[pr_z(30, 15)], recenzje=[ta.recenzja()]))
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oddane")
        self.assertTrue(w["powod"].startswith("duża zmiana:"))
        self.assertEqual(s.github.scalone, [], "nie scala automatycznie")
        self.assertIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        komentarz = next(k[2] for k in s.linear.zdarzenia if k[0] == "komentarz")
        self.assertIn("Decyzja człowieka: duża zmiana", komentarz)

    def test_c03_mala_zmiana_scala_sie_jak_dotad(self):
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=ta.AtrapaGitHub(prs=[pr_z(10, 10)], recenzje=[ta.recenzja()]))
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "scalone")

    def test_c03_oddana_duza_zmiana_nie_wraca_sama_a_czlowiek_ktory_zdjal_etykiete_przejmuje(self):
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=ta.AtrapaGitHub(prs=[pr_z(30, 15)], recenzje=[ta.recenzja()]))
        agent_scal.uruchom_scalanie(s)
        komentarzy = len(s.github.dodane_komentarze)
        self.assertEqual(agent_scal.uruchom_scalanie(s), [], "kolejny przebieg: nadal oddana, bez powtórzeń")
        self.assertEqual(len(s.github.dodane_komentarze), komentarzy)
        s.linear.zgloszenia[0]["labels"].remove("Decyzja człowieka")          # człowiek zdejmuje etykietę: przejął PR
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])
        self.assertEqual((s.github.scalone, len(s.github.dodane_komentarze)), ([], komentarzy), "agent nie oddaje drugi raz ani nie scala")


# ── c04. konflikty plików i aktualizacja gałęzi ───────────────────────────────

class C04Konflikty(unittest.TestCase):

    def test_c04_zadanie_zmieniajace_plik_z_otwartym_pr_innego_zadania_czeka(self):
        gh = ta.AtrapaGitHub(prs=[ta.pr(5, ref="rin-40-inne")], pliki=["config/auto-tama.yaml"])
        s = ta.Srodowisko([ta.zgloszenie(41)], github=gh)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "czeka_na_scalenie")
        self.assertIn("config/auto-tama.yaml", w["powod"])
        self.assertIn("#5", w["powod"])
        self.assertEqual((s.linear.zdarzenia, s.git.wywolania), ([], []), "nic nie przejęto")

    def test_c04_zadanie_innego_klienta_idzie_a_czekajace_nie_zuzywa_limitu(self):
        gh = ta.AtrapaGitHub(prs=[ta.pr(5, ref="rin-40-inne")], pliki=["config/auto-tama.yaml"])
        s = ta.Srodowisko([ta.zgloszenie(41), ta.zgloszenie(42, klient="beta"), ta.zgloszenie(43, klient="gamma")], github=gh)
        w = agent.uruchom(s, max_n=1)
        self.assertEqual([x["status"] for x in w], ["czeka_na_scalenie", "pr"], "limit 1 zużyty dopiero przez prawdziwe przejęcie")

    def test_c04_w_jednym_przebiegu_drugie_zadanie_tego_samego_klienta_czeka_na_pierwsze(self):
        s = ta.Srodowisko([ta.zgloszenie(41), ta.zgloszenie(42)])
        w = agent.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["pr", "czeka_na_scalenie"])

    def test_c04_pr_nie_agenta_nie_blokuje_plikow(self):
        gh = ta.AtrapaGitHub(prs=[ta.pr(5, ref="dependabot/pip/x")], pliki=["config/auto-tama.yaml"])
        self.assertEqual(agent.uruchom(ta.Srodowisko([ta.zgloszenie(41)], github=gh))[0]["status"], "pr")

    def test_c04_przewidywane_pliki_to_config_i_wiedza_klienta(self):
        self.assertEqual(agent.pliki_zadania(ta.zgloszenie(41, klient="klinika-usmiech"), Z), {"config/klinika-usmiech.yaml", "wiedza/klinika-usmiech.md"})

    def test_c04_przed_scaleniem_galaz_za_main_jest_aktualizowana_i_czeka_na_testy(self):
        gh = ta.AtrapaGitHub(prs=[pr_z(mergeable_state="behind")], recenzje=[ta.recenzja()])
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=gh)
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "zaktualizowana")
        self.assertEqual((gh.aktualizacje, gh.scalone), ([7], []), "aktualizacja z main zamiast scalenia")
        gh.prs = [pr_z(mergeable_state="clean", sha="nowy")]          # po aktualizacji: nowy commit, CodeRabbit jeszcze nie zrecenzował
        gh.runy = [{"name": "testy", "status": "completed", "conclusion": "success"}, {"name": "CodeRabbit", "status": "in_progress", "conclusion": None}]
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "czekaj")
        gh.recenzje_lista = [ta.recenzja(commit="nowy")]
        gh.runy = None
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "scalone", "scalenie dopiero po ponownych testach i recenzji nowego commita")

    def test_c04_konflikt_z_main_lub_nieudana_aktualizacja_to_oddanie(self):
        gh = ta.AtrapaGitHub(prs=[pr_z(mergeable_state="dirty")], recenzje=[ta.recenzja()])
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=gh)
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oddane")
        self.assertIn("konflikt z main", w["powod"])
        gh2 = ta.AtrapaGitHub(prs=[pr_z(mergeable_state="behind")], recenzje=[ta.recenzja()], blad_aktualizacji="HTTP 422")
        w2 = agent_scal.uruchom_scalanie(ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=gh2))[0]
        self.assertEqual(w2["akcja"], "oddane")

    def test_c04_klient_github_ma_update_branch(self):
        wywolania = []
        import agent_github
        gh = agent_github.GitHub("token-testowy-123", "x/y")
        gh._zapytaj = lambda metoda, sciezka, dane=None, params=None: wywolania.append((metoda, sciezka))
        gh.aktualizuj_galaz(7)
        self.assertEqual(wywolania, [("PUT", "/pulls/7/update-branch")])


# ── c05. blokady a naprawy ────────────────────────────────────────────────────

KARTA_URLOP = {**ta.KARTA, "klient": "auto-tama", "zakazy": ta.KARTA["zakazy"] + [
    {"id": "Z5", "tytul": "Nic nowego nie startuje 19–23.10 (urlop Kasi)", "opis": "", "cytat": ["od dziewiętnastego do dwudziestego trzeciego mam urlop."]}]}


class C05Blokady(unittest.TestCase):

    def _s(self, zgloszenia, dzien, **kw):
        s = ta.Srodowisko(zgloszenia, karta=KARTA_URLOP, **kw)
        s.dzis = lambda: dzien
        return s

    def test_c05_blokada_rozpoznana_po_tytule_i_okresie(self):
        z5 = KARTA_URLOP["zakazy"][-1]
        self.assertTrue(zakazy_czas.czy_blokada(z5, Z))
        self.assertFalse(zakazy_czas.czy_blokada({"tytul": "Limit prób pozostaje 5"}, Z))
        self.assertEqual([z["id"] for z in zakazy_czas.aktywne_blokady(KARTA_URLOP, date(2026, 10, 20), "auto-tama", Z)], ["Z5"])
        self.assertEqual(zakazy_czas.aktywne_blokady(KARTA_URLOP, date(2026, 10, 18), "auto-tama", Z), [], "przed urlopem jeszcze nie blokuje")
        self.assertEqual(zakazy_czas.aktywne_blokady(KARTA_URLOP, date(2026, 10, 24), "auto-tama", Z), [], "po urlopie już nie")

    def test_c05_na_urlopie_poprawki_bledow_i_korekty_przechodza(self):
        for tytul, etykiety in (("Toruń podaje sobotę do 14:00 zamiast do 15:00", None), ("Błędne godziny otwarcia Sopot w piątek", ["Błąd", "Dla agenta", "repo: rinvo-app"]),
                                ("Aktualizacja godzin otwarcia salonu", None), ("Popraw adres salonu we Włocławku", None), ("Korekta limitu prób w konfiguracji", None)):
            s = self._s([ta.zgloszenie(41, tytul=tytul, etykiety=etykiety)], date(2026, 10, 20))
            self.assertEqual(agent.uruchom(s)[0]["status"], "pr", tytul)

    def test_c05_na_urlopie_nowe_kampanie_marki_funkcje_i_teksty_czekaja(self):
        for tytul in ("Uruchomić nową kampanię świeżych leadów", "Włączyć markę Opel we Włocławku", "Dodać nową funkcję eksportu", "Nowy tekst wstępu rozmowy dla Torunia"):
            s = self._s([ta.zgloszenie(41, tytul=tytul)], date(2026, 10, 20))
            w = agent.uruchom(s)[0]
            self.assertEqual(w["status"], "odlozone", tytul)
            self.assertIn("blokada Z5", w["powod"])
            self.assertIn("poprawki błędów nie są blokowane", w["powod"])
            self.assertEqual((s.linear.zdarzenia, s.git.wywolania), ([], []), "żadnych zmian w Linearze ani w repo")

    def test_c05_po_urlopie_nowe_rzeczy_ruszaja(self):
        s = self._s([ta.zgloszenie(41, tytul="Uruchomić nową kampanię świeżych leadów")], date(2026, 10, 24))
        self.assertEqual(agent.uruchom(s)[0]["status"], "pr")

    def test_c05_odlozone_nie_zuzywa_limitu_przebiegu(self):
        s = self._s([ta.zgloszenie(41, tytul="Nowa kampania", klient="a"), ta.zgloszenie(42, tytul="Błąd godzin", klient="b", etykiety=["Błąd", "Dla agenta", "repo: rinvo-app"])],
                    date(2026, 10, 20))
        self.assertEqual([w["status"] for w in agent.uruchom(s, max_n=1)], ["odlozone", "pr"])

    def test_c05_model_nie_dostaje_blokady_do_oceny_zakazow(self):
        s = self._s([ta.zgloszenie(41, tytul="Toruń podaje sobotę do 14:00")], date(2026, 10, 20))
        agent.uruchom(s)
        p = s.claude.pytania[0]
        self.assertNotIn("Nic nowego nie startuje", p, "blokady pilnuje kod, nie model")
        self.assertIn("Z4", p)

    def test_c05_regula_jest_w_zasadach_a_nie_w_kodzie(self):
        self.assertIn("nic nowego", Z["blokady"]["wzorce_zakazu"])
        self.assertIn("Błąd", Z["blokady"]["dozwolone_etykiety"])
        self.assertIn("kampani", Z["blokady"]["blokowane_slowa"])

    def test_c05_prawdziwa_karta_auto_tama_z5_blokuje_19_23_10(self):
        k = json.loads((ROOT / "testy/migawka_demo/ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        self.assertIn("Z5", [z["id"] for z in zakazy_czas.aktywne_blokady(k, date(2026, 10, 21), "auto-tama", Z, ROOT / "testy/migawka_demo")])


# ── c06. wygasające klucze ────────────────────────────────────────────────────

class C06Klucze(unittest.TestCase):

    def test_c06_data_z_naglowka_github(self):
        self.assertEqual(klucze.data_z_naglowka("2026-11-13 12:00:00 UTC"), date(2026, 11, 13))
        self.assertIsNone(klucze.data_z_naglowka(None))
        self.assertIsNone(klucze.data_z_naglowka("brak"))

    def test_c06_siedem_dni_przed_linijka_wczesniej_nic(self):
        dzis = date(2026, 11, 6)
        w = klucze.wygasajace(Z, "2026-11-13 12:00:00 UTC", dzis)
        self.assertEqual([(x["nazwa"], x["dni"]) for x in w], [("token GitHub agenta", 7)])
        self.assertEqual(klucze.wygasajace(Z, "2026-11-14 12:00:00 UTC", dzis), [], "8 dni przed: jeszcze cicho")
        self.assertIn("wygasa za 7 dni (13.11)", klucze.linie_uwagi(w)[0])

    def test_c06_wygasly_i_dzis_i_jutro(self):
        dzis = date(2026, 11, 6)
        l = klucze.linie_uwagi(klucze.wygasajace(Z, "2026-11-05 00:00:00 UTC", dzis))
        self.assertIn("wygasł 05.11", l[0])
        self.assertIn("wygasa dziś", klucze.linie_uwagi(klucze.wygasajace(Z, "2026-11-06 00:00:00 UTC", dzis))[0])
        self.assertIn("za 1 dzień", klucze.linie_uwagi(klucze.wygasajace(Z, "2026-11-07 00:00:00 UTC", dzis))[0])

    def test_c06_daty_pozostalych_sekretow_z_zasady_json(self):
        Z2 = copy.deepcopy(Z)
        Z2["klucze"]["daty"] = {"CLAUDE_CODE_OAUTH_TOKEN": "2026-11-10", "GMAIL_APP_PASSWORD": "2027-05-01"}
        w = klucze.wygasajace(Z2, None, date(2026, 11, 5))
        self.assertEqual([(x["nazwa"], x["dni"]) for x in w], [("CLAUDE_CODE_OAUTH_TOKEN", 5)])

    def test_c06_pobranie_naglowka_z_odpowiedzi_api_bez_sieci(self):
        class Odp:
            headers = {"github-authentication-token-expiration": "2026-11-13 12:00:00 UTC"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
        zapytania = []
        h = klucze.pobierz_naglowek_github("tajny-token-123456", "Rembolekk/Rinvo-app", otworz=lambda req, timeout=None: (zapytania.append(req), Odp())[1])
        self.assertEqual(h, "2026-11-13 12:00:00 UTC")
        self.assertIn("/repos/Rembolekk/Rinvo-app", zapytania[0].full_url)
        self.assertIsNone(klucze.pobierz_naglowek_github("", "x/y"))
        self.assertIsNone(klucze.pobierz_naglowek_github("t", "x/y", otworz=lambda req, timeout=None: (_ for _ in ()).throw(OSError("brak sieci"))))

    def test_c06_linijka_trafia_do_uwagi_w_podsumowaniu(self):
        dane = {"human": [], "uwaga": [], "szkice": [], "eskalacje": [], "klucze_uwaga": klucze.linie_uwagi(klucze.wygasajace(Z, "2026-11-13 00:00:00 UTC", date(2026, 11, 6))),
                "agenci_otwarte": 0, "agenci_skonczone": 0, "czeka_n": 0, "czeka_najblizsze": None, "nowe_n": 0, "widok": None, "strony_url": None}
        tekst, bloki = podsumowanie.buduj_wiadomosc(dane, date(2026, 11, 6))
        self.assertIn("*Uwaga*", tekst)
        self.assertIn("wygasa za 7 dni", tekst)
        dane["klucze_uwaga"] = []
        self.assertNotIn("*Uwaga*", podsumowanie.buduj_wiadomosc(dane, date(2026, 11, 6))[0], "bez kluczy i bez spraw Uwagi nie ma")

    def test_c06_token_nie_trafia_do_wiadomosci_ani_logow(self):
        kod = (ROOT / "klucze.py").read_text(encoding="utf-8")
        self.assertNotIn("print(", kod)
        self.assertIn("AGENT_GITHUB_TOKEN", (ROOT / ".github/workflows/podsumowanie.yml").read_text(encoding="utf-8"))


# ── c07. limity i kredyty modelu ──────────────────────────────────────────────

class FakeProces:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


class C07Limity(Tmp):

    def test_c07_wzorce_limitu_i_brak_falszywych_trafien(self):
        for t in ("Claude AI usage limit reached|1761", "You have reached your usage limit. Limit will reset at 5pm", "Error: 429 Too Many Requests",
                  "Your credit balance is too low to access the API", "overloaded_error", "rate limit exceeded"):
            self.assertTrue(limity.czy_limit(t, Z), t)
        for t in ("OK", "Zmieniłem godziny salonu.", "limit prób pozostaje 5", "Błąd 500"):
            self.assertFalse(limity.czy_limit(t, Z), t)

    def _claude(self, proces, kolejka=None, budzet=None):
        o = agent_srodowisko.subprocess.run
        agent_srodowisko.subprocess.run = lambda *a, **kw: proces
        self.addCleanup(setattr, agent_srodowisko.subprocess, "run", o)
        return agent_srodowisko.ClaudeAgent("m", budzet, "agent", kolejka, Z)

    def test_c07_blad_limitu_z_claude_to_wyjatek_limitu_a_inny_blad_nie(self):
        c = self._claude(FakeProces(1, "", "Claude AI usage limit reached"))
        with self.assertRaises(limity.LimitModelu):
            c.zapytaj("x")
        with self.assertRaises(limity.LimitModelu):
            c.edytuj(self.root, "x")
        c2 = self._claude(FakeProces(1, "", "Segmentation fault"))
        with self.assertRaises(RuntimeError) as ctx:
            c2.zapytaj("x")
        self.assertNotIsInstance(ctx.exception, limity.LimitModelu)

    def test_c07_agent_odklada_zadanie_do_kolejki_bez_oddania_i_bez_zuzycia_proby(self):
        kolejka = limity.Kolejka(self.root / "kolejka.json")

        class ClaudeLimit(ta.AtrapaClaude):
            def edytuj(self, katalog, prompt):
                raise limity.LimitModelu("usage limit reached")

        s = ta.Srodowisko([ta.zgloszenie(41, klient="a"), ta.zgloszenie(42, klient="b")], claude=ClaudeLimit())
        s.kolejka = kolejka
        w = agent.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["oczekuje_na_limit"], "limit kończy przebieg: kolejne zadania nie próbują")
        zg = s.linear.zgloszenia[0]
        self.assertEqual(zg["state"], "Todo", "wraca do Todo")
        self.assertNotIn("Do weryfikacji", zg["labels"], "to nie jest nieudana próba")
        self.assertNotIn(("stan", "RIN-41", "Todo"), [z for z in s.linear.zdarzenia if z[0] == "komentarz"])
        self.assertEqual(kolejka.lista(), ["RIN-41"])
        self.assertEqual(len(s.slack.wiadomosci), 1)
        self.assertIn("oczekuje na limit", s.slack.wiadomosci[0])
        self.assertFalse(any("oddał" in m for m in s.slack.wiadomosci))

    def test_c07_jedna_informacja_na_epizod_ponowienie_przy_nastepnym_przebiegu(self):
        kolejka = limity.Kolejka(self.root / "kolejka.json")

        class ClaudeLimit(ta.AtrapaClaude):
            def edytuj(self, katalog, prompt):
                raise limity.LimitModelu("limit")

        s = ta.Srodowisko([ta.zgloszenie(41)], claude=ClaudeLimit())
        s.kolejka = kolejka
        agent.uruchom(s)
        agent.uruchom(s)
        self.assertEqual(len(s.slack.wiadomosci), 1, "drugi przebieg w tym samym epizodzie: bez drugiej wiadomości")
        # limit minął: model działa, zadanie jest przejmowane normalnie (nie utknęło)
        s2 = ta.Srodowisko([ta.zgloszenie(41)])
        s2.kolejka = kolejka
        self.assertEqual(agent.uruchom(s2)[0]["status"], "pr")
        kolejka.sukces()
        self.assertTrue(kolejka.powiadom_raz(), "po udanym wywołaniu nowy epizod znów da jedną informację")

    def test_c07_udane_wywolanie_zamyka_epizod(self):
        kolejka = limity.Kolejka(self.root / "k.json")
        self.assertTrue(kolejka.powiadom_raz())
        self.assertFalse(kolejka.powiadom_raz())
        c = self._claude(FakeProces(0, "OK"), kolejka)
        c.zapytaj("x")
        self.assertTrue(kolejka.powiadom_raz())

    def test_c07_limit_przy_sprawdzaniu_zakazow_to_kolejka_a_nie_niepewne_pominiecie(self):
        class ClaudeLimit(ta.AtrapaClaude):
            def zapytaj(self, prompt):
                raise limity.LimitModelu("limit")

        s = ta.Srodowisko([ta.zgloszenie(41)], claude=ClaudeLimit())
        self.assertEqual(agent.uruchom(s)[0]["status"], "oczekuje_na_limit")

    def test_c07_limit_w_scalaniu_przy_poprawce_coderabbit(self):
        class ClaudeLimit(ta.AtrapaClaude):
            def edytuj(self, katalog, prompt):
                raise limity.LimitModelu("limit")

        inline = [{"pull_request_review_id": 1, "path": "config/a.yaml", "line": 1, "body": "Błąd"}]
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], claude=ClaudeLimit(),
                          github=ta.AtrapaGitHub(prs=[ta.pr()], recenzje=[ta.recenzja(uwagi=1)], inline=inline))
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oczekuje_na_limit")
        self.assertFalse(any(agent_scal.ZNACZNIK_POPRAWKI in k[1] for k in s.github.dodane_komentarze), "poprawka nie została „zużyta”")

    def test_c07_przetworz_odklada_zadanie_i_cofa_probe_maila(self):
        kod = (ROOT / "przetworz.py").read_text(encoding="utf-8")
        self.assertIn("limity.czy_limit(tail_log(log_path, 40), Zl)", kod)
        self.assertIn("cofnij_probe(transkrypcja)", kod)
        self.assertIn("sys.exit(limity_kod_wyjscia)", kod)
        self.assertEqual(Z["limity_modelu"]["kod_wyjscia"], 75)
        for wf in ("przetworz-rozmowy", "sprawdz-maile"):
            self.assertIn('"$RC" -eq 75', (ROOT / f".github/workflows/{wf}.yml").read_text(encoding="utf-8"), wf)

    def test_c07_cofnij_probe_maila(self):
        self.zapisz("ops/.maile.json", {"przetworzone": {}, "nieznani": {}, "oczekujace": {"<a>": {"klient": "alfa", "plik": "ops/maile/alfa/2026-10-14-x.md", "proby": 2, "status": "oczekuje"}}})
        self.assertTrue(maile.cofnij_probe("ops/maile/alfa/2026-10-14-x.md"))
        self.assertEqual(json.loads((self.root / "ops/.maile.json").read_text(encoding="utf-8"))["oczekujace"]["<a>"]["proby"], 1)
        self.assertFalse(maile.cofnij_probe("ops/maile/alfa/inny.md"))

    def test_c07_rozmowy_czekajace_na_limit_wracaja_na_liste(self):
        kolejka = limity.Kolejka(limity.PLIK_KOLEJKI)
        self.zapisz("ops/transkrypcje/alfa/2026-10-14-call.md", "# x")
        kolejka.dodaj("ops/transkrypcje/alfa/2026-10-14-call.md")
        kolejka.dodaj("ops/transkrypcje/alfa/nie-istnieje.md")
        lista = self.zapisz("lista.txt", "ops/transkrypcje/alfa/inna.md\n")
        sys.argv = ["limity.py", "--dopisz-kolejke", str(lista)]
        with contextlib.redirect_stdout(io.StringIO()):
            limity.main()
        self.assertEqual(lista.read_text(encoding="utf-8").split(), ["ops/transkrypcje/alfa/inna.md", "ops/transkrypcje/alfa/2026-10-14-call.md"])


# ── c08. bezpiecznik kosztów ──────────────────────────────────────────────────

class C08Budzet(Tmp):

    def _b(self, razem=3, agent_=2, dzien=date(2026, 10, 14)):
        Z2 = copy.deepcopy(Z)
        Z2["budzet_modelu"] = {"dziennie_razem": razem, "dziennie_agent": agent_}
        return limity.Budzet(Z2, self.root / "zuzycie.json", dzien), Z2

    def test_c08_limit_razem_zatrzymuje_i_nie_liczy_odrzuconego_wywolania(self):
        b, _ = self._b(razem=3)
        for _ in range(3):
            b.zuzyj("inne")
        with self.assertRaises(limity.BudzetWyczerpany) as ctx:
            b.zuzyj("inne")
        self.assertEqual(ctx.exception.zakres, "razem")
        self.assertEqual(b.zuzycie()["razem"], 3)

    def test_c08_osobny_limit_agenta_inne_wywolania_dalej_dzialaja(self):
        b, _ = self._b(razem=10, agent_=2)
        b.zuzyj("agent"); b.zuzyj("agent")
        with self.assertRaises(limity.BudzetWyczerpany) as ctx:
            b.zuzyj("agent")
        self.assertEqual(ctx.exception.zakres, "agent")
        b.zuzyj("inne")                                   # analiza rozmów, szkice, notatki: nie dotyczy limitu agenta
        self.assertEqual(b.zuzycie(), {**b.zuzycie(), "razem": 3, "agent": 2})

    def test_c08_agent_liczy_sie_do_obu_limitow(self):
        b, _ = self._b(razem=2, agent_=5)
        b.zuzyj("agent"); b.zuzyj("inne")
        with self.assertRaises(limity.BudzetWyczerpany) as ctx:
            b.zuzyj("agent")
        self.assertEqual(ctx.exception.zakres, "razem")

    def test_c08_nastepnego_dnia_liczniki_od_zera(self):
        b, Z2 = self._b(razem=1)
        b.zuzyj("inne")
        jutro = limity.Budzet(Z2, self.root / "zuzycie.json", date(2026, 10, 15))
        jutro.zuzyj("inne")
        self.assertEqual(jutro.zuzycie()["razem"], 1)
        self.assertEqual(jutro.zuzycie()["data"], "2026-10-15")

    def test_c08_alert_raz_dziennie_na_zakres(self):
        b, Z2 = self._b()
        self.assertTrue(b.alert_potrzebny("razem"))
        self.assertFalse(b.alert_potrzebny("razem"))
        self.assertTrue(b.alert_potrzebny("agent"))
        self.assertTrue(limity.Budzet(Z2, self.root / "zuzycie.json", date(2026, 10, 15)).alert_potrzebny("razem"), "jutro znów wolno ostrzec")

    def test_c08_claude_agent_liczy_wywolania_i_zatrzymuje_przed_wywolaniem(self):
        b, Z2 = self._b(razem=2)
        wywolania = []
        o = agent_srodowisko.subprocess.run
        agent_srodowisko.subprocess.run = lambda *a, **kw: (wywolania.append(1), FakeProces(0, "OK"))[1]
        self.addCleanup(setattr, agent_srodowisko.subprocess, "run", o)
        c = agent_srodowisko.ClaudeAgent("m", b, "inne", None, Z2)
        c.zapytaj("a"); c.zapytaj("b")
        with self.assertRaises(limity.BudzetWyczerpany):
            c.zapytaj("c")
        self.assertEqual(len(wywolania), 2, "trzecie wywołanie nie wyszło do modelu")

    def test_c08_agent_zatrzymuje_sie_alert_raz_dalej_nastepnego_dnia(self):
        b, Z2 = self._b(razem=10, agent_=1)
        s = ta.Srodowisko([ta.zgloszenie(41, klient="a"), ta.zgloszenie(42, klient="b")])
        s.Z = Z2
        s.budzet = b
        s.claude = agent_srodowisko.ClaudeAgent("m", b, "agent", None, Z2)
        o = agent_srodowisko.subprocess.run
        agent_srodowisko.subprocess.run = lambda *a, **kw: FakeProces(0, '{"konflikt": false, "zakaz": null, "powod": ""}')
        self.addCleanup(setattr, agent_srodowisko.subprocess, "run", o)
        w = agent.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["budzet"], "pierwsze wywołanie (sprawdzenie zakazów) zużyło budżet agenta")
        self.assertEqual(s.linear.zgloszenia[0]["state"], "Todo")
        self.assertEqual(len(s.slack.wiadomosci), 1)
        self.assertIn("Dzienny limit wywołań modelu (dla agenta) wyczerpany", s.slack.wiadomosci[0])
        agent.uruchom(s)
        self.assertEqual(len(s.slack.wiadomosci), 1, "alert raz dziennie")

    def test_c08_limity_w_zasadach(self):
        self.assertGreater(Z["budzet_modelu"]["dziennie_razem"], Z["budzet_modelu"]["dziennie_agent"])

    def test_c08_przetworz_sprawdza_budzet_przed_modelem(self):
        kod = (ROOT / "przetworz.py").read_text(encoding="utf-8")
        self.assertLess(kod.index('budzet.zuzyj("inne")'), kod.index("claude_cmd,"), "bezpiecznik przed uruchomieniem modelu")
        for wf in ("przetworz-rozmowy", "sprawdz-maile", "agent", "podsumowanie"):
            self.assertIn("ops/.zuzycie_modelu.json", (ROOT / f".github/workflows/{wf}.yml").read_text(encoding="utf-8"), wf)


# ── c09. eskalacja decyzji człowieka ──────────────────────────────────────────

def zgl_czlowiek(ident, zmiana, tytul="Decyzja o Oplu", klient="alfa", etykiety=("Decyzja człowieka",)):
    return {"id": "i" + ident, "identifier": ident, "url": f"https://linear.app/x/{ident}", "title": f"[{klient}] {tytul}", "createdAt": "2026-10-01T10:00:00Z",
            "updatedAt": zmiana, "dueDate": None, "state": {"name": "Todo", "type": "unstarted"}, "labels": {"nodes": [{"name": n} for n in etykiety]}}


class C09Eskalacja(unittest.TestCase):

    KARTY = {"alfa": {"klient": "alfa", "otwarte_sprawy": {}, "zakazy": []}}

    def test_c09_dni_robocze_bez_weekendow_i_swiat(self):
        self.assertEqual(podsumowanie.dni_robocze(date(2026, 10, 9), date(2026, 10, 12)), 1, "piątek → poniedziałek")
        self.assertEqual(podsumowanie.dni_robocze(date(2026, 10, 12), date(2026, 10, 14)), 2)
        self.assertEqual(podsumowanie.dni_robocze(date(2026, 11, 10), date(2026, 11, 12), ["2026-11-11"]), 1, "11.11 to święto")
        self.assertEqual(podsumowanie.dni_robocze(date(2026, 10, 14), date(2026, 10, 14)), 0)

    def test_c09_ponad_dwa_dni_robocze_bez_reakcji_idzie_na_gore(self):
        dzis = date(2026, 10, 14)                                 # środa
        otwarte = [zgl_czlowiek("RIN-1", "2026-10-09T10:00:00Z"),      # piątek → środa = 3 dni robocze: eskalacja
                   zgl_czlowiek("RIN-2", "2026-10-12T10:00:00Z"),      # poniedziałek → środa = 2: jeszcze nie
                   zgl_czlowiek("RIN-3", "2026-10-09T10:00:00Z", etykiety=("Dla agenta",))]
        e = podsumowanie.eskalacje(otwarte, self.KARTY, Z, dzis)
        self.assertEqual([(x["z"]["identifier"], x["dni"]) for x in e], [("RIN-1", 3)])

    def test_c09_reakcja_czyli_zmiana_w_zgloszeniu_zeruje_licznik(self):
        e = podsumowanie.eskalacje([zgl_czlowiek("RIN-1", "2026-10-14T08:00:00Z")], self.KARTY, Z, date(2026, 10, 14))
        self.assertEqual(e, [])

    def test_c09_wiadomosc_ma_eskalacje_na_samej_gorze_z_liczba_dni_i_bez_powtorki(self):
        dzis = date(2026, 10, 14)
        otwarte = [zgl_czlowiek("RIN-1", "2026-10-09T10:00:00Z"), zgl_czlowiek("RIN-2", "2026-10-13T10:00:00Z", tytul="Nowa decyzja")]
        dane = podsumowanie.przygotuj(otwarte, [], self.KARTY, Z, dzis)
        tekst, bloki = podsumowanie.buduj_wiadomosc(dane, dzis)
        sekcje = [b["text"]["text"] for b in bloki if b["type"] == "section"]
        self.assertTrue(sekcje[0].startswith("*Czeka najdłużej na Twoją decyzję*"), sekcje[0])
        self.assertIn("czeka 3 dni roboczych", sekcje[0])
        self.assertIn("RIN-1", sekcje[0])
        self.assertEqual(tekst.count("/RIN-1"), 1 if "/issue/RIN-1" in tekst else tekst.count("/RIN-1"))
        wymaga = next(s for s in sekcje if s.startswith("*Wymaga człowieka*"))
        self.assertNotIn("Decyzja o Oplu", wymaga, "eskalowana sprawa nie powtarza się w zwykłej liście")
        self.assertIn("Nowa decyzja", wymaga)

    def test_c09_bez_eskalacji_wiadomosc_jak_dotad(self):
        dzis = date(2026, 10, 14)
        dane = podsumowanie.przygotuj([zgl_czlowiek("RIN-2", "2026-10-13T10:00:00Z")], [], self.KARTY, Z, dzis)
        self.assertNotIn("Czeka najdłużej", podsumowanie.buduj_wiadomosc(dane, dzis)[0])

    def test_c09_ponad_piec_dni_osobna_wiadomosc_raz(self):
        dzis = date(2026, 10, 14)
        otwarte = [zgl_czlowiek("RIN-1", "2026-10-02T10:00:00Z"), zgl_czlowiek("RIN-2", "2026-10-09T10:00:00Z")]       # 8 i 3 dni robocze
        dane = podsumowanie.przygotuj(otwarte, [], self.KARTY, Z, dzis)
        stan, wyslane = {}, []
        wysylacz = lambda tekst: (wyslane.append(tekst), (True, None))[1]            # noqa: E731
        nowe = podsumowanie.eskalacje_osobne(dane, stan, Z, wysylacz)
        self.assertEqual(nowe, ["RIN-1"], "RIN-2 ma 3 dni: tylko na górze podsumowania")
        self.assertIn("8 dni roboczych", wyslane[0])
        self.assertEqual(stan["eskalowane"], ["RIN-1"])
        self.assertEqual(podsumowanie.eskalacje_osobne(dane, stan, Z, wysylacz), [], "raz")
        self.assertEqual(len(wyslane), 1)

    def test_c09_nieudana_wysylka_nie_oznacza_jako_wyslanej(self):
        dane = podsumowanie.przygotuj([zgl_czlowiek("RIN-1", "2026-10-02T10:00:00Z")], [], self.KARTY, Z, date(2026, 10, 14))
        stan = {}
        self.assertEqual(podsumowanie.eskalacje_osobne(dane, stan, Z, lambda t: (False, "blad")), [])
        self.assertEqual(stan["eskalowane"], [])
        self.assertEqual(podsumowanie.eskalacje_osobne(dane, stan, Z, lambda t: (True, None)), ["RIN-1"], "następny przebieg spróbuje ponownie")

    def test_c09_progi_w_zasadach(self):
        self.assertEqual((Z["eskalacja"]["dni_do_gory"], Z["eskalacja"]["dni_osobna_wiadomosc"]), (2, 5))
        self.assertIn("updatedAt", podsumowanie._POLA)


# ── README i spójność ─────────────────────────────────────────────────────────

class TestSpojnosc(unittest.TestCase):

    def test_readme_ma_przypadki_c01_c09_w_tabeli(self):
        r = "".join((ROOT / d).read_text(encoding="utf-8") for d in ("README.md", "docs/SZCZEGOLY.md", "docs/PRZYPADKI-BRZEGOWE.md"))
        for nr in range(1, 10):
            self.assertIn(f"c{nr:02d}_", r, f"test punktu {nr} wymieniony w README")

    def test_kazdy_punkt_ma_test(self):
        kod = Path(__file__).read_text(encoding="utf-8")
        for nr in range(1, 10):
            self.assertIn(f"def test_c{nr:02d}_", kod)

    def test_workflowy_commituja_stan_utwardzania(self):
        for wf in ("przetworz-rozmowy", "sprawdz-maile", "agent", "podsumowanie"):
            t = (ROOT / f".github/workflows/{wf}.yml").read_text(encoding="utf-8")
            for plik in ("ops/.reczne_zmiany.json", "ops/.zmiany_automatu.json", "ops/.kolejka_limit.json"):
                self.assertIn(plik, t, f"{wf}: {plik}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
