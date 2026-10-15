#!/usr/bin/env python3
"""test_strona_glowna.py – nowy układ index.html, stron klientów i Głosu klientów; czas od wpłynięcia; nazwy klientów z karty; zgodność
liczby w widoku „Dla mnie dziś” z „Wymaga Ciebie”. Bez sieci i bez modelu. Uruchomienie: python3 testy/test_strona_glowna.py
"""

import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import generuj_strony as gs
import higiena
import widok
import wplyniecia
import zasady
import test_strony as ts
from test_strony import Repo, karta, tekst, zg

Z = zasady.wczytaj_zasady()


def repo_hoteli():
    stan = {"RIN-1": zg("[hotele-baltyk] Decyzja", etykiety=["Decyzja człowieka"], url="https://linear.app/ws/issue/RIN-1/x"),
            "RIN-2": zg("[hotele-baltyk] Wysyłka", etykiety=["Szkic gotowy"]),
            "RIN-3": zg("[hotele-baltyk] Agent", etykiety=["Dla agenta"]),
            "RIN-4": zg("[hotele-baltyk] Zamknięte decyzja", stan="Done", etykiety=["Decyzja człowieka"]),
            "RIN-5": zg("[hotele-baltyk] Anulowane", stan="Canceled", etykiety=["Do weryfikacji"]),
            "RIN-6": zg("[alfa] Czeka", etykiety=["Czeka na klienta"]),
            "RIN-7": zg("[alfa] Weryfikacja w backlogu", stan="Backlog", etykiety=["Do weryfikacji", "Produkt"])}
    k = karta("hotele-baltyk", nazwa="Hotele Bałtyk", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "x"}, {"data": "2026-10-13", "zrodlo": "b.md", "cytat": "y"}]})
    r = Repo(stan=stan, karta_a=karta("alfa", nazwa="Alfa Sp. z o.o."), karta_b=k)
    shutil_rm = r.root / "ops/klienci/beta"
    import shutil
    shutil.rmtree(shutil_rm)
    r.zapisz("ops/klienci/hotele-baltyk/karta.json", k)
    return r


