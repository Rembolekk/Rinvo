#!/usr/bin/env python3
"""test_nowy_klient.py – nowy klient: jedno zgłoszenie „Potwierdź kartę klienta …”, reszta spraw wstrzymana; „dziś” tylko na dziś (bez produktu
i bez wstrzymanych). Bez sieci i bez modelu. Uruchomienie: python3 testy/test_nowy_klient.py
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import agent
import dla_czlowieka as dc
import generuj_strony as gs
import karta_klienta as kk
import linear_sync
import podsumowanie
import widok
import zasady
import test_agent as ta
import test_porzadek_produkt as tp
import test_strony as ts
from test_strony import Repo, karta, tekst, zg

Z = zasady.wczytaj_zasady()
E = Z["etykiety"]

KARTA_NOWA = {"klient": "motor-lux", "nazwa": "Motor-Lux", "nowy_klient": True, "kontakty": [
    {"imie": "Agnieszka Wróbel", "email": "agnieszka@motorlux.pl", "rola": "agnieszka@motorlux.pl", "potwierdzony": False, "status": "z rozmowy, do potwierdzenia"},
    {"imie": "Piotr Nowak", "email": "", "rola": "handlowiec", "potwierdzony": False}],
    "decydenci": [], "decydenci_wniosek": [{"imie": "Agnieszka Wróbel", "rola": "wniosek z rozmowy, do potwierdzenia"}],
    "zakazy": [], "otwarte_sprawy": {}, "ryzyka": {}}


class N1Etykiety(unittest.TestCase):

    def test_n1_sprawy_nowego_klienta_zachowuja_normalny_podzial_i_dostaja_wstrzymanie(self):
        item = {"sekcja": 1, "typ": "bug", "tytul": "Błąd godzin", "pewnosc": "wysoka", "kryteria_akceptacji": ["a"], "flagi": ["nowy_klient"], "klucz_sprawy": "k"}
        et = zasady.etykiety_pozycji(item, Z, KARTA_NOWA)
        self.assertIn(E["agent"], et, "nadal Dla agenta")
        self.assertNotIn(E["weryfikacja"], et, "nowy klient nie przenosi sprawy do „Do weryfikacji”")
        self.assertIn(E["wstrzymane"], et)
        self.assertNotIn(E["wstrzymane"], zasady.etykiety_pozycji(item, Z, {**KARTA_NOWA, "nowy_klient": False}), "karta potwierdzona")
        self.assertNotIn(E["wstrzymane"], zasady.etykiety_pozycji(item, Z, {"klient": "x"}))

    def test_n1_wstrzymanie_dla_kazdego_rodzaju_sprawy_ale_nie_dla_zakazow(self):
        for sekcja, oczekuj in ((1, True), (2, True), (3, True), (5, True), (4, False)):
            et = zasady.etykiety_pozycji({"sekcja": sekcja, "typ": "bug", "tytul": "x", "pewnosc": "wysoka", "klucz_sprawy": "k"}, Z, KARTA_NOWA)
            self.assertEqual(E["wstrzymane"] in et, oczekuj, sekcja)

    def test_n1_flaga_nowy_klient_nie_jest_powodem_dla_czlowieka(self):
        self.assertEqual(zasady.powody_flag({"flagi": ["nowy_klient"]}, Z), [])
        self.assertTrue(zasady.powody_flag({"flagi": ["niepelna_transkrypcja"]}, Z), "inne znaczniki działają jak dotąd")

    def test_n1_etykiety_istnieja_w_linearze_i_zasadach(self):
        for n in ("Wstrzymane do potwierdzenia karty", "Karta do potwierdzenia"):
            self.assertIn(n, linear_sync.REQUIRED_LABELS)
        self.assertEqual((E["wstrzymane"], E["karta"]), ("Wstrzymane do potwierdzenia karty", "Karta do potwierdzenia"))

    def test_n1_linear_sync_dry_run_pokazuje_jedno_zgloszenie_do_potwierdzenia(self):
        with tempfile.TemporaryDirectory() as t:
            cwd = os.getcwd()
            os.chdir(t)
            try:
                Path("ops/klienci/motor-lux").mkdir(parents=True)
                Path("ops/klienci/motor-lux/karta.json").write_text(json.dumps(KARTA_NOWA, ensure_ascii=False), encoding="utf-8")
                pozycje = [{"id": f"T{i}", "sekcja": 1, "typ": "bug", "status": "zrob_teraz", "tytul": f"Błąd {i}", "klucz_sprawy": f"k{i}", "pewnosc": "wysoka",
                            "cytat": ["x"], "wlasciciel": "Marek", "termin": "brak", "warunek": "brak", "opis": "", "kryteria_akceptacji": ["a"]} for i in range(3)]
                Path("w.json").write_text(json.dumps({"zrodlo": "ops/transkrypcje/motor-lux/2026-10-15-call.md", "spotkanie": {"data": "2026-10-15", "uczestnicy": ["Agnieszka"]},
                                                     "wygenerowano": "2026-10-15", "pozycje": pozycje, "aktualizacje_spraw": []}), encoding="utf-8")
                wyj = io.StringIO()
                with contextlib.redirect_stdout(wyj):
                    sys.argv = ["linear_sync.py", "w.json", "--klient", "motor-lux", "--zrodlo", "ops/transkrypcje/motor-lux/2026-10-15-call.md", "--dry-run"]
                    linear_sync.main()
            finally:
                os.chdir(cwd)
        out = wyj.getvalue()
        self.assertEqual(out.count("Potwierdź kartę klienta Motor-Lux"), 1)
        self.assertEqual(out.count("[utwórz] k"), 3)
        self.assertIn("Wstrzymane do potwierdzenia karty", out)
        self.assertNotIn("Do weryfikacji", out)


class N2Zgloszenie(unittest.TestCase):

    def _s(self, karta_=None):
        with tempfile.TemporaryDirectory() as t:
            self._tmp = t
        self.root = Path(tempfile.mkdtemp())
        s = tp.BSrod(self.root)
        s.karty["motor-lux"] = copy.deepcopy(karta_ or KARTA_NOWA)
        return s

    def test_n2_tytul_etykiety_i_krotka_lista_bez_adresow(self):
        self.assertEqual(kk.tytul_potwierdzenia("motor-lux", KARTA_NOWA, Z), "[motor-lux] Potwierdź kartę klienta Motor-Lux")
        opis = kk.opis_potwierdzenia("motor-lux", KARTA_NOWA, Z)
        self.assertTrue(opis.startswith(dc.START))
        self.assertIn("**Dlaczego Ty:** karta", opis)
        self.assertIn("## Kontakty (do potwierdzenia)", opis)
        self.assertIn("- Agnieszka Wróbel, adres e-mail w karcie (do potwierdzenia)", opis)
        self.assertIn("- Piotr Nowak, handlowiec (do potwierdzenia)", opis)
        self.assertIn("## Decydenci (do potwierdzenia)", opis)
        self.assertIn("- Agnieszka Wróbel, z rozmowy", opis)
        self.assertNotIn("@", opis, "żadnych adresów e-mail")

    def test_n2_tworzy_jedno_zgloszenie_raz(self):
        s = self._s()
        zg1 = kk.zapewnij_zgloszenie(s, "motor-lux", s.karty["motor-lux"])
        self.assertEqual(zg1["title"], "[motor-lux] Potwierdź kartę klienta Motor-Lux")
        self.assertEqual(set(zg1["labels"]), {E["weryfikacja"], E["karta"]})
        self.assertEqual(s.karty["motor-lux"]["potwierdzenie_karty"]["identifier"], zg1["identifier"])
        self.assertIsNone(kk.zapewnij_zgloszenie(s, "motor-lux", s.karty["motor-lux"]), "drugi raz nic")
        self.assertEqual(len(s.linear.zgloszenia), 1)
        self.assertIsNone(kk.zapewnij_zgloszenie(s, "auto-tama", {"klient": "auto-tama"}), "karta potwierdzona: bez zgłoszenia")

    def test_n2_uklad_dla_czlowieka_nie_nadpisuje_zgloszenia_karty(self):
        s = self._s()
        z = kk.zapewnij_zgloszenie(s, "motor-lux", s.karty["motor-lux"])
        self.assertIsNone(dc.przebuduj(z, Z, tp.SROD))
        self.assertEqual(dc.czynnosc_dla(z["labels"], "", Z), "Potwierdź")

    def test_n2_zgloszenie_karty_jest_w_dzis_a_wstrzymane_nie(self):
        r = Repo(stan={"RIN-1": zg("[alfa] Potwierdź kartę klienta Alfa", etykiety=["Do weryfikacji", "Karta do potwierdzenia"]),
                       "RIN-2": zg("[alfa] Błąd", etykiety=["Dla agenta", "Wstrzymane do potwierdzenia karty"]),
                       "RIN-3": zg("[alfa] Decyzja o cenie", etykiety=["Decyzja człowieka", "Finanse", "Wstrzymane do potwierdzenia karty"]),
                       "RIN-4": zg("[alfa] Czeka", etykiety=["Czeka na klienta", "Wstrzymane do potwierdzenia karty"])})
        d = r.dane()
        s = gs.sprawy_klienta(d, "alfa")
        self.assertEqual([z["id"] for z in s["czlowiek"]], ["RIN-1"])
        self.assertEqual([z["id"] for z in s["wstrzymane"]], ["RIN-2", "RIN-3", "RIN-4"])
        self.assertEqual((s["agent"], s["czeka"]), ([], []), "wstrzymane nie liczą się jako „u agentów” ani „czeka na klienta”")
        self.assertEqual(gs.sprawy_dla_czlowieka(d), ["RIN-1"])
        self.assertIn("3 sprawy wstrzymane do potwierdzenia karty", gs.uwaga_klienta(d, d["klienci"]["alfa"]))
        h = gs.strona_klienta(d, d["klienci"]["alfa"])
        self.assertIn("Wstrzymane do potwierdzenia karty (3)", tekst(h))


class N3Zwolnienie(unittest.TestCase):

    def _s(self):
        s = tp.BSrod(Path(tempfile.mkdtemp()))
        s.karty["motor-lux"] = copy.deepcopy(KARTA_NOWA)
        s.karty["auto-tama"] = {"klient": "auto-tama", "nowy_klient": True}
        kk.zapewnij_zgloszenie(s, "motor-lux", s.karty["motor-lux"])
        for i, (kl, et) in enumerate((("motor-lux", ["Dla agenta"]), ("motor-lux", ["Czeka na klienta"]), ("auto-tama", ["Dla agenta"])), 1):
            s.linear.utworz(f"[{kl}] Sprawa {i}", "", et + [E["wstrzymane"]], "Todo")
        s.linear.ustaw_stan = lambda zg, nazwa, orig=s.linear.ustaw_stan: orig(zg, nazwa)
        return s

    def test_n3_zamkniecie_zgloszenia_karty_zwalnia_sprawy_tego_klienta(self):
        s = self._s()
        s.linear.zgloszenia["RIN-101"]["state"] = "Done"          # człowiek zamknął „Potwierdź kartę klienta”
        w = kk.zwolnij_potwierdzone(s)
        self.assertEqual(w, [{"klient": "motor-lux", "zwolnione": ["RIN-102", "RIN-103"]}])
        for ident in ("RIN-102", "RIN-103"):
            self.assertNotIn(E["wstrzymane"], s.linear.zgloszenia[ident]["labels"])
        self.assertIn(E["wstrzymane"], s.linear.zgloszenia["RIN-104"]["labels"], "inny klient nietknięty")
        self.assertIn("Dla agenta", s.linear.zgloszenia["RIN-102"]["labels"], "wracają do normalnego obiegu")
        k = s.karty["motor-lux"]
        self.assertNotIn("nowy_klient", k)
        self.assertNotIn("potwierdzenie_karty", k)
        self.assertEqual(k["decydenci"], [{"imie": "Agnieszka Wróbel", "rola": "decydent"}])
        self.assertTrue(k["kontakty"][0]["potwierdzony"], "kontakt z adresem potwierdzony")
        self.assertFalse(k["kontakty"][1]["potwierdzony"], "bez adresu nie ma czego potwierdzać")
        self.assertTrue(any("Karta klienta Motor-Lux potwierdzona: 2 sprawy wracają" in m for m in s.slack.wiadomosci))

    def test_n3_nic_sie_nie_dzieje_dopoki_karta_niepotwierdzona(self):
        s = self._s()
        self.assertEqual(kk.zwolnij_potwierdzone(s), [])
        self.assertIn(E["wstrzymane"], s.linear.zgloszenia["RIN-102"]["labels"])
        self.assertTrue(s.karty["motor-lux"]["nowy_klient"])

    def test_n3_zdjecie_znacznika_w_karcie_tez_potwierdza_i_zamyka_zgloszenie(self):
        s = self._s()
        s.karty["motor-lux"].pop("nowy_klient")                   # człowiek poprawił ops/klienci/motor-lux/karta.json
        w = kk.zwolnij_potwierdzone(s)
        self.assertEqual(w[0]["zwolnione"], ["RIN-102", "RIN-103"])
        self.assertEqual(s.linear.zgloszenia["RIN-101"]["state"], "Done", "zgłoszenie karty zamknięte")

    def test_n3_drugi_przebieg_nic_nie_zmienia(self):
        s = self._s()
        s.linear.zgloszenia["RIN-101"]["state"] = "Done"
        kk.zwolnij_potwierdzone(s)
        wiadomosci = len(s.slack.wiadomosci)
        self.assertEqual(kk.zwolnij_potwierdzone(s), [], "etykieta „Karta do potwierdzenia” zdjęta")
        self.assertEqual(len(s.slack.wiadomosci), wiadomosci)

    def test_n3_wyslij_main_zwalnia_potwierdzone(self):
        self.assertIn("karta_klienta.zwolnij_potwierdzone(s)", (ROOT / "wyslij.py").read_text(encoding="utf-8"))


class N4Wykluczenia(unittest.TestCase):

    def test_n4_agent_nie_bierze_wstrzymanych(self):
        s = ta.Srodowisko([ta.zgloszenie(41, etykiety=["Konfiguracja", "Dla agenta", "repo: rinvo-app", E["wstrzymane"]]), ta.zgloszenie(42, klient="beta")])
        w = agent.uruchom(s)
        self.assertEqual([x["zgloszenie"] for x in w], ["RIN-42"])
        self.assertEqual(s.github.utworzone[0]["tytul"].split()[0], "[beta]")

    def test_n4_poranne_podsumowanie_pomija_produkt_i_wstrzymane(self):
        def z(i, et):
            return {"id": f"i{i}", "identifier": f"RIN-{i}", "url": "u", "title": "[alfa] X", "createdAt": "2026-10-14T10:00:00Z", "updatedAt": "2026-10-14T10:00:00Z",
                    "dueDate": None, "state": {"name": "Todo", "type": "unstarted"}, "labels": {"nodes": [{"name": n} for n in et]}}
        d = __import__("datetime").date(2026, 10, 15)
        self.assertIsNone(podsumowanie.kategoria(z(1, ["Decyzja człowieka", "Produkt"]), d, Z))
        self.assertIsNone(podsumowanie.kategoria(z(2, ["Decyzja człowieka", E["wstrzymane"]]), d, Z))
        self.assertEqual(podsumowanie.kategoria(z(3, ["Szkic gotowy", "Decyzja człowieka"]), d, Z), "czlowiek")
        self.assertEqual(podsumowanie.kategoria(z(4, ["Do weryfikacji", E["karta"]]), d, Z), "weryfikacja")

    def test_n4_widok_i_strona_licza_to_samo_na_danych_mieszanych(self):
        stan = {"RIN-1": zg("[alfa] Szkic", etykiety=["Szkic gotowy"]), "RIN-2": zg("[alfa] Decyzja o cenie", etykiety=["Decyzja człowieka", "Finanse"]),
                "RIN-3": zg("[alfa] Weryfikacja", etykiety=["Do weryfikacji"]), "RIN-4": zg("[alfa] Potwierdź kartę klienta Alfa", etykiety=["Do weryfikacji", "Karta do potwierdzenia"]),
                "RIN-5": zg("[alfa] Pomysł", stan="Backlog", etykiety=["Decyzja człowieka", "Produkt"]),
                "RIN-6": zg("[alfa] Wstrzymane", etykiety=["Decyzja człowieka", E["wstrzymane"]]), "RIN-7": zg("[alfa] Zamknięte", stan="Done", etykiety=["Szkic gotowy"])}
        d = Repo(stan=stan).dane()
        f = widok.filtr(Z)
        etykiety_widoku = set(f["and"][0]["labels"]["name"]["in"])
        wyklucz = set(f["and"][1]["labels"]["every"]["name"]["nin"])
        w_widoku = [i for i, x in stan.items() if x["stan"] not in ("Done", "Canceled") and set(x["etykiety"]) & etykiety_widoku and not set(x["etykiety"]) & wyklucz]
        self.assertEqual(sorted(gs.sprawy_dla_czlowieka(d)), sorted(w_widoku), "dokładnie to, co pokaże widok Linear")
        self.assertEqual(sorted(w_widoku), ["RIN-1", "RIN-2", "RIN-3", "RIN-4"])
        self.assertIn("Dziś potrzebujemy Cię w 4 sprawach", tekst(gs.strona_index(d)))

    def test_n4_tabela_bez_wiersza_produkt_i_linijka_produktu(self):
        stan = {"RIN-1": zg("[produkt] Zdecyduj: propozycja – CRM", etykiety=["Decyzja człowieka", "Produkt"]),
                "RIN-2": zg("[alfa] Pomysł", stan="Backlog", etykiety=["Decyzja człowieka", "Produkt"])}
        h = gs.strona_index(Repo(stan=stan).dane())
        self.assertNotIn(">Produkt</a></td>", h)
        self.assertIn("Produkt: ", tekst(h))
        self.assertIn("2 pomysły do przeglądu", tekst(h))
        self.assertIn("(raz w tygodniu)", tekst(h))

    def test_n4_bez_zdublowanego_podpisu_pod_zdaniem_o_agentach(self):
        h = gs.strona_index(Repo().dane())
        self.assertNotIn('class="podpis"', h)
        self.assertNotIn("do wdrożonej poprawki", h)


class N5Dokumentacja(unittest.TestCase):

    def test_readme_opisuje_nowego_klienta_i_dzis(self):
        r = "".join((ROOT / d).read_text(encoding="utf-8") for d in ("README.md", "docs/SZCZEGOLY.md", "docs/PRZYPADKI-BRZEGOWE.md"))
        for fraza in ("Potwierdź kartę klienta", "Wstrzymane do potwierdzenia karty", "raz w tygodniu", "karta_klienta.py"):
            self.assertIn(fraza, r, fraza)

    def test_zasady_maja_wykluczenia_widoku(self):
        self.assertEqual(set(Z["dla_czlowieka"]["widok"]["wyklucz_etykiety"]), {"Produkt", "Wstrzymane do potwierdzenia karty"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
