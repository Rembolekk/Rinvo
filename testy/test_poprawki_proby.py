#!/usr/bin/env python3
"""test_poprawki_proby.py – poprawki po próbie generalnej: maskowanie osób znanych, kotwice w cytatach, kolejność w workflow agenta,
wycofywanie przeterminowanych zaproszeń i notatek, limit sesji przy analizie rozmowy. Bez sieci i bez modelu.

Nazwy testów zaczynają się od numeru punktu (p1_ … p5_). Uruchomienie: python3 testy/test_poprawki_proby.py
"""

import contextlib
import copy
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import dla_czlowieka as dc
import higiena as hg
import limity
import notatka_spotkania as ns
import odmaskuj as od
import szkice
import wyslij as wy
import zasady
import test_wysylka as tw
import uruchom as ur

Z = zasady.wczytaj_zasady()
W = Z["wysylka"]
MIG = ROOT / "testy/migawka_demo"

TRANSKRYPCJA = """# Hotele X × Rinvo: call

15 października 2026 (czwartek), 13:00–13:27, Google Meet.

## Uczestnicy

- **Joanna Wiśniewska**, kierowniczka recepcji, Hotele X
- **Marek Rewoliński**, Rinvo

Wspominani, nieobecni: **pan Robert** (dyrektor, decyduje o kosztach i o Kołobrzegu), **Tomek** (recepcja Sopot).

## Transkrypcja

**Joanna:** Z panem Robertem rozmawiać dopiero po miesiącu. Pan Robert nie lubi maili.

**Marek:** Przygotuję wycenę i wyślę Robertowi?

**Joanna:** Wyślij mnie, ja mu przekażę. Do Roberta nie piszcie bezpośrednio. Wczoraj dzwonił pan Kowalski z rezerwacji, pani Nowak też. Tomek to sprawdzi.
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._t.cleanup()


# ── 1. maskowanie: osoby znane nie, osoby trzecie tak ─────────────────────────

class P1Maskowanie(Tmp):

    def test_p1_znana_osoba_w_kazdej_odmianie_nie_jest_osoba_trzecia(self):
        znane = hg._tokeny_znane(["pan Robert", "Tomek", "Joanna Wiśniewska"])
        for tok in ("Robert", "Roberta", "Robertowi", "Robertem", "Robercie", "Tomek", "Tomka", "Tomkowi", "Joanny", "Joannie", "Wiśniewskiej"):
            self.assertTrue(hg.jest_znany(tok, znane), tok)
        for tok in ("Kowalski", "Nowak", "Robotnik", "Toma"):
            self.assertFalse(hg.jest_znany(tok, znane), tok)

    def test_p1_osoby_z_naglowka_to_wszystko_co_pogrubione_przed_transkrypcja(self):
        osoby = hg.osoby_z_naglowka(TRANSKRYPCJA)
        self.assertIn("pan Robert", osoby)
        self.assertIn("Tomek", osoby)
        self.assertIn("Joanna Wiśniewska", osoby)
        self.assertNotIn("Joanna", osoby, "pogrubienie w samej transkrypcji (mówca) nie liczy się do nagłówka")

    def test_p1_pan_robert_w_kazdej_odmianie_nie_jest_maskowany_a_klienci_koncowi_tak(self):
        nazw = hg.nazwiska_koncowe(TRANSKRYPCJA)
        self.assertEqual(nazw, {"Kowalski", "Nowak"})
        t, nazw, k = hg.maskuj_zrodlo(TRANSKRYPCJA)
        self.assertIn("panem Robertem", t)
        self.assertIn("Do Roberta nie piszcie", t)
        self.assertNotIn("Kowalski", t)
        self.assertNotIn("Nowak", t)
        self.assertEqual(k["nazwisko"], 2)

    def test_p1_wynik_z_robertem_nie_traci_osoby_a_gosc_zostaje_zamaskowany(self):
        wynik = {"zrodlo": "x.md", "spotkanie": {"uczestnicy": ["Joanna"], "wspominani": ["pan Robert"]},
                 "pozycje": [{"tytul": "Przekazać panu Robertowi wycenę", "opis": "Dzwonił pan Kowalski. Do Roberta nie piszemy.", "wlasciciel": "pan Robert",
                              "cytat": ["Do Roberta nie piszcie bezpośrednio."]}]}
        licznik = hg.maskuj_wynik(wynik, TRANSKRYPCJA, [], [])
        p = wynik["pozycje"][0]
        self.assertEqual(p["tytul"], "Przekazać panu Robertowi wycenę")
        self.assertEqual(p["wlasciciel"], "pan Robert")
        self.assertIn("pan [nazwisko]", p["opis"])
        self.assertNotIn("Kowalski", p["opis"])
        self.assertEqual(licznik["nazwisko"], 1)

    def test_p1_kontakty_i_decydenci_z_karty_tez_sa_znani(self):
        tekst = "## Transkrypcja\n**A:** Dzwoniła pani Wiśniewska i pan Zieliński.\n"
        self.assertEqual(hg.nazwiska_koncowe(tekst, []), {"Wiśniewska", "Zieliński"})
        self.assertEqual(hg.nazwiska_koncowe(tekst, ["Joanna Wiśniewska"]), {"Zieliński"})

    def test_p1_rodzina_do_przywrocenia_jest_jednoznaczna(self):
        self.assertEqual(od.rodzina_do_przywrocenia(TRANSKRYPCJA), "Robert")
        self.assertIsNone(od.rodzina_do_przywrocenia("## Transkrypcja\n**A:** pan Kowalski.\n"), "bez znanej osoby nic nie przywracamy")

    def test_p1_odmiana_i_odtwarzanie_z_transkrypcji(self):
        self.assertEqual([od.odmien("Robert", p) for p in ("mian", "dop", "cel", "narz", "miej")], ["Robert", "Roberta", "Robertowi", "Robertem", "Robercie"])
        t, zm = od.odmaskuj_tekst("Do [nazwisko] nie piszcie bezpośrednio.", TRANSKRYPCJA, "Robert")
        self.assertEqual(t, "Do Roberta nie piszcie bezpośrednio.")
        self.assertEqual(zm[0][2], "z transkrypcji")
        t, zm = od.odmaskuj_tekst("Pan [nazwisko] decyduje; rozmowa z panem [nazwisko]; przekażemy panu [nazwisko]; nie piszemy do pana [nazwisko].", "", "Robert")
        self.assertEqual(t, "Pan Robert decyduje; rozmowa z panem Robertem; przekażemy panu Robertowi; nie piszemy do pana Roberta.")

    def test_p1_przeliczenie_wyniku_bez_modelu_przywraca_osobe_i_maskuje_od_nowa(self):
        Path("ops/klienci/hx").mkdir(parents=True)
        Path("ops/klienci/hx/karta.json").write_text(json.dumps({"klient": "hx", "kontakty": [{"imie": "Joanna Wiśniewska"}]}), encoding="utf-8")
        Path("t.md").write_text(TRANSKRYPCJA, encoding="utf-8")
        wynik = {"zrodlo": "t.md", "spotkanie": {"uczestnicy": ["Joanna"], "wspominani": ["pan [nazwisko]"]},
                 "pozycje": [{"tytul": "Przekazać panu [nazwisko] wycenę", "opis": "Pan [nazwisko] czeka. Dzwonił pan [nazwisko].",
                              "cytat": ["Do [nazwisko] nie piszcie bezpośrednio."], "wlasciciel": "pan [nazwisko]"}]}
        Path("w.json").write_text(json.dumps(wynik, ensure_ascii=False), encoding="utf-8")
        zmiany, rdzen = od.przelicz_wynik("w.json", "t.md", "hx", ".")
        self.assertEqual(rdzen, "Robert")
        w = json.loads(Path("w.json").read_text(encoding="utf-8"))
        p = w["pozycje"][0]
        self.assertEqual(p["tytul"], "Przekazać panu Robertowi wycenę")
        self.assertEqual(p["cytat"], ["Do Roberta nie piszcie bezpośrednio."], "cytat dosłownie z transkrypcji")
        self.assertEqual(w["spotkanie"]["wspominani"], ["pan Robert"])
        self.assertNotIn("[nazwisko]", json.dumps(w, ensure_ascii=False))
        self.assertEqual(w["kontrola"]["maskowanie"]["liczba"], 0)

    def test_p1_karta_i_linear_tez_wracaja_do_poprawnej_formy(self):
        Path("ops/klienci/hx").mkdir(parents=True)
        karta = {"klient": "hx", "zakazy": [{"id": "Z1", "tytul": "Nie pisać do [nazwisko] bezpośrednio", "opis": "Pan [nazwisko] nie lubi maili.",
                                              "cytat": ["Do [nazwisko] nie piszcie bezpośrednio."]}]}
        Path("ops/klienci/hx/karta.json").write_text(json.dumps(karta, ensure_ascii=False), encoding="utf-8")
        import linear_sync
        o = linear_sync.write_karta_md
        linear_sync.write_karta_md = lambda k, c: Path("ops/klienci/hx/karta.md").write_text("md", encoding="utf-8")
        self.addCleanup(setattr, linear_sync, "write_karta_md", o)
        zm = od.przelicz_karte("hx", TRANSKRYPCJA, "Robert", ".")
        k = json.loads(Path("ops/klienci/hx/karta.json").read_text(encoding="utf-8"))
        self.assertEqual(k["zakazy"][0]["tytul"], "Nie pisać do Roberta bezpośrednio")
        self.assertEqual(k["zakazy"][0]["opis"], "Pan Robert nie lubi maili.")
        self.assertEqual(k["zakazy"][0]["cytat"], ["Do Roberta nie piszcie bezpośrednio."])
        self.assertEqual(len(zm), 3)

        wywolania = []

        def gql(key, q, v=None):
            wywolania.append((q, v))
            if "comments" in q:
                return {"issues": {"nodes": [{"id": "i1", "identifier": "RIN-5", "title": "[hx] Uzupełnij: Rozmowa z panem [nazwisko]",
                                              "description": "Pan [nazwisko] czeka.", "comments": {"nodes": [{"id": "c1", "body": "Dla pana [nazwisko]"}]}},
                                             {"id": "i2", "identifier": "RIN-6", "title": "[hx] Zwykłe", "description": "ok", "comments": {"nodes": []}}]}}
            return {}
        zm = od.przelicz_linear("k", gql, "hx", TRANSKRYPCJA, "Robert", True)
        self.assertEqual({(i, co) for i, co, _, _ in zm}, {("RIN-5", "title"), ("RIN-5", "description"), ("RIN-5", "komentarz")})
        zapisy = [v for q, v in wywolania if v and "input" in v]
        self.assertEqual(zapisy[0]["input"]["title"], "[hx] Uzupełnij: Rozmowa z panem Robertem")
        self.assertEqual(zapisy[0]["input"]["description"], "Pan Robert czeka.")
        self.assertEqual(len(zapisy), 2, "tylko zgłoszenie z maską było zmieniane")

    def test_p1_prawdziwa_transkrypcja_proby_hotele_baltyk(self):
        sciezka = MIG / "ops/transkrypcje/hotele-baltyk/2026-10-15-call-wdrozeniowy.md"
        self.assertTrue(sciezka.exists())
        self.assertEqual(hg.nazwiska_koncowe(sciezka.read_text(encoding="utf-8"), ["Joanna Wiśniewska"]), set(), "pan Robert nie jest maskowany")


# ── 2. kotwice w cytatach zamiast kluczy ──────────────────────────────────────

class P2Kotwice(unittest.TestCase):

    OCZEKIWANIA = ROOT / "testy/oczekiwania"

    def _wynik(self, wariant, nazwa):
        return json.loads((MIG / ("wyniki" if wariant == "stare" else "wyniki_proba") / "auto-tama" / nazwa / "wynik.json").read_text(encoding="utf-8"))

    def test_p2_zaden_test_nie_jest_zakotwiczony_w_nazwie_klucza(self):
        for plik in self.OCZEKIWANIA.glob("*.json"):
            for e in json.loads(plik.read_text(encoding="utf-8")):
                self.assertNotIn("klucz_sprawy", e, f"{plik.name}: {e.get('opis')}")

    def test_p2_kotwice_rozwiazuja_sie_w_obu_wersjach_nazw_kluczy(self):
        e13 = json.loads((self.OCZEKIWANIA / "auto-tama-2026-10-13-call-statusowy.json").read_text(encoding="utf-8"))
        kotwice = [e for e in e13 if "kotwica_cytatu" in e]
        self.assertGreaterEqual(len(kotwice), 15)
        for wariant in ("stare", "proba"):
            wynik = self._wynik(wariant, "2026-10-13-call-statusowy")
            for e in kotwice:
                odnalezione = [k for a in ur._alternatywy(e["kotwica_cytatu"]) if len(k := ur.klucze_z_kotwicy(wynik, a)) == 1]
                self.assertTrue(odnalezione, f"{wariant}: {e['opis']}")

    def test_p2_te_same_sprawy_inne_nazwy_ta_sama_kotwica(self):
        a = ur.klucze_z_kotwicy(self._wynik("stare", "2026-10-13-call-statusowy"), "Adres we Włocławku działa, puściłam sobie test")
        b = ur.klucze_z_kotwicy(self._wynik("proba", "2026-10-13-call-statusowy"), "Adres we Włocławku działa, puściłam sobie test")
        self.assertEqual((a, b), ({"adres-wloclawek"}, {"adres-salonu-wloclawek"}))

    def test_p2_niejednoznaczna_albo_nieznaleziona_kotwica_to_fail(self):
        wynik = {"pozycje": [{"klucz_sprawy": "a", "cytat": ["wspólny fragment"]}, {"klucz_sprawy": "b", "cytat": ["wspólny fragment i więcej"]}],
                 "aktualizacje_spraw": []}

        class Ctx:
            pass
        ctx = Ctx()
        ctx.wynik = wynik
        status, powod = ur.check(ctx, {"typ_sprawdzania": "aktualizacja", "kotwica_cytatu": "wspólny fragment", "oczekiwany_nowy_status": "x"})
        self.assertEqual(status, "fail")
        self.assertIn("niejednoznaczna", powod)
        status, powod = ur.check(ctx, {"typ_sprawdzania": "aktualizacja", "kotwica_cytatu": "czegoś takiego nie ma", "oczekiwany_nowy_status": "x"})
        self.assertEqual(status, "fail")
        self.assertIn("nie znaleziono", powod)

    def test_p2_alternatywy_wystarczy_jedna(self):
        wynik = {"pozycje": [{"id": "T1", "sekcja": 1, "status": "zrob_teraz", "klucz_sprawy": "a", "cytat": ["Toruńska 120."]}], "aktualizacje_spraw": []}

        class Ctx:
            karta, prosby, klient = {}, {}, "x"
        ctx = Ctx()
        ctx.wynik = wynik
        exp = {"fragment_cytatu": ["Toruńska 120. Godziny bez zmian", "Toruńska 120."], "oczekiwana_sekcja": 1}
        self.assertEqual(ur.check(ctx, exp)[0], "pass")
        exp["fragment_cytatu"] = ["nie ma", "też nie ma"]
        self.assertEqual(ur.check(ctx, exp)[0], "fail")

    def test_p2_testy_zalezne_od_innego_klienta_sa_pomijane_gdy_go_nie_ma(self):
        e13 = json.loads((self.OCZEKIWANIA / "auto-tama-2026-10-13-call-statusowy.json").read_text(encoding="utf-8"))
        zalezne = [e for e in e13 if e.get("wymaga_klienta")]
        self.assertEqual(len(zalezne), 3, "Excel: pozycja z etykietą Wielu klientów, prosby.json z 2 klientami i Linear")
        self.assertTrue(all(e["wymaga_klienta"] == "klinika-usmiech" for e in zalezne))

        class Ctx:
            wynik = {}
        with tempfile.TemporaryDirectory() as t:
            ur.ROOT, stary = Path(t), ur.ROOT
            try:
                self.assertEqual(ur.check(Ctx(), zalezne[0])[0], "skip", "brak karty kliniki: SKIP")
                (Path(t) / "ops/klienci/klinika-usmiech").mkdir(parents=True)
                (Path(t) / "ops/klienci/klinika-usmiech/karta.json").write_text("{}", encoding="utf-8")
                self.assertNotEqual(ur.check(Ctx(), zalezne[0])[0], "skip", "klient jest: test się wykonuje")
            finally:
                ur.ROOT = stary

    def test_p2_wynik_z_proby_przechodzi_oczekiwania_offline_na_cytatach(self):
        """Uruchomienie na wynikach z próby (15.10): kotwice rozwiązują się mimo innych nazw kluczy; zostaje tylko różnica w klasyfikacji modelu."""
        w = ROOT / "testy/migawka_demo/wyniki_proba/auto-tama/2026-10-13-call-statusowy/wynik.json"
        r = subprocess.run([sys.executable, "testy/uruchom.py", str(w), "testy/oczekiwania/auto-tama-2026-10-13-call-statusowy.json"],
                           cwd=ROOT, capture_output=True, text=True)
        niepowodzenia = [l for l in r.stdout.splitlines() if l.startswith("  FAIL")]
        for l in niepowodzenia:
            self.assertNotIn("brak aktualizacji_spraw", l)
        self.assertNotIn("brak aktualizacji_spraw", r.stdout)
        self.assertNotIn("kotwica", r.stdout)


# ── 3. agent w workflow: najpierw scalanie ────────────────────────────────────

class P3KolejnoscAgenta(unittest.TestCase):

    def test_p3_scalanie_przed_braniem_nowych_zadan(self):
        t = (ROOT / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertLess(t.index("python3 agent_scal.py"), t.index("python3 agent.py"))
        self.assertLess(t.index("python3 agent.py"), t.index("python3 szkice.py"))

    def test_p3_kroki_w_yaml_w_tej_kolejnosci(self):
        import re
        t = (ROOT / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        nazwy = re.findall(r"- name: (.+)", t)
        self.assertLess(nazwy.index("Agent scala gotowe PR"), nazwy.index("Agent wykonuje zgłoszenia"))


# ── 4. zaproszenie na minione spotkanie i notatka po godzinie spotkania ───────

def zg_zaproszenie(numer=41, labels=("Konfiguracja", "Szkic gotowy", "Wyślij"), stan="Todo"):
    return tw.zg(numer, labels=labels, stan=stan, tytul="Wysłać zaproszenie na spotkanie z Pawłem")


def komentarz_ze_spotkaniem(data="2026-10-14", godzina="09:00"):
    sp = {"data": data, "godzina": godzina, "czas_min": 30, "miejsce": "Toruń", "tytul": "Spotkanie"}
    return {"id": "c1", "createdAt": "2026-10-13T10:00:00Z", "body": wy.format_komentarza_szkicu("Kasia Malinowska", "Spotkanie", tw.DOBRA, ["RIN-41"], sp)}


class P4Spotkania(unittest.TestCase):

    def test_p4_spotkanie_minelo_uwzglednia_godzine(self):
        sp = {"data": "2026-10-14", "godzina": "10:00"}
        self.assertFalse(wy.spotkanie_minelo(sp, datetime(2026, 10, 14, 7, 59, tzinfo=timezone.utc), W), "09:59 w Polsce: jeszcze nie")
        self.assertTrue(wy.spotkanie_minelo(sp, datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc), W), "10:00 w Polsce: już")
        self.assertFalse(wy.spotkanie_minelo({"data": "zła"}, tw.SROD, W))

    def test_p4_walidacja_spotkania_wie_o_godzinie(self):
        fakty = "Spotkanie 14.10 o 09:00"
        sp = {"data": "2026-10-14", "godzina": "09:00", "czas_min": 30}
        self.assertEqual(wy.waliduj_spotkanie(sp, fakty, date(2026, 10, 14), W, tw.SROD)[1], wy.POWOD_MINELO, "środa 10:00, spotkanie o 9:00")
        self.assertIsNotNone(wy.waliduj_spotkanie(sp, fakty, date(2026, 10, 14), W, datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc))[0])

    def test_p4_wyslij_nie_wysyla_zaproszenia_na_minione_spotkanie_i_wycofuje_szkic(self):
        s = tw.Srodowisko([zg_zaproszenie()], {"RIN-41": [komentarz_ze_spotkaniem("2026-10-14", "09:00")]})
        w = wy.uruchom(s)[0]
        self.assertEqual(w["status"], "wycofane")
        self.assertEqual(s.poczta.wyslane, [], "bez wysyłki")
        z = s.linear.zgloszenia["RIN-41"]
        self.assertNotIn("Wyślij", z["labels"])
        self.assertNotIn("Szkic gotowy", z["labels"])
        self.assertNotIn("Do weryfikacji", z["labels"], "to nie błąd szkicu")
        komentarze = [k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"]
        self.assertTrue(any(k.startswith("Szkic zaproszenia wycofany: spotkanie (2026-10-14 09:00) już minęło") for k in komentarze))
        self.assertTrue(any("Szkic wycofany: spotkanie już minęło" in k["body"] for k in s.linear.kom["RIN-41"]), "stary komentarz ze szkicem zastąpiony adnotacją")

    def test_p4_przyszle_spotkanie_wychodzi_normalnie(self):
        s = tw.Srodowisko([zg_zaproszenie()], {"RIN-41": [komentarz_ze_spotkaniem("2026-10-15", "10:00")]},
                          )
        s.fakty_zgloszen = lambda grupa: "Spotkanie w czwartek 15.10 o 10:00"
        w = wy.uruchom(s)[0]
        self.assertEqual(w["status"], "wyslane")

    def test_p4_szkic_z_blokiem_w_opisie_tez_sie_wycofuje_a_blok_znika(self):
        sp = {"data": "2026-10-14", "godzina": "09:00", "czas_min": 30, "miejsce": "", "tytul": "Spotkanie"}
        mail = {"do": "Kasia Malinowska", "temat": "Spotkanie", "tresc": tw.DOBRA, "zgloszenia": ["RIN-41"], "spotkanie": sp, "kiedy": "teraz"}
        blok = dc.zloz_blok("Wyślij.", "klient", mail, dc.RUCHY_MAIL)
        z = tw.zg(41, labels=("Konfiguracja", "Szkic gotowy", "Wyślij"), stan="Todo", opis=dc.zloz_opis(blok, tw.OPIS), tytul="Zaproszenie")
        z["title"] = "[auto-tama] Wyślij: Zaproszenie"
        s = tw.Srodowisko([z], {})
        self.assertEqual(wy.uruchom(s)[0]["status"], "wycofane")
        po = s.linear.zgloszenia["RIN-41"]
        self.assertEqual(po["title"], "[auto-tama] Zaproszenie")
        self.assertFalse(po["description"].startswith(dc.START))
        self.assertIn("## Cel", po["description"])
        self.assertIsNone(dc.parsuj_blok(po["description"]))

    def test_p4_szkice_sprzataja_przeterminowane_oczekujace_na_wyslij(self):
        s = tw.Srodowisko([zg_zaproszenie(labels=("Konfiguracja", "Szkic gotowy"))], {"RIN-41": [komentarz_ze_spotkaniem("2026-10-14", "09:00")]})
        wyniki = szkice.uruchom(s)
        self.assertEqual([w["status"] for w in wyniki if w["status"] == "wycofane"], ["wycofane"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_p4_wycofane_zaproszenie_nie_jest_pisane_od_nowa_przy_kazdym_przebiegu(self):
        s = tw.Srodowisko([zg_zaproszenie(labels=("Konfiguracja",))], {})
        s.linear.zgloszenia["RIN-41"]["description"] = tw.OPIS
        s.linear.komentarz(s.linear.zgloszenia["RIN-41"], "Szkic zaproszenia wycofany: spotkanie (2026-10-14 09:00) już minęło. Nic nie zostało wysłane.")
        pytania = len(s.claude.prompty)
        szkice.uruchom(s)
        self.assertEqual(len(s.claude.prompty), pytania, "model nie jest wołany")
        self.assertTrue(szkice.juz_wycofany_przeterminowany(s, s.linear.zgloszenia["RIN-41"]))

    def test_p4_generowany_szkic_z_minionym_spotkaniem_to_komentarz_a_nie_do_weryfikacji(self):
        sp = {"data": "2026-10-14", "godzina": "09:00", "czas_min": 30, "miejsce": "Toruń", "tytul": "Spotkanie"}
        z = tw.zg(41, labels=("Konfiguracja", "Dla agenta"), stan="Todo", tytul="Wysłać zaproszenie na spotkanie 14.10 o 09:00",
                  opis=tw.OPIS.replace("Godziny w sobotę do 15:00.", "Wysłać zaproszenie na spotkanie 14.10 o 09:00."))
        s = tw.Srodowisko([z], claude=tw.AtrapaClaude(tw.json_szkic(spotkanie=sp)))
        w = szkice.uruchom(s)
        self.assertEqual(w[0]["status"], "wycofane")
        self.assertNotIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertEqual(s.poczta.wyslane, [])

    KARTA_NOTATKI = {"klient": "auto-tama", "otwarte_sprawy": {
        "spotkanie-z-pawlem": {"identifier": "RIN-10", "tytul": "Potwierdzenie spotkania Marek–Paweł (15.10, 10:00, Toruń)"},
        "notatka-spotkanie-z-pawlem": {"identifier": "RIN-11", "tytul": "Notatka przed spotkaniem: spotkanie", "termin": "2026-10-15"}}}

    def _sp(self, teraz, dzis=date(2026, 10, 15)):
        import notatki
        z = {"klucz": "notatka-spotkanie-z-pawlem", "termin": date(2026, 10, 15), "tytul": "Notatka przed spotkaniem: spotkanie"}
        stary = notatki.zbierz_zadania
        notatki.zbierz_zadania = lambda *a, **kw: [z]
        try:
            return ns.spotkania_do_notatki("auto-tama", self.KARTA_NOTATKI, {}, Z, dzis, teraz)
        finally:
            notatki.zbierz_zadania = stary

    def test_p4_notatka_nie_powstaje_po_godzinie_spotkania(self):
        przed = datetime(2026, 10, 15, 7, 59, tzinfo=timezone.utc)      # 9:59 w Polsce, spotkanie o 10:00
        po = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)          # 10:00
        poznej = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
        dzien_wczesniej = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(len(self._sp(przed)), 1)
        self.assertEqual(self._sp(po), [])
        self.assertEqual(self._sp(poznej), [])
        self.assertEqual(len(self._sp(dzien_wczesniej, date(2026, 10, 14))), 1, "dzień przed spotkaniem: notatka powstaje")
        self.assertEqual(len(self._sp(None)), 1, "bez czasu zachowanie jak dotąd")

    def test_p4_godzina_spotkania_z_tytulu_albo_opisu_pozycji(self):
        self.assertEqual(ns.godzina_spotkania("Spotkanie (15.10, 10:00, Toruń)", None), (10, 0))
        self.assertEqual(ns.godzina_spotkania("Spotkanie", {"tytul": "x", "opis": "w czwartek o 9:30"}), (9, 30))
        self.assertIsNone(ns.godzina_spotkania("Spotkanie w czwartek", {"tytul": "", "opis": ""}))

    def test_p4_bez_znanej_godziny_notatka_powstaje_jak_dotad(self):
        k = copy.deepcopy(self.KARTA_NOTATKI)
        k["otwarte_sprawy"]["spotkanie-z-pawlem"]["tytul"] = "Spotkanie z Pawłem w czwartek"
        import notatki
        stary = notatki.zbierz_zadania
        notatki.zbierz_zadania = lambda *a, **kw: [{"klucz": "notatka-spotkanie-z-pawlem", "termin": date(2026, 10, 15), "tytul": "Notatka"}]
        try:
            wynik = ns.spotkania_do_notatki("auto-tama", k, {}, Z, date(2026, 10, 15), datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc))
        finally:
            notatki.zbierz_zadania = stary
        self.assertEqual(len(wynik), 1)


# ── 5. limit sesji przy analizie rozmowy ──────────────────────────────────────

class P5Limit(Tmp):

    KOMUNIKATY = ("You've hit your session limit · resets 7pm (Europe/Warsaw)", "5-hour limit reached ∙ resets 3pm", "Claude AI usage limit reached|1760000000",
                  "Weekly limit reached. Resets Mon 9am", "Your credit balance is too low to access the Anthropic API", "API Error: 429 rate limit exceeded",
                  "Request rejected (429)", "You are out of extra usage")

    def test_p5_wzorce_obejmuja_komunikaty_limitu_sesji_i_nie_lapia_zwyklych_logow(self):
        for k in self.KOMUNIKATY:
            self.assertTrue(limity.czy_limit(k, Z), k)
        for k in ("OK", "Limit prób pozostaje 5", "Zapisano wynik.json", "Przypomnienie ma limit 0"):
            self.assertFalse(limity.czy_limit(k, Z), k)

    def test_p5_cli_czy_limit_zwraca_kod_wyjscia(self):
        for tekst, kod in ((self.KOMUNIKATY[0], 0), ("OK", 1)):
            r = subprocess.run([sys.executable, str(ROOT / "limity.py"), "--czy-limit", tekst], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, kod, tekst)

    def test_p5_kolejkowanie_rozmow_i_maili_oraz_jedno_powiadomienie(self):
        k = limity.Kolejka(Path("k.json"))
        k.dodaj("ops/transkrypcje/a/2026-10-15-call.md")
        self.assertTrue(k.powiadom_raz())
        self.assertFalse(k.powiadom_raz(), "jedna informacja na epizod")
        k.sukces()
        self.assertTrue(k.powiadom_raz())

    def _kopia_repo(self):
        kopia = self.root / "repo"
        shutil.copytree(ROOT, kopia, ignore=shutil.ignore_patterns(".git", "testy", "proba", "wyniki", "logi", "klienci", "*.pdf", "__pycache__", "*.html", "ops"))
        shutil.copytree(ROOT / "ops", kopia / "ops", ignore=shutil.ignore_patterns("materialy", "maile", "transkrypcje", ".*"))
        (kopia / "ops/klienci").mkdir(parents=True, exist_ok=True)
        (kopia / "ops/transkrypcje/alfa").mkdir(parents=True)
        (kopia / "ops/transkrypcje/alfa/2026-10-15-call.md").write_text(TRANSKRYPCJA, encoding="utf-8")
        return kopia

    def _fake_claude(self, kod, tekst):
        bin_ = self.root / "bin"
        bin_.mkdir(exist_ok=True)
        f = bin_ / "claude"
        f.write_text(f"#!/bin/sh\necho \"{tekst}\"\nexit {kod}\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        return bin_

    def _uruchom_przetworz(self, kod, tekst):
        kopia = self._kopia_repo()
        env = {**os.environ, "PATH": f"{self._fake_claude(kod, tekst)}:{os.environ['PATH']}", "CLAUDE_CODE_OAUTH_TOKEN": "token-testowy-1234567890",
               "LINEAR_API_KEY": "", "SLACK_WEBHOOK_URL": "", "RINVO_MODEL": "claude-test"}
        r = subprocess.run([sys.executable, "przetworz.py", "ops/transkrypcje/alfa/2026-10-15-call.md"], cwd=kopia, env=env, capture_output=True, text=True, timeout=120)
        return kopia, r

    def test_p5_limit_przy_analizie_rozmowy_z_kodem_bledu_idzie_do_kolejki_a_nie_na_czerwono(self):
        kopia, r = self._uruchom_przetworz(1, "You've hit your session limit · resets 7pm")
        self.assertEqual(r.returncode, 75, r.stderr[-400:] + r.stdout[-400:])
        kolejka = json.loads((kopia / "ops/.kolejka_limit.json").read_text(encoding="utf-8"))
        self.assertIn("ops/transkrypcje/alfa/2026-10-15-call.md", kolejka["oczekuje"])
        self.assertTrue(kolejka["powiadomiono"], "jedna informacja na Slacku na epizod (próba wysłania zapisana w stanie)")
        self.assertNotIn("BŁĄD w kroku", r.stderr)
        rejestr = kopia / "ops/.przetworzone.json"
        self.assertFalse(rejestr.exists() and "alfa" in rejestr.read_text(encoding="utf-8"), "nie zarejestrowane jako przetworzone")

    def test_p5_limit_zglaszany_kodem_0_bez_wyniku_tez_idzie_do_kolejki(self):
        kopia, r = self._uruchom_przetworz(0, "You've hit your session limit · resets 7pm")
        self.assertEqual(r.returncode, 75, r.stderr[-400:] + r.stdout[-400:])
        self.assertIn("ops/transkrypcje/alfa/2026-10-15-call.md", json.loads((kopia / "ops/.kolejka_limit.json").read_text(encoding="utf-8"))["oczekuje"])

    def test_p5_inny_blad_claude_nadal_jest_bledem(self):
        kopia, r = self._uruchom_przetworz(1, "Segmentation fault")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BŁĄD w kroku 'claude'", r.stderr)
        self.assertFalse((kopia / "ops/.kolejka_limit.json").exists() and "alfa" in (kopia / "ops/.kolejka_limit.json").read_text(encoding="utf-8"))

    def test_p5_diagnostyka_w_workflow_nie_robi_czerwonego_przebiegu_przy_limicie(self):
        for wf in ("przetworz-rozmowy", "sprawdz-maile", "agent"):
            t = (ROOT / f".github/workflows/{wf}.yml").read_text(encoding="utf-8")
            self.assertIn('python3 limity.py --czy-limit "$ODP"', t, wf)
            self.assertIn('echo "limit=true" >> "$GITHUB_OUTPUT"', t, wf)
            self.assertIn("python3 limity.py", t)
            self.assertIn("--powiadom", t, wf)
            self.assertIn("steps.diag.outputs.limit", t, wf)
        t = (ROOT / ".github/workflows/przetworz-rozmowy.yml").read_text(encoding="utf-8")
        self.assertLess(t.index("- name: Wykryj transkrypcje"), t.index("- name: Diagnostyka Claude"), "najpierw lista rozmów, żeby limit mógł je zakolejkować")
        self.assertIn("--kolejkuj /tmp/transkrypcje.txt", t)
        self.assertIn("steps.diag.outputs.limit != 'true'", t)
        m = (ROOT / ".github/workflows/sprawdz-maile.yml").read_text(encoding="utf-8")
        self.assertIn("--kolejkuj-maile /tmp/maile.txt", m)

    def test_p5_maile_w_limicie_oddaja_zuzyta_probe(self):
        Path("ops").mkdir()
        Path("ops/.maile.json").write_text(json.dumps({"przetworzone": {}, "nieznani": {}, "oczekujace": {"<a>": {"klient": "alfa", "plik": "ops/maile/alfa/m.md", "proby": 2, "status": "oczekuje"}}}), encoding="utf-8")
        Path("lista.txt").write_text("ops/maile/alfa/m.md\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            sys.argv = ["limity.py", "--kolejkuj-maile", "lista.txt"]
            limity.main()
        self.assertEqual(json.loads(Path("ops/.maile.json").read_text(encoding="utf-8"))["oczekujace"]["<a>"]["proby"], 1)
        self.assertIn("ops/maile/alfa/m.md", limity.Kolejka().lista())


class TestSpojnosc(unittest.TestCase):

    def test_kazdy_punkt_ma_test_i_wpis_w_readme(self):
        kod = Path(__file__).read_text(encoding="utf-8")
        r = (ROOT / "README.md").read_text(encoding="utf-8")
        for p in ("p1", "p2", "p3", "p4", "p5"):
            self.assertIn(f"def test_{p}_", kod)
        for fraza in ("odmaskuj.py", "kotwica_cytatu", "najpierw scalanie", "wycofuje się sam", "oczekuje na limit"):
            self.assertIn(fraza, r, fraza)


if __name__ == "__main__":
    unittest.main(verbosity=1)