class TestIndex(unittest.TestCase):

    def setUp(self):
        self.r = repo_hoteli()
        self.dane = self.r.dane()
        self.h = gs.strona_index(self.dane)
        self.t = tekst(self.h)

    def test_jedno_duze_zdanie_i_linijka_o_agentach(self):
        self.assertIn("Dziś potrzebujemy Cię w 3 sprawach", self.t)
        self.assertIn("Agenci w tym tygodniu:", self.t)
        self.assertEqual(self.h.count('class="glowne"'), 1)

    def test_zdanie_linkuje_do_widoku_dla_mnie_dzis(self):
        self.r.zapisz("ops/widok_dla_mnie.json", {"url": "https://linear.app/ws/view/abc"})
        h = gs.strona_index(self.r.dane())
        self.assertIn('<a href="https://linear.app/ws/view/abc">3 sprawach</a>', h)
        self.assertNotIn("<a href=\"https://linear.app/ws/view/abc\"", self.h, "bez pliku widoku bez linku")

    def test_liczba_zgadza_sie_z_wymaga_ciebie_i_z_filtrem_widoku(self):
        liczby = [int(x) for x in re.findall(r'<td class="n[^"]*">(\d+)</td>', self.h)]
        wymaga = liczby[0::3]                              # kolumna „Wymaga Ciebie” (Wymaga, Agenci, Czeka)
        self.assertEqual(sum(wymaga), len(gs.sprawy_dla_czlowieka(self.dane)))
        self.assertEqual(sum(wymaga), 3, "Decyzja i Szkic u hoteli oraz Do weryfikacji w backlogu u alfy; Done i Canceled nie liczą się")
        f = widok.filtr(Z)
        self.assertEqual(set(f["labels"]["name"]["in"]), gs.wymaga_ciebie_etykiety(self.dane), "te same etykiety co w widoku Linear")
        self.assertEqual(f["state"]["type"]["nin"], ["completed", "canceled"], "tylko otwarte")

    def test_zdanie_pasuje_do_sumy_w_tabeli(self):
        n = sum(int(x) for x in re.findall(r'<td class="n[^"]*">(\d+)</td>', self.h)[0::3])
        self.assertIn(f"Dziś potrzebujemy Cię w {n} sprawach", self.t)

    def test_tabela_z_nazwami_z_karty_a_nie_ze_sluga(self):
        self.assertIn("Hotele Bałtyk", self.t)
        self.assertNotIn("Hotele Baltyk", self.t)
        self.assertIn("Alfa Sp. z o.o.", self.t)
        self.assertRegex(self.h, r'<a href="klienci/hotele-baltyk\.html">Hotele Bałtyk</a>')
        for kolumna in ("Klient", "Wymaga Ciebie", "U agentów", "Czeka na klienta", "Uwaga"):
            self.assertIn(f">{kolumna}</th>", self.h)

    def test_uwaga_to_jedno_krotkie_zdanie(self):
        self.assertIn("konkurencja wraca drugi raz", self.t)
        self.assertEqual(gs.uwaga_klienta(self.dane, self.dane["klienci"]["alfa"]), "")
        d = self.dane
        k = d["klienci"]["hotele-baltyk"]
        k["karta"]["ryzyka"]["konkurencja"].append({"data": "2026-10-14", "zrodlo": "c.md", "cytat": "z"})
        self.assertEqual(gs.uwaga_klienta(d, k), "konkurencja wraca 3. raz")

    def test_uwaga_o_sprawach_po_terminie_gdy_brak_ryzyka(self):
        r = Repo(stan={"RIN-1": zg("[alfa] Spóźnione", termin="2026-10-01", etykiety=["Dla agenta"]), "RIN-2": zg("[alfa] Też", termin="2026-10-02", etykiety=["Dla agenta"])})
        d = r.dane()
        self.assertEqual(gs.uwaga_klienta(d, d["klienci"]["alfa"]), "2 sprawy po terminie")

    def test_bez_legendy_kolorow_i_bez_kafelkow_a_kolor_w_dymku(self):
        for fraza in ("Czerwone:", "Żółte:", "Zielone:", "Powtarzające się ryzyko albo sprawa po terminie"):
            self.assertNotIn(fraza, self.t.replace("title", ""), fraza)
        self.assertNotIn('class="card"', self.h)
        self.assertNotIn('class="num"', self.h)
        self.assertRegex(self.h, r'<span class="dot czerwone" title="Czerwone: ryzyko „Konkurencja” pojawiło się już 2 razy"></span>')
        self.assertRegex(self.h, r'<span class="dot [a-z]+" title="[^"]+"></span><a href="klienci/alfa\.html">')

    def test_stopka_jedna_linijka_z_data_po_polsku(self):
        self.r.zapisz("ops/.stan_linear.json", {"zapisano": "2026-10-15T14:05:00+00:00", "zgloszenia": {}})
        h = gs.strona_index(self.r.dane())
        self.assertRegex(h, r"<footer>Dane fikcyjne, demo · zaktualizowano 15 października 2026, 16:05</footer>")
        self.assertEqual(h.count("<footer>"), 1)
        self.assertNotIn('class="demo"', h)

    def test_liczby_wyrownane_do_prawej_jedna_czcionka(self):
        self.assertIn("th.n,td.n{text-align:right;font-variant-numeric:tabular-nums}", gs.CSS)
        self.assertEqual(gs.CSS.count("font-family"), 0)
        self.assertEqual(len(re.findall(r"font:[^;]*(?:sans-serif)", gs.CSS)), 1, "jedna czcionka na całej stronie")

    def test_zdanie_zerowe_i_odmiana(self):
        self.assertIn("Dziś nic nie wymaga Ciebie", tekst(gs.strona_index(Repo().dane())))
        r = Repo(stan={"RIN-1": zg("[alfa] A", etykiety=["Decyzja człowieka"])})
        self.assertIn("Dziś potrzebujemy Cię w 1 sprawie", tekst(gs.strona_index(r.dane())))
        self.assertEqual([gs.forma_liczby(n, "sprawa", "sprawy", "spraw") for n in (1, 2, 5, 12, 22)], ["sprawa", "sprawy", "spraw", "spraw", "sprawy"])

    def test_pozycje_produktowe_maja_wlasny_wiersz_z_linkiem_do_glosu_klientow(self):
        r = Repo(stan={"RIN-1": zg("[produkt] Zdecyduj: propozycja – CRM", etykiety=["Decyzja człowieka", "Produkt"])})
        h = gs.strona_index(r.dane())
        self.assertIn('<a href="glos-klientow.html">Produkt</a>', h)

    def test_strony_klientow_i_glos_maja_ten_sam_uklad(self):
        for h in (self.r.strony()["klienci/hotele-baltyk.html"], self.r.strony()["glos-klientow.html"]):
            self.assertIn("Dane fikcyjne, demo · zaktualizowano", h)
            self.assertNotIn('class="demo"', h)
            self.assertNotIn("Adresy e-mail kontaktów celowo", h)
        self.assertIn("<h1>Hotele Bałtyk</h1>", self.r.strony()["klienci/hotele-baltyk.html"])
        self.assertNotIn("Klient: hotele-baltyk", self.r.strony()["klienci/hotele-baltyk.html"], "bez sluga")


