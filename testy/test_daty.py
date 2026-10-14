#!/usr/bin/env python3
"""test_daty.py – daty względne liczone przez kod (daty.py): parser polskich wyrażeń, pierwszeństwo daty
z kodu nad datą modelu, ostrzeżenia o rozbieżnościach, oznaczenie „wniosek”, poprawa tekstów pozycji.

Bez sieci i bez modelu. Uruchomienie:  python3 testy/test_daty.py
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import daty
import uzupelnij


def d(rrrr_mm_dd):
    return date.fromisoformat(rrrr_mm_dd)


def licz(wyrazenie, zrodlo):
    r = daty.oblicz_wyrazenie(wyrazenie, d(zrodlo))
    return None if r is None else (r["od"].isoformat(), r["do"].isoformat())


class TestPrzykladyZPolecenia(unittest.TestCase):
    """Przykłady, które muszą działać zawsze."""

    def test_13_10_do_piatku_to_16_10(self):
        self.assertEqual(licz("do piątku", "2026-10-13"), ("2026-10-16", "2026-10-16"))

    def test_06_10_do_czwartku_to_08_10(self):
        self.assertEqual(licz("do czwartku", "2026-10-06"), ("2026-10-08", "2026-10-08"))

    def test_13_10_dwudziesty_siodmy_to_27_10(self):
        self.assertEqual(licz("dwudziesty siódmy", "2026-10-13"), ("2026-10-27", "2026-10-27"))


class TestDniTygodnia(unittest.TestCase):

    def test_najblizszy_nastepny_dzien_tygodnia(self):
        # 13.10.2026 to wtorek
        for wyr, oczek in (("w środę", "2026-10-14"), ("w czwartek", "2026-10-15"), ("do piątku", "2026-10-16"),
                           ("w sobotę", "2026-10-17"), ("w niedzielę", "2026-10-18"), ("w poniedziałek", "2026-10-19"),
                           ("od środy", "2026-10-14")):
            self.assertEqual(licz(wyr, "2026-10-13")[0], oczek, wyr)

    def test_ten_sam_dzien_tygodnia_co_zrodlo_to_za_tydzien(self):
        self.assertEqual(licz("do wtorku", "2026-10-13")[0], "2026-10-20")

    def test_przyszly_czwartek_to_czwartek_nastepnego_tygodnia(self):
        self.assertEqual(licz("przyszły czwartek", "2026-10-06")[0], "2026-10-15")
        self.assertEqual(licz("w przyszły czwartek", "2026-10-13")[0], "2026-10-22")
        self.assertEqual(licz("na przyszłą środę", "2026-10-13")[0], "2026-10-21")
        self.assertEqual(licz("następny piątek", "2026-10-13")[0], "2026-10-23")

    def test_wszystkie_odmiany_nazw_dni(self):
        for wyr in ("poniedziałku", "wtorku", "środę", "środy", "czwartku", "piątku", "sobotę", "soboty", "niedzielę"):
            self.assertIsNotNone(licz(wyr, "2026-10-13"), wyr)

    def test_wiecej_niz_jeden_dzien_to_niejednoznaczne(self):
        self.assertIsNone(licz("środa i czwartek", "2026-10-13"))
        self.assertIsNone(licz("w środę lub w piątek", "2026-10-13"))


class TestJutroPojutrze(unittest.TestCase):

    def test_jutro_pojutrze_dzis(self):
        self.assertEqual(licz("jutro", "2026-10-13")[0], "2026-10-14")
        self.assertEqual(licz("od jutra", "2026-10-06")[0], "2026-10-07")
        self.assertEqual(licz("pojutrze", "2026-10-13")[0], "2026-10-15")
        self.assertEqual(licz("dzisiaj", "2026-10-13")[0], "2026-10-13")
        self.assertEqual(licz("przekażę mu dziś", "2026-10-13")[0], "2026-10-13")

    def test_przez_granice_miesiaca(self):
        self.assertEqual(licz("jutro", "2026-10-31")[0], "2026-11-01")
        self.assertEqual(licz("pojutrze", "2026-12-31")[0], "2027-01-02")


class TestDniMiesiaca(unittest.TestCase):

    def test_liczebniki_porzadkowe_w_roznych_formach(self):
        for wyr, dzien in (("piętnastego", 15), ("dwudziesty siódmy", 27), ("dwudziestego siódmego", 27),
                           ("trzydziesty pierwszy", 31), ("pierwszego", 1), ("drugiego", 2), ("trzeciego", 3),
                           ("dziewiętnastego", 19), ("dwudziestego", 20)):
            r = licz(wyr, "2026-10-13")
            self.assertEqual(int(r[0][-2:]), dzien, wyr)

    def test_dzien_miesiaca_to_najblizszy_taki_dzien_a_gdy_minal_nastepny_miesiac(self):
        self.assertEqual(licz("dwudziesty siódmy", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("piąty", "2026-10-13")[0], "2026-11-05")
        self.assertEqual(licz("drugiego", "2026-12-20")[0], "2027-01-02")

    def test_dzien_z_nazwa_miesiaca_i_data_numeryczna(self):
        self.assertEqual(licz("27 października", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("dwudziestego siódmego października", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("27.10", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("27.10.2026", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("2026-10-27", "2026-10-13")[0], "2026-10-27")
        self.assertEqual(licz("5 stycznia", "2026-10-30")[0], "2027-01-05", "miesiąc, który minął, to przyszły rok")

    def test_liczebnik_z_dniem_tygodnia_potwierdza_date(self):
        # 27.10.2026 to wtorek
        self.assertEqual(licz("dwudziesty siódmy, wtorek", "2026-10-13")[0], "2026-10-27")
        self.assertIsNone(licz("dwudziesty siódmy, środa", "2026-10-13"), "niezgodny dzień tygodnia")

    def test_liczebnik_w_zwyklym_zdaniu_to_nie_data(self):
        self.assertIsNone(licz("drugi raz", "2026-10-13"))
        self.assertIsNone(licz("w drugim tygodniu", "2026-10-13"))

    def test_zakres_od_do(self):
        self.assertEqual(licz("od dziewiętnastego do dwudziestego trzeciego", "2026-10-13"), ("2026-10-19", "2026-10-23"))
        self.assertEqual(licz("od 2 do 6 listopada", "2026-10-13"), ("2026-11-02", "2026-11-06"))


class TestTygodnieIMiesiace(unittest.TestCase):

    def test_w_tym_tygodniu_to_do_piatku(self):
        self.assertEqual(licz("w tym tygodniu", "2026-10-13"), ("2026-10-13", "2026-10-16"))
        self.assertEqual(licz("do końca tygodnia", "2026-10-13"), ("2026-10-13", "2026-10-16"))
        self.assertEqual(licz("tego tygodnia", "2026-10-06"), ("2026-10-06", "2026-10-09"))

    def test_w_przyszlym_tygodniu_to_pon_pt_nastepnego(self):
        self.assertEqual(licz("w przyszłym tygodniu", "2026-10-13"), ("2026-10-19", "2026-10-23"))
        self.assertEqual(licz("w następnym tygodniu", "2026-10-06"), ("2026-10-12", "2026-10-16"))

    def test_do_konca_miesiaca_i_miesiace(self):
        self.assertEqual(licz("do końca miesiąca", "2026-10-13"), ("2026-10-13", "2026-10-31"))
        self.assertEqual(licz("w tym miesiącu", "2026-02-10"), ("2026-02-10", "2026-02-28"))
        self.assertEqual(licz("w przyszłym miesiącu", "2026-12-10"), ("2027-01-01", "2027-01-31"))

    def test_wyrazenia_bez_daty_to_none(self):
        for wyr in ("po urlopie", "przed urlopem", "kiedyś", "", "jak znajdzie"):
            self.assertIsNone(licz(wyr, "2026-10-13"), wyr)


class TestPierwszenstwoKoduIWniosek(unittest.TestCase):

    def _wynik(self, **kw):
        w = {"spotkanie": {"data": "2026-10-13"}, "zrodlo": "ops/transkrypcje/k/2026-10-13-x.md",
             "fakty_czasowe": [], "pozycje": []}
        w.update(kw)
        return w

    def _fakt(self, typ, wyr, od, do=None, dotyczy="sprawa"):
        return {"typ": typ, "od": od, "do": do, "dotyczy": dotyczy, "cytat": "c", "wyrazenie": wyr}

    def test_data_z_kodu_wygrywa_a_rozbieznosc_trafia_do_ostrzezen(self):
        w = self._wynik(fakty_czasowe=[self._fakt("termin", "do piątku", "2026-10-17", "2026-10-17")])
        ostrz, zmiany = daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        f = w["fakty_czasowe"][0]
        self.assertEqual((f["od"], f["do"], f["zrodlo_daty"]), ("2026-10-16", "2026-10-16", "kod"))
        self.assertEqual(f["data_modelu"], {"od": "2026-10-17", "do": "2026-10-17"})
        self.assertEqual(len(ostrz), 1)
        self.assertIn("model podał 2026-10-17", ostrz[0]["uwaga"])
        self.assertIn("kod policzył 2026-10-16", ostrz[0]["uwaga"])
        self.assertEqual(zmiany[0][2:], ("2026-10-17–2026-10-17", "2026-10-16"))

    def test_zgodna_data_nie_daje_ostrzezenia_ale_jest_oznaczona_jako_z_kodu(self):
        w = self._wynik(fakty_czasowe=[self._fakt("termin", "do piątku", "2026-10-16", "2026-10-16")])
        ostrz, _ = daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        self.assertEqual(ostrz, [])
        self.assertEqual(w["fakty_czasowe"][0]["zrodlo_daty"], "kod")

    def test_gdy_kod_nie_umie_zostaje_data_modelu_z_oznaczeniem_wniosek(self):
        w = self._wynik(fakty_czasowe=[self._fakt("blokada", "po urlopie", "2026-10-26", "2026-10-30")])
        ostrz, _ = daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        f = w["fakty_czasowe"][0]
        self.assertEqual((f["od"], f["do"], f["zrodlo_daty"]), ("2026-10-26", "2026-10-30", "wniosek"))
        self.assertEqual(ostrz, [])

    def test_fakt_bez_wyrazenia_to_wniosek(self):
        f = {"typ": "termin", "od": "2026-10-16", "dotyczy": "x", "cytat": "c"}
        daty.popraw_daty_wzgledne(self._wynik(fakty_czasowe=[f]), d("2026-10-13"))
        self.assertEqual(f["zrodlo_daty"], "wniosek")

    def test_idempotentne_drugie_uruchomienie_zachowuje_ostrzezenie(self):
        w = self._wynik(fakty_czasowe=[self._fakt("termin", "do piątku", "2026-10-17", "2026-10-17")])
        daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        ostrz2, _ = daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        self.assertEqual(w["fakty_czasowe"][0]["do"], "2026-10-16")
        self.assertEqual(len(ostrz2), 1, "informacja o rozbieżności nie ginie przy ponownym przeliczeniu")
        self.assertEqual(w["fakty_czasowe"][0]["data_modelu"]["od"], "2026-10-17")

    def test_semantyka_wedlug_typu_faktu(self):
        w = self._wynik(fakty_czasowe=[
            self._fakt("blokada", "w czwartek", "2026-10-13", "2026-10-15"),            # koniec blokady
            self._fakt("urlop", "od dziewiętnastego", "2026-10-19", "2026-10-23"),      # tylko początek
            self._fakt("urlop", "od dziewiętnastego do dwudziestego trzeciego", "2026-10-19", "2026-10-22"),
            self._fakt("start_nie_wczesniej", "od jutra", "2026-10-14", None),
            self._fakt("start_nie_wczesniej", "w tym tygodniu", "2026-10-19", None),    # zakaz, nie start
        ])
        daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        f = w["fakty_czasowe"]
        self.assertEqual((f[0]["od"], f[0]["do"]), ("2026-10-13", "2026-10-15"))
        self.assertEqual((f[1]["od"], f[1]["do"]), ("2026-10-19", "2026-10-23"), "„od X” nie skraca urlopu")
        self.assertEqual((f[2]["od"], f[2]["do"]), ("2026-10-19", "2026-10-23"), "zakres z kodu wygrywa")
        self.assertEqual(f[3]["od"], "2026-10-14")
        self.assertEqual((f[4]["od"], f[4]["zrodlo_daty"]), ("2026-10-19", "wniosek"),
                         "„w tym tygodniu” przy starcie to zakaz, nie data startu")

    def test_wyrazenie_zlozone_to_wniosek(self):
        f = self._fakt("start_nie_wczesniej", "od jutra, środa i czwartek", "2026-10-14")
        daty.popraw_daty_wzgledne(self._wynik(fakty_czasowe=[f]), d("2026-10-13"))
        self.assertEqual(f["zrodlo_daty"], "wniosek")

    def test_tydzien_pn_pt_i_niedziela_modelu_to_ten_sam_termin_roboczy(self):
        f = self._fakt("blokada", "w tym tygodniu", "2026-10-06", "2026-10-11")
        ostrz, _ = daty.popraw_daty_wzgledne(self._wynik(fakty_czasowe=[f]), d("2026-10-06"))
        self.assertEqual(ostrz, [], "niedziela vs piątek w „tym tygodniu” nie jest rozbieżnością")


class TestTerminyPozycji(unittest.TestCase):

    def _klinika(self):
        return {"spotkanie": {"data": "2026-10-13"}, "szkic_maila": "Lista lekarzy – do piątku (17.10). Jedno przypomnienie.",
                "fakty_czasowe": [], "pozycje": [{
                    "id": "K2", "klucz_sprawy": "grafik", "tytul": "Lista lekarzy z grafikiem na listopad (do piątku 17.10)",
                    "opis": "Ania wyśle listę do piątku 17.10.", "termin": "2026-10-17", "termin_wyrazenie": "Do piątku",
                    "przypomnienie": {"data": "2026-10-17", "limit": "1 raz", "uwagi": "u"},
                    "kryteria_akceptacji": ["Lista dotarła do 17.10"]}]}

    def test_bledny_termin_poprawiony_a_model_zapamietany(self):
        w = self._klinika()
        ostrz, zmiany = daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        p = w["pozycje"][0]
        self.assertEqual((p["termin"], p["termin_modelu"], p["termin_zrodlo"]), ("2026-10-16", "2026-10-17", "kod"))
        self.assertEqual(len(ostrz), 1)
        self.assertIn("termin: model podał 2026-10-17, kod policzył 2026-10-16", ostrz[0]["uwaga"])
        self.assertEqual(zmiany, [("grafik", "Do piątku", "2026-10-17", "2026-10-16")])

    def test_ta_sama_blednia_data_w_tytule_opisie_przypomnieniu_i_szkicu_maila_tez_poprawiona(self):
        w = self._klinika()
        daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        p = w["pozycje"][0]
        self.assertIn("(do piątku 16.10)", p["tytul"])
        self.assertIn("16.10", p["opis"])
        self.assertEqual(p["przypomnienie"]["data"], "2026-10-16")
        self.assertEqual(p["kryteria_akceptacji"], ["Lista dotarła do 16.10"])
        self.assertIn("do piątku (16.10)", w["szkic_maila"])
        self.assertNotIn("17.10", json.dumps(w, ensure_ascii=False))

    def test_od_x_bez_konca_nie_jest_terminem(self):
        w = {"fakty_czasowe": [], "pozycje": [{"id": "T", "termin": "2026-10-14 – 2026-10-15", "termin_wyrazenie": "od jutra"}]}
        daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        self.assertEqual(w["pozycje"][0]["termin"], "2026-10-14 – 2026-10-15")
        self.assertEqual(w["pozycje"][0]["termin_zrodlo"], "wniosek")

    def test_zakres_daje_termin_koncowy(self):
        w = {"fakty_czasowe": [], "pozycje": [{"id": "Z", "termin": "2026-11-05", "termin_wyrazenie": "od 2 do 6 listopada"}]}
        daty.popraw_daty_wzgledne(w, d("2026-10-13"))
        self.assertEqual(w["pozycje"][0]["termin"], "2026-11-06")

    def test_niedziela_modelu_w_tym_tygodniu_nie_zmienia_terminu(self):
        w = {"fakty_czasowe": [], "pozycje": [{"id": "T9", "termin": "2026-10-11", "termin_wyrazenie": "w tym tygodniu"}]}
        ostrz, _ = daty.popraw_daty_wzgledne(w, d("2026-10-06"))
        self.assertEqual((w["pozycje"][0]["termin"], ostrz), ("2026-10-11", []))

    def test_zamiana_dat_nie_rusza_innych_dat_ani_liczb(self):
        self.assertEqual(daty._zamien_date("do 17.10 i 7.10, kwota 117.100", "2026-10-17", "2026-10-16"),
                         "do 16.10 i 7.10, kwota 117.100")


class TestDatyUruchomienieSkryptu(unittest.TestCase):
    """Cały skrypt (python -I daty.py): okna robocze liczone z poprawionych dat, ostrzeżenia w wynik.json."""

    def _uruchom(self, wynik):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "wynik.json"
            f.write_text(json.dumps(wynik), encoding="utf-8")
            r = subprocess.run([sys.executable, "-I", str(Path(__file__).parent.parent / "daty.py"), str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(f.read_text(encoding="utf-8")), r.stdout

    def test_okno_liczone_z_daty_z_kodu_a_ostrzezenie_w_wyniku(self):
        wynik = {"spotkanie": {"data": "2026-10-13"}, "zrodlo": "ops/transkrypcje/k/2026-10-13-x.md",
                 "pozycje": [{"id": "K2", "sekcja": 2, "klucz_sprawy": "grafik", "cytat": ["x"]}],
                 "fakty_czasowe": [{"typ": "termin", "od": "2026-10-17", "do": "2026-10-17", "dotyczy": "grafik",
                                    "cytat": "Do piątku.", "wyrazenie": "do piątku"}]}
        w, stdout = self._uruchom(wynik)
        okna = next(o["okna"] for o in w["okna_czasowe"] if o["klucz_sprawy"] == "grafik")
        self.assertEqual(okna, [{"od": "2026-10-14", "do": "2026-10-16"}], "piątek 16.10, nie sobota 17.10")
        self.assertTrue(any("kod policzył 2026-10-16" in o["uwaga"] for o in w["ostrzezenia_dat"]))
        self.assertIn("Daty względne przeliczone przez kod", stdout)

    def test_data_maila_pochodzi_z_pliku_maila_a_nie_z_modelu(self):
        with tempfile.TemporaryDirectory() as tmp:
            mail = Path(tmp) / "maile" / "k" / "2026-10-13-x.md"
            mail.parent.mkdir(parents=True)
            mail.write_text("# Mail: x\n\n- **Od:** a@b.pl\n- **Data:** 2026-10-13 10:00\n", encoding="utf-8")
            wynik = {"spotkanie": {"data": "1999-01-01"}, "zrodlo": str(mail)}
            self.assertEqual(daty.data_zrodla_z_wyniku(wynik), d("2026-10-13"))
        self.assertEqual(daty.data_zrodla_z_wyniku({"spotkanie": {"data": "2026-10-06"}, "zrodlo": "ops/transkrypcje/k/x.md"}),
                         d("2026-10-06"))


class TestScalanieWyrazen(unittest.TestCase):

    def test_scal_wyrazenia_dopisuje_i_nie_nadpisuje(self):
        w = {"fakty_czasowe": [{"typ": "termin"}, {"typ": "termin", "wyrazenie": "istniejące"}],
             "pozycje": [{"id": "T1"}, {"id": "T2", "termin_wyrazenie": "stare"}]}
        n, ostrz = uzupelnij.scal_wyrazenia(w, {"fakty": {"0": "do piątku", "1": "nowe", "7": "x"},
                                                "terminy": {"T1": "w czwartek", "T2": "nowe", "T9": "y"}})
        self.assertEqual(n, 2)
        self.assertEqual(w["fakty_czasowe"][0]["wyrazenie"], "do piątku")
        self.assertEqual(w["fakty_czasowe"][1]["wyrazenie"], "istniejące")
        self.assertEqual(w["pozycje"][0]["termin_wyrazenie"], "w czwartek")
        self.assertEqual(w["pozycje"][1]["termin_wyrazenie"], "stare")
        self.assertEqual(len(ostrz), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
