#!/usr/bin/env python3
"""test_notatka_spotkania.py – notatka przed spotkaniem (notatka_spotkania.py) bez sieci i bez modelu.

Dane klienta (karta, wyniki, rozmowy) są prawdziwe z repozytorium; Linear, model i Slack to atrapy.
Uruchomienie: python3 testy/test_notatka_spotkania.py
"""

import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import linear_sync
import notatka_spotkania as ns
import notatki
import szkice
import test_wysylka as tw
import wyslij as wy
import zasady

Z = zasady.wczytaj_zasady()
W = Z["wysylka"]
DZIS = date(2026, 10, 14)

ZG_STATUSY = [
    tw.zg(41, tytul="Toruń podaje sobotę do 14:00", stan="In Progress", labels=("Konfiguracja",)),
    tw.zg(42, tytul="Filtr statusu nie zawęża listy", stan="Done", labels=("Błąd",)),
    tw.zg(58, tytul="Integracja Rinvo z CRM dealera", stan="Backlog", labels=("Produkt",)),
    tw.zg(65, klient="klinika-usmiech", tytul="Sopot piątek", stan="In Progress"),
    tw.zg(78, tytul="Notatka przed spotkaniem: Potwierdzenie spotkania", stan="Todo", labels=("Zadanie",)),
]


def ryzyko(i):
    return {"nazwa": f"RIN-6{i}: ryzyko {i}", "argument": f"Argument {i}: na starej bazie 70 numerów dało 41 odebranych i 23 pełne rozmowy.",
            "stanowisko": f"Stanowisko {i}: nie licytujemy się, pokazujemy wyniki."}


def odpowiedz(ryzyka=3, pytania=4, tematy=2, **nadpisz):
    d = {"ryzyka": [ryzyko(i) for i in range(ryzyka)], "pytania": [f"Pytanie {i}?" for i in range(pytania)],
         "tematy": [{"temat": f"Temat {i}", "status": "w toku", "krok": "pokazać"} for i in range(tematy)]}
    d.update(nadpisz)
    return json.dumps(d, ensure_ascii=False)


class Sro(tw.Srodowisko):
    def __init__(self, odp=None, **kw):
        super().__init__(ZG_STATUSY, karta=linear_sync.load_karta("auto-tama"), claude=tw.AtrapaClaude(odp or odpowiedz()), **kw)
        self.katalog_wynikow = ROOT / "wyniki"
        self.odswiez = False
        self.linear.zgloszenia["RIN-78"] = ZG_STATUSY[-1]

    def wczytaj_karte(self, klient):
        return linear_sync.load_karta(klient) if klient == "auto-tama" else {"klient": klient, "kontakty": [], "zakazy": []}