class TestGlosKlientow(unittest.TestCase):

    def _repo(self):
        pro = {"crm": {"tytul": "Integracja z CRM", "prosby": [ts.prosba("alfa", "Chcę integrację z systemem CRM.", "2026-10-06", "a.md")]},
               "xls": {"tytul": "Eksport do Excela", "prosby": [ts.prosba("alfa", "Excel proszę.", "2026-10-13", "a.md"), ts.prosba("beta", "Też Excel.", "2026-10-14", "b.md")]},
               "kolor": {"tytul": "Inny kolor", "prosby": [ts.prosba("beta", "Fajnie byłoby mieć kolor.", "2026-10-13", "b.md")]}}
        ka = karta("alfa", nazwa="Auto Tama", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk łączy się z systemem dealera."}]})
        return Repo(prosby=pro, karta_a=ka, karta_b=karta("beta", nazwa="Beta Klinika"))

    def test_zdanie_na_gorze_wiersze_z_powodem_liczba_klientow_i_link(self):
        r = self._repo()
        r.zapisz("ops/produkt/propozycje.json", {"crm": {"status": "do_decyzji", "wersja": 1}})
        h = gs.strona_glos(r.dane())
        t = tekst(h)
        self.assertTrue(t.index("2 sygnały warte decyzji") < t.index("Integracja z CRM"))
        self.assertIn("może uratować klienta Auto Tama, konkurencja to ma", t)
        self.assertIn("prosi 2 klientów", t)
        self.assertRegex(h, r'<td class="n">1</td><td><a href="ops/materialy/produkt/crm\.pdf">Propozycja</a>')
        self.assertIn("w przygotowaniu", t, "sygnał bez propozycji")

    def test_cytat_zwiniety_pod_wierszem_a_pojedyncze_prosby_w_jednej_linijce(self):
        h = gs.strona_glos(self._repo().dane())
        self.assertRegex(h, r"</tr><tr><td colspan=\"4\"[^>]*><details><summary>Cytat klienta</summary><blockquote>Chcę integrację")
        self.assertRegex(h, r'<summary class="jedna">Pozostałe pojedyncze prośby \(1\): Inny kolor</summary>')
        self.assertIn("white-space:nowrap", gs.CSS)

    def test_odmiana_zdania_o_sygnalach(self):
        r = Repo()
        self.assertIn("Brak sygnałów wartych decyzji", tekst(gs.strona_glos(r.dane())))
        pro = {f"f{i}": {"tytul": f"Funkcja {i}", "prosby": [ts.prosba("alfa", "c", "2026-10-06", "a.md"), ts.prosba("beta", "c", "2026-10-07", "b.md")]} for i in range(5)}
        self.assertIn("5 sygnałów wartych decyzji", tekst(gs.strona_glos(Repo(prosby=pro).dane())))


class TestWplyniecie(unittest.TestCase):

    def test_czas_z_gita_to_najnowsze_dodanie_pliku(self):
        with tempfile.TemporaryDirectory() as t:
            def git(*a, env=None):
                import os
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=t, check=True, capture_output=True, env={**os.environ, **(env or {})})
            git("init", "-q")
            (Path(t) / "ops/transkrypcje/a").mkdir(parents=True)
            f = Path(t) / "ops/transkrypcje/a/2026-10-06-call.md"
            f.write_text("x", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "pierwszy", env={"GIT_COMMITTER_DATE": "2026-10-10T08:00:00+02:00", "GIT_AUTHOR_DATE": "2026-10-10T08:00:00+02:00"})
            git("rm", "-q", str(f))
            git("commit", "-q", "-m", "reset", env={"GIT_COMMITTER_DATE": "2026-10-11T08:00:00+02:00"})
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
            git("add", "-A")
            git("commit", "-q", "-m", "ponownie", env={"GIT_COMMITTER_DATE": "2026-10-15T11:29:54+02:00", "GIT_AUTHOR_DATE": "2026-10-15T11:29:54+02:00"})
            self.assertEqual(wplyniecia.czas_z_gita("ops/transkrypcje/a/2026-10-06-call.md", t), "2026-10-15T11:29:54+02:00",
                             "data z nazwy pliku (6.10) i pierwszy commit (10.10) nie mają znaczenia")
            self.assertIsNone(wplyniecia.czas_z_gita("ops/transkrypcje/a/nie-ma.md", t))
            rejestr = Path(t) / "ops/.przetworzone.json"
            rejestr.write_text('{"h": {"transkrypcja": "ops/transkrypcje/a/2026-10-06-call.md"}, "g": {"transkrypcja": "ops/transkrypcje/a/nie-ma.md"}}', encoding="utf-8")
            self.assertEqual(wplyniecia.uzupelnij(rejestr, t), 1)
            self.assertEqual(wplyniecia.mapa(__import__("json").loads(rejestr.read_text(encoding="utf-8"))),
                             {"ops/transkrypcje/a/2026-10-06-call.md": "2026-10-15T11:29:54+02:00"})
            self.assertEqual(wplyniecia.uzupelnij(rejestr, t), 0, "idempotentne")

    def test_rejestr_w_repozytorium_ma_wplyniecie_przy_kazdym_wpisie(self):
        import json
        rejestr = json.loads((ROOT / "ops/.przetworzone.json").read_text(encoding="utf-8"))
        self.assertTrue(all(w.get("wplynelo") for w in rejestr.values()), "wpływ zapisany przy przetworzeniu albo uzupełniony z gita")


