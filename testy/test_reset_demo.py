#!/usr/bin/env python3
"""test_reset_demo.py – reset_demo.py (próba generalna od czystego stanu), bez sieci: Linear i GitHub to atrapy, repozytoria git są tymczasowe.

Uruchomienie: python3 testy/test_reset_demo.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import reset_demo as rd

KARTA = {
    "klient": "auto-tama", "nazwa": "Grupa Auto Tama", "domeny": ["autotama.pl"],
    "decydenci": [{"imie": "Kasia Malinowska", "rola": "BDC"}, {"imie": "Paweł", "rola": "przełożony"}],
    "kontakty": [{"imie": "Kasia Malinowska", "email": "kasia@autotama.pl", "rola": "BDC, kontakt główny", "zakres_decyzji": "ustala zakazy i terminy",
                  "potwierdzony": True, "status": "potwierdzony",
                  "nieobecnosci": [{"od": "2026-10-19", "do": "2026-10-23", "zrodlo": "x.md", "cytat": "urlop"}]},
                 {"imie": "Paweł", "email": "pawel@autotama.pl", "potwierdzony": False}],
    "zakazy": [{"id": "Z1", "tytul": "Limit prób 5"}], "zakazy_wygasle": [{"id": "Z11"}], "historia_zakazow": [{"id": "Z2"}],
    "otwarte_sprawy": {"x": {"identifier": "RIN-1"}}, "zamkniete_sprawy": {"y": {"identifier": "RIN-2"}}, "ryzyka": {"konkurencja": [{"cytat": "c"}]},
    "decyzje_zastrzezone": [{"opis": "Opel"}], "historia_wysylek": [{"hash": "h"}], "zalozenia_demo": [{"temat": "t"}],
}


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)
        self._t.cleanup()

    def zapisz(self, sciezka, tresc="x"):
        p = self.root / sciezka
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(tresc if isinstance(tresc, str) else json.dumps(tresc, ensure_ascii=False), encoding="utf-8")
        return p

    def repo_roboczy(self):
        """Rinvo w miniaturze: wygenerowany stan, transkrypcje, karty."""
        for s in ("wyniki/auto-tama/a/wynik.json", "wyniki/klinika-usmiech/b/wynik.json", "ops/materialy/auto-tama/n.md", "ops/maile/auto-tama/m.md",
                  "logi/przebiegi/1.log", "ops/.stan_linear.json", "ops/.zdarzenia.json", "ops/.sygnaly.json", "ops/.reczne_zmiany.json",
                  "ops/.zmiany_automatu.json", "ops/.zuzycie_modelu.json", "ops/.kolejka_limit.json", "ops/.podsumowanie.json",
                  "ops/produkt/propozycje.json", "klienci/klinika-usmiech.html", "klienci/auto-tama.html"):
            self.zapisz(s)
        self.zapisz("ops/.maile.json", {"przetworzone": {"<a>": {}}, "nieznani": {"x": {}}, "oczekujace": {"<b>": {}}, "wlaczono": "2026-10-14"})
        self.zapisz("ops/.przetworzone.json", {"abc": {"klient": "auto-tama"}})
        self.zapisz("ops/produkt/prosby.json", {"f": {"tytul": "F", "prosby": []}})
        self.zapisz("ops/klienci/auto-tama/karta.json", KARTA)
        self.zapisz("ops/klienci/klinika-usmiech/karta.json", {"klient": "klinika-usmiech"})
        self.zapisz("ops/transkrypcje/auto-tama/2026-10-06-call.md", "t1")
        self.zapisz("ops/transkrypcje/auto-tama/2026-10-13-call.md", "t2")
        self.zapisz("ops/transkrypcje/klinika-usmiech/2026-10-13-call.md", "t3")
        self.zapisz("ops/widok_dla_mnie.json", {"url": "https://linear.app/ws/view/x"})
        self.zapisz("ops/zasady.json", "{}")


class TestPlan(unittest.TestCase):

    def test_bez_flagi_tak_tylko_plan_i_nic_sie_nie_zmienia(self):
        przed = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        r = subprocess.run([sys.executable, "reset_demo.py"], cwd=ROOT, capture_output=True, text=True)
        po = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertEqual(r.returncode, 2)
        self.assertIn("--tak", r.stdout)
        self.assertIn("archiwizacja wszystkich zgłoszeń zespołu RIN", r.stdout)
        self.assertEqual(przed, po)


class TestLinear(unittest.TestCase):

    def test_archiwizuje_wszystkie_zgloszenia_ze_stronicowaniem_i_nie_rusza_etykiet(self):
        wywolania = []

        def gql(k, q, v=None):
            wywolania.append((q, v))
            if "issueArchive" in q:
                return {}
            if 'after: "c1"' in q:
                return {"issues": {"nodes": [{"id": "i3", "identifier": "RIN-3"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
            return {"issues": {"nodes": [{"id": "i1", "identifier": "RIN-1"}, {"id": "i2", "identifier": "RIN-2"}],
                               "pageInfo": {"hasNextPage": True, "endCursor": "c1"}}}
        self.assertEqual(rd.archiwizuj_zgloszenia("k", gql), 3)
        archiwa = [v["id"] for q, v in wywolania if "issueArchive" in q]
        self.assertEqual(archiwa, ["i1", "i2", "i3"])
        tekst = " ".join(q for q, _ in wywolania)
        self.assertNotIn("issueLabel", tekst)
        self.assertNotIn("customView", tekst)
        self.assertNotIn("issueDelete", tekst, "archiwizacja, nie usuwanie")


class TestPliki(Tmp):

    def test_karta_minimalna_ma_tylko_konfiguracje_spoza_rozmow(self):
        k = rd.karta_minimalna(KARTA)
        self.assertEqual(k["nazwa"], "Grupa Auto Tama")
        self.assertEqual(k["domeny"], ["autotama.pl"])
        self.assertEqual(len(k["kontakty"]), 1)
        kasia = k["kontakty"][0]
        self.assertEqual((kasia["imie"], kasia["potwierdzony"], kasia["zakres_decyzji"]), ("Kasia Malinowska", True, "ustala zakazy i terminy"))
        self.assertNotIn("nieobecnosci", kasia)
        self.assertEqual(k["decydenci"], [{"imie": "Kasia Malinowska", "rola": "BDC, kontakt główny"}])
        self.assertEqual((k["zakazy"], k["otwarte_sprawy"]), ([], {}))
        for pole in ("zakazy_wygasle", "historia_zakazow", "zamkniete_sprawy", "ryzyka", "decyzje_zastrzezone", "historia_wysylek", "zalozenia_demo"):
            self.assertNotIn(pole, k)

    def test_reset_kart_zostawia_auto_tama_i_usuwa_karte_kliniki(self):
        self.repo_roboczy()
        zostalo, usuniete = rd.reset_kart(self.root)
        self.assertEqual((zostalo, usuniete), (["auto-tama"], ["klinika-usmiech"]))
        self.assertFalse((self.root / "ops/klienci/klinika-usmiech").exists())
        k = json.loads((self.root / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        self.assertEqual(k["zakazy"], [])
        self.assertNotIn("ryzyka", k)

    def test_transkrypcje_ida_poza_sciezke_wyzwalajaca_workflow(self):
        self.repo_roboczy()
        ruchy = rd.przenies_transkrypcje(self.root)
        self.assertEqual(len(ruchy), 3)
        self.assertTrue((self.root / "proba/transkrypcje/auto-tama/2026-10-06-call.md").exists())
        self.assertTrue((self.root / "proba/transkrypcje/auto-tama/2026-10-13-call.md").exists())
        self.assertTrue((self.root / "proba/archiwum/klinika-usmiech/2026-10-13-call.md").exists())
        self.assertEqual(list((self.root / "ops").glob("transkrypcje/**/*.md")), [], "nic, co uruchamia workflow")
        self.assertFalse(Path("proba/transkrypcje/auto-tama/x.md").match("ops/transkrypcje/**/*.md"))
        wf = (ROOT / ".github/workflows/przetworz-rozmowy.yml").read_text(encoding="utf-8")
        self.assertIn('"ops/transkrypcje/**/*.md"', wf)
        self.assertEqual(rd.przenies_transkrypcje(self.root), [], "drugi raz nic do przeniesienia")

    def test_reset_stanu_usuwa_wygenerowane_i_pisze_puste_rejestry(self):
        self.repo_roboczy()
        usuniete = rd.reset_stanu(self.root, date(2026, 10, 15))
        for s in ("wyniki", "ops/materialy", "ops/maile", "ops/.stan_linear.json", "ops/.zdarzenia.json", "ops/.reczne_zmiany.json", "ops/.zmiany_automatu.json",
                  "ops/.zuzycie_modelu.json", "ops/.kolejka_limit.json", "ops/.podsumowanie.json", "ops/produkt/propozycje.json", "klienci"):
            self.assertFalse((self.root / s).exists(), s)
            self.assertIn(s, usuniete)
        self.assertEqual(list((self.root / "logi/przebiegi").glob("*.log")), [])
        m = json.loads((self.root / "ops/.maile.json").read_text(encoding="utf-8"))
        self.assertEqual(m, {"przetworzone": {}, "nieznani": {}, "oczekujace": {}, "wlaczono": "2026-10-15"})
        self.assertEqual(json.loads((self.root / "ops/.przetworzone.json").read_text(encoding="utf-8")), {})
        self.assertEqual(json.loads((self.root / "ops/produkt/prosby.json").read_text(encoding="utf-8")), {})
        self.assertEqual(json.loads((self.root / "ops/.sygnaly.json").read_text(encoding="utf-8")), {"widziane": []})
        self.assertTrue((self.root / "ops/widok_dla_mnie.json").exists(), "widok zostaje")
        self.assertTrue((self.root / "ops/zasady.json").exists())

    def test_data_wlaczenia_maili_odcina_stare_maile(self):
        import maile
        self.assertEqual(maile.okno_od(date(2026, 10, 15), 30, "2026-10-15"), date(2026, 10, 15))

    def test_puste_strony_po_resecie(self):
        """Reset na kopii prawdziwych danych: strony generują się bez błędu i bez klienta, którego karta zniknęła."""
        import shutil
        kopia = self.root / "kopia"
        shutil.copytree(ROOT / "ops", kopia / "ops")
        shutil.copytree(ROOT / "wyniki", kopia / "wyniki") if (ROOT / "wyniki").exists() else None
        os.chdir(kopia)
        rd.przenies_transkrypcje(kopia)
        rd.reset_kart(kopia)
        rd.reset_stanu(kopia, date(2026, 10, 15))
        import generuj_strony as gs
        strony = gs.buduj(gs.wczytaj_dane(".", date(2026, 10, 15)))
        self.assertIn("klienci/auto-tama.html", strony)
        self.assertNotIn("klienci/klinika-usmiech.html", strony)
        self.assertIn("Brak sygnałów wartych decyzji", strony["glos-klientow.html"])


class TestApp(Tmp):

    def git(self, cwd, *a):
        r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    CONFIG_PRZED = 'sobota: {od: "09:00", do: "14:00"}\ngodziny_dzwonienia_do: "20:00"\n'
    CONFIG_PO = 'sobota: {od: "09:00", do: "15:00"}\ngodziny_dzwonienia_do: "19:00"\n'

    def zrob_repo(self):
        origin = self.root / "origin.git"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        app = self.root / "app"
        self.git(self.root, "clone", "-q", str(origin), str(app))
        self.git(app, "checkout", "-q", "-b", "main")
        (app / "config").mkdir()
        (app / "wiedza").mkdir()
        (app / "config/auto-tama.yaml").write_text(self.CONFIG_PRZED, encoding="utf-8")
        (app / "wiedza/auto-tama.md").write_text("- Sobota: 9:00–14:00\n", encoding="utf-8")
        self.git(app, "add", "-A")
        self.git(app, "commit", "-q", "-m", "baza")
        baza = self.git(app, "rev-parse", "HEAD")
        self.git(app, "push", "-q", "origin", "main")
        # poprawki agenta: zmiany plików, nowy plik, gałąź agenta scalona
        self.git(app, "checkout", "-q", "-b", "rin-41-sobota")
        (app / "config/auto-tama.yaml").write_text(self.CONFIG_PO, encoding="utf-8")
        (app / "wiedza/auto-tama.md").write_text("- Sobota: 9:00–15:00\n", encoding="utf-8")
        (app / "wiedza/nowy.md").write_text("nowy plik agenta\n", encoding="utf-8")
        self.git(app, "add", "-A")
        self.git(app, "commit", "-q", "-m", "poprawka agenta")
        self.git(app, "push", "-q", "origin", "rin-41-sobota")
        self.git(app, "checkout", "-q", "main")
        self.git(app, "merge", "-q", "--no-ff", "rin-41-sobota", "-m", "merge")
        self.git(app, "push", "-q", "origin", "main")
        return app, origin, baza

    def test_reset_app_przywraca_config_i_wiedze_commit_na_main_i_push(self):
        app, origin, baza = self.zrob_repo()
        w = rd.reset_app(app, baza)
        self.assertEqual(sorted(w["zmienione"]), ["config/auto-tama.yaml", "wiedza/auto-tama.md", "wiedza/nowy.md"])
        self.assertTrue(w["commit"])
        self.assertEqual((app / "config/auto-tama.yaml").read_text(encoding="utf-8"), self.CONFIG_PRZED)
        self.assertEqual((app / "wiedza/auto-tama.md").read_text(encoding="utf-8"), "- Sobota: 9:00–14:00\n")
        self.assertFalse((app / "wiedza/nowy.md").exists(), "plik dodany później też znika")
        zdalny = self.git(self.root, "--git-dir", str(origin), "show", "main:config/auto-tama.yaml")
        self.assertEqual(zdalny + "\n", self.CONFIG_PRZED, "push na main")
        self.assertEqual(self.git(app, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertIn("rin-41-sobota", w["galezie"], "scalona gałąź agenta usunięta ze zdalnego")
        self.assertNotIn("rin-41-sobota", self.git(self.root, "--git-dir", str(origin), "branch"))

    def test_reset_app_drugi_raz_niczego_nie_zmienia(self):
        app, origin, baza = self.zrob_repo()
        rd.reset_app(app, baza)
        w = rd.reset_app(app, baza)
        self.assertEqual((w["zmienione"], w["commit"]), ([], None))

    def test_baza_ktora_nie_jest_stanem_sprzed_poprawek_jest_odrzucona(self):
        app, origin, baza = self.zrob_repo()
        po_poprawkach = self.git(app, "rev-parse", "HEAD")
        with self.assertRaises(RuntimeError) as ctx:
            rd.reset_app(app, po_poprawkach)
        self.assertIn("nie wygląda na stan sprzed poprawek agenta", str(ctx.exception))
        self.assertEqual((app / "config/auto-tama.yaml").read_text(encoding="utf-8"), self.CONFIG_PO, "nic nie zmieniono")

    def test_prawdziwa_baza_to_stan_sprzed_poprawek(self):
        app = ROOT.parent / "Rinvo-app"
        if not app.exists():
            self.skipTest("brak lokalnego klona Rinvo-app")
        rd.sprawdz_baze(app, "b2556d6")


class TestPR(unittest.TestCase):

    class Odp:
        def __init__(self, dane):
            self.dane = dane

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.dane).encode("utf-8")

    def test_lista_i_zamykanie_pr(self):
        zapytania = []

        def otworz(req, timeout=None):
            zapytania.append((req.get_method(), req.full_url, req.data))
            return self.Odp([{"number": 7, "title": "[auto-tama] X"}] if req.get_method() == "GET" else {})
        self.assertEqual(rd.otwarte_pr("Rembolekk/rinvo-app", None, otworz), [(7, "[auto-tama] X")])
        self.assertTrue(rd.zamknij_pr("Rembolekk/rinvo-app", 7, "tajny-token", otworz))
        self.assertEqual(zapytania[1][0], "PATCH")
        self.assertEqual(json.loads(zapytania[1][2]), {"state": "closed"})
        self.assertNotIn("tajny-token", json.dumps(zapytania[1][1]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