class Baza(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(ROOT)

    def tearDown(self):
        os.chdir(self._cwd)

    def uruchom(self, s, dzis=DZIS):
        return ns.uruchom(s, dzis, ["auto-tama"])


class TestWyborSpotkan(Baza):

    def _sp(self, dzis):
        karta = linear_sync.load_karta("auto-tama")
        naj = notatki.najnowsze_pozycje("auto-tama")
        return ns.spotkania_do_notatki("auto-tama", karta, naj, Z, dzis)

    def test_dzien_przed_spotkaniem_z_karty(self):
        sp = self._sp(date(2026, 10, 14))
        self.assertEqual([x["data"] for x in sp], [date(2026, 10, 15)])
        self.assertIn("Potwierdzenie spotkania Marek–Paweł", sp[0]["tytul"])
        self.assertTrue(sp[0]["zadanie"].startswith("RIN-"))

    def test_w_dniu_spotkania_tez_ale_nie_dwa_dni_wczesniej_ani_po(self):
        self.assertEqual(len(self._sp(date(2026, 10, 15))), 1)
        self.assertEqual(self._sp(date(2026, 10, 13)), [])
        self.assertEqual(self._sp(date(2026, 10, 16)), [])

    def test_szkolenie_handlowcow_nie_dostaje_notatki(self):
        self.assertFalse(any("szkolen" in x["tytul"].lower() for x in self._sp(date(2026, 10, 26))))


class TestTworzenieNotatki(Baza):

    def test_powstaja_md_i_pdf_jedna_strona(self):
        s = Sro()
        w = self.uruchom(s)[0]
        self.assertEqual(w["status"], "gotowa")
        md, pdf = ns.sciezki_notatki("auto-tama", date(2026, 10, 15), s.katalog_materialow)
        self.assertTrue(md.exists() and pdf.exists())
        self.assertEqual(md.name, "notatka-2026-10-15.md")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(ns.liczba_stron(pdf), 1)
        tekst = md.read_text(encoding="utf-8")
        self.assertIn("Materiał wewnętrzny, nie dla klienta", tekst)
        self.assertEqual(tekst.count("### "), 3, "trzy ryzyka")
        self.assertEqual(tekst.count("- Pytanie"), 4)
        self.assertIn("Nasz argument", tekst)
        self.assertIn("Stanowisko", tekst)

    def test_nigdy_szkic_maila_ani_wysylka(self):
        s = Sro()
        self.uruchom(s)
        self.assertEqual(s.poczta.wyslane, [])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-78"]["labels"])
        self.assertFalse(any("Szkic maila" in z[2] for z in s.linear.zdarzenia if z[0] == "komentarz"))

    def test_zadanie_notatki_nigdy_nie_dostaje_szkicu_mimo_slow_o_wysylaniu(self):
        z = tw.zg(78, tytul="Notatka przed spotkaniem: Wysłać zaproszenie i zestawienie", stan="Todo", labels=("Zadanie", "Decyzja człowieka"),
                  opis="## Cel\n\nWysłać zaproszenie.\n\n## Kontekst\n\n> Napisz mi.")
        s = tw.Srodowisko([z], claude=tw.AtrapaClaude(tw.json_szkic()))
        self.assertEqual(szkice.uruchom(s), [])
        self.assertEqual(s.claude.prompty, [])

    def test_statusy_z_lineara_w_prompcie_a_nie_z_opisu_zgloszenia(self):
        s = Sro()
        self.uruchom(s)
        p = s.claude.prompty[0]
        self.assertIn("STATUSY W LINEARZE", p)
        self.assertIn("RIN-41 | In Progress | Toruń podaje sobotę do 14:00", p)
        self.assertIn("RIN-42 | Done | Filtr statusu nie zawęża listy", p)
        self.assertIn("RIN-58 | Backlog | Integracja Rinvo z CRM dealera", p)
        self.assertNotIn("RIN-65", p, "zgłoszenia innego klienta nie wchodzą")
        self.assertNotIn("RIN-78 |", p, "notatka nie opisuje samej siebie")
        self.assertIn("ważniejsze niż opisy zgłoszeń", p)
        self.assertIn("In Progress to „w toku”", p)

    def test_prompt_wymaga_faktow_jednej_strony_i_uczciwosci_o_integracji(self):
        s = Sro()
        self.uruchom(s)
        p = s.claude.prompty[0]
        self.assertIn("WYŁĄCZNIE faktów", p)
        self.assertIn("Dokładnie 3 ryzyka", p)
        self.assertIn("3 do 5 pytań", p)
        self.assertIn("integracji z CRM (z systemem klienta) nie mamy", p)
        self.assertIn("maksymalnie 5 tematów", p)
        self.assertIn("jednej stronie A4", p)
        for fakt in ("Siedemdziesiąt numerów, odebrało czterdzieści jeden", "dwadzieścia trzy", "Peugeota 208", "VoiceDesk"):
            self.assertIn(fakt, p, f"fakty z rozmów: {fakt}")

    def test_prompt_zawiera_ryzyka_z_karty_i_zakazy(self):
        s = Sro()
        self.uruchom(s)
        p = s.claude.prompty[0]
        self.assertIn("RYZYKA (omów dokładnie te)", p)
        self.assertIn("VoiceDesk złożył Pawłowi pisemną ofertę", p)
        self.assertIn("Z4:", p)
        self.assertIn("kasia", p.lower())

    def test_idempotencja_druga_proba_nic_nie_robi(self):
        s = Sro()
        self.uruchom(s)
        liczba, slack, kom = len(s.claude.prompty), len(s.slack.wiadomosci), len(s.linear.zdarzenia)
        w = self.uruchom(s)[0]
        self.assertEqual(w["status"], "istnieje")
        self.assertEqual((len(s.claude.prompty), len(s.slack.wiadomosci), len(s.linear.zdarzenia)), (liczba, slack, kom))

    def test_sucho_nic_nie_tworzy(self):
        s = Sro()
        s.sucho = True
        self.assertEqual(self.uruchom(s)[0]["status"], "powstalaby")
        self.assertEqual((s.claude.prompty, s.slack.wiadomosci, s.linear.zdarzenia), ([], [], []))
        self.assertFalse(s.katalog_materialow.exists())

    def test_odswiezenie_nadpisuje_pliki_bez_powtarzania_powiadomien(self):
        s = Sro()
        self.uruchom(s)
        s.odswiez = True
        s.claude.odpowiedzi = [odpowiedz(pytania=5)]
        w = self.uruchom(s)[0]
        self.assertEqual(w["status"], "gotowa")
        self.assertEqual(len(s.slack.wiadomosci), 1, "Slack tylko raz")
        md, _ = ns.sciezki_notatki("auto-tama", date(2026, 10, 15), s.katalog_materialow)
        self.assertEqual(md.read_text(encoding="utf-8").count("- Pytanie"), 5)


class TestPowiadomienia(Baza):

    def test_slack_i_komentarz_zadania_z_linkiem(self):
        s = Sro()
        w = self.uruchom(s)[0]
        url = "https://github.com/Rembolekk/Rinvo/blob/main/" + w["pdf"]
        self.assertTrue(w["pdf"].endswith("notatka-2026-10-15.pdf"))
        self.assertEqual(s.slack.wiadomosci, [f":memo: Notatka przed spotkaniem gotowa: <{url}|auto-tama, 15.10>"])
        zadanie = next(k for k in s.linear.zdarzenia if k[0] == "komentarz")
        self.assertEqual(zadanie[1], "RIN-78", "komentarz w zadaniu notatki")
        self.assertIn(url, zadanie[2])
        self.assertIn("nie dla klienta", zadanie[2])

    def test_odrzucona_notatka_nie_powiadamia(self):
        s = Sro(odpowiedz(ryzyka=2))
        w = self.uruchom(s)[0]
        self.assertEqual(w["status"], "odrzucona")
        self.assertEqual((s.slack.wiadomosci, s.linear.zdarzenia), ([], []))
        md, pdf = ns.sciezki_notatki("auto-tama", date(2026, 10, 15), s.katalog_materialow)
        self.assertFalse(md.exists() or pdf.exists(), "po odrzuceniu nie zostają pliki")


class TestWalidacja(Baza):

    def _powody(self, **kw):
        r = [ryzyko(i) for i in range(3)]
        p = [f"P{i}?" for i in range(4)]
        t = []
        r = kw.get("ryzyka", r)
        p = kw.get("pytania", p)
        return ns.sprawdz(r, p, kw.get("tematy", t), kw.get("fakty", "70 numerów 41 odebranych"), [("klinika-usmiech", "Klinika Uśmiech")], W)

    def test_poprawna_przechodzi(self):
        self.assertEqual(self._powody(), [])

    def test_liczba_ryzyk_i_pytan(self):
        self.assertTrue(self._powody(ryzyka=[ryzyko(0)] * 2))
        self.assertTrue(self._powody(ryzyka=[ryzyko(0)] * 4))
        self.assertTrue(self._powody(pytania=["a?", "b?"]))
        self.assertTrue(self._powody(pytania=[f"{i}?" for i in range(6)]))
        self.assertTrue(self._powody(tematy=[{"temat": str(i), "status": "x", "krok": "y"} for i in range(6)]))

    def test_kwota_spoza_faktow_to_odrzucenie_a_z_faktow_przechodzi(self):
        r = [ryzyko(0), ryzyko(1), {**ryzyko(2), "argument": "Oferta kosztuje 1500 zł miesięcznie."}]
        self.assertTrue(any("kwota" in p for p in self._powody(ryzyka=r)))
        self.assertEqual(self._powody(ryzyka=r, fakty="Cennik: 1500 zł miesięcznie"), [])

    def test_obietnice_integracji_i_terminow(self):
        for tekst in ("Zintegrujemy się z waszym CRM do końca roku. Integracji nie mamy.", "Integracja będzie w tym kwartale. Nie mamy jej dziś.",
                      "Gwarantujemy wynik."):
            r = [ryzyko(0), ryzyko(1), {**ryzyko(2), "stanowisko": tekst}]
            self.assertTrue(any("obietnica" in p for p in self._powody(ryzyka=r)), tekst)

    def test_integracja_bez_uczciwego_nie_mamy_to_odrzucenie(self):
        r = [ryzyko(0), ryzyko(1), {**ryzyko(2), "argument": "Paweł pyta o integrację z CRM."}]
        self.assertTrue(any("uczciwego" in p for p in self._powody(ryzyka=r)))
        r[2]["argument"] = "Paweł pyta o integrację z CRM. Integracji nie mamy."
        self.assertEqual(self._powody(ryzyka=r), [])

    def test_stan_todo_to_nie_placeholder_ale_todo_w_tresci_juz_tak(self):
        r = [ryzyko(0), ryzyko(1), {**ryzyko(2), "argument": "RIN-62 jest w stanie Todo. Marek ma 70 numerów."}]
        self.assertEqual(self._powody(ryzyka=r), [])
        r[2]["argument"] = "[do potwierdzenia: wynik]"
        self.assertTrue(any("uzupełnienia" in p for p in self._powody(ryzyka=r)))

    def test_inny_klient_to_odrzucenie(self):
        r = [ryzyko(0), ryzyko(1), {**ryzyko(2), "argument": "Podobnie w Klinika Uśmiech."}]
        self.assertTrue(any("innego klienta" in p for p in self._powody(ryzyka=r)))

    def test_model_poprawia_sie_po_odrzuceniu(self):
        s = Sro()
        s.claude.odpowiedzi = [odpowiedz(ryzyka=2), odpowiedz()]
        self.assertEqual(self.uruchom(s)[0]["status"], "gotowa")
        self.assertIn("POPRZEDNIA WERSJA ODRZUCONA", s.claude.prompty[1])
        self.assertIn("ryzyk ma być 3", s.claude.prompty[1])

    def test_notatka_dluzsza_niz_strona_jest_odrzucona_po_probach(self):
        dluga = odpowiedz(ryzyka=3)
        d = json.loads(dluga)
        for r in d["ryzyka"]:
            r["argument"] = ("Bardzo długi argument o wynikach starej bazy. " * 120)
        s = Sro(json.dumps(d, ensure_ascii=False))
        w = self.uruchom(s)[0]
        self.assertEqual(w["status"], "odrzucona")
        self.assertIn("ma być jedna", w["powod"])
        self.assertEqual(len(s.claude.prompty), 3)


class TestWorkflow(unittest.TestCase):

    def test_notatki_w_porannym_podsumowaniu(self):
        t = (ROOT / ".github/workflows/podsumowanie.yml").read_text(encoding="utf-8")
        self.assertIn("python3 notatka_spotkania.py", t)
        self.assertIn("fpdf2", t)
        self.assertIn("ops/materialy", t)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", t)

    def test_zasady_maja_repo_do_linkow(self):
        self.assertEqual(Z["notatki"]["repo_github"], "Rembolekk/Rinvo")


if __name__ == "__main__":
    unittest.main(verbosity=1)