class TestNazwaKlienta(unittest.TestCase):

    def test_nazwa_z_naglowka_z_polskimi_znakami(self):
        self.assertEqual(higiena.nazwa_z_naglowka("# Hotele Bałtyk × Rinvo: call po pierwszym tygodniu\n\ntekst"), "Hotele Bałtyk")
        self.assertEqual(higiena.nazwa_z_naglowka("# Rinvo × Grupa Auto Tama: status"), "Grupa Auto Tama")
        self.assertIsNone(higiena.nazwa_z_naglowka("bez nagłówka"))

    def test_nowa_karta_dostaje_nazwe_z_naglowka_a_awaryjnie_ze_sluga(self):
        k = higiena.karta_nowego_klienta("hotele-baltyk", "# Hotele Bałtyk × Rinvo: call\n\n## Uczestnicy\n")
        self.assertEqual(k["nazwa"], "Hotele Bałtyk")
        self.assertEqual(higiena.karta_nowego_klienta("hotele-baltyk", "brak")["nazwa"], "Hotele Baltyk")

    def test_karta_hoteli_w_repozytorium_ma_poprawna_nazwe(self):
        import json
        p = ROOT / "ops/klienci/hotele-baltyk/karta.json"
        if p.exists():
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["nazwa"], "Hotele Bałtyk")


if __name__ == "__main__":
    unittest.main(verbosity=1)
