#!/usr/bin/env python3
"""test_logika.py – testy jednostkowe logiki (bez sieci i bez modelu AI).

Uruchomienie:
  python3 testy/test_logika.py
  python3 -m pytest testy/test_logika.py -v
"""

import hashlib
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from linear_sync import (
    dodaj_zakazy,
    process_aktualizacje,
    should_get_agent_label,
    update_risk_counter,
)
from sekrety import czysc, wyczysc_srodowisko
from daty import compute_windows, has_temporal_word


# ── should_get_agent_label ────────────────────────────────────────────────────

class TestShouldGetAgentLabel(unittest.TestCase):

    def test_bug_dostaje_agent(self):
        self.assertTrue(should_get_agent_label(
            {"typ": "bug", "pewnosc": "wysoka", "rodzaj": "blad"}))

    def test_zmiana_konfiguracji_dostaje_agent(self):
        self.assertTrue(should_get_agent_label(
            {"typ": "zmiana_konfiguracji", "pewnosc": "wysoka"}))

    def test_poprawka_bazy_wiedzy_dostaje_agent(self):
        self.assertTrue(should_get_agent_label(
            {"typ": "poprawka_bazy_wiedzy", "pewnosc": "wysoka"}))

    def test_konflikt_z_zakazem_blokuje_agent(self):
        self.assertFalse(should_get_agent_label({
            "typ": "bug", "pewnosc": "wysoka",
            "konflikt_z_zakazem": {"zakaz": "Z1", "uzasadnienie": "x"},
        }))

    def test_niska_pewnosc_blokuje_agent(self):
        self.assertFalse(should_get_agent_label(
            {"typ": "bug", "pewnosc": "niska"}))

    def test_nowa_funkcja_blokuje_agent(self):
        self.assertFalse(should_get_agent_label(
            {"typ": "bug", "pewnosc": "wysoka", "rodzaj": "nowa_funkcja"}))

    def test_pomysl_produktowy_nie_dostaje_agent(self):
        self.assertFalse(should_get_agent_label(
            {"typ": "pomysl_produktowy", "pewnosc": "wysoka"}))

    def test_finanse_nie_dostaje_agent(self):
        self.assertFalse(should_get_agent_label(
            {"typ": "finanse", "pewnosc": "wysoka"}))


# ── process_aktualizacje ──────────────────────────────────────────────────────

class TestProcessAktualizacje(unittest.TestCase):

    def _wynik(self, source, meeting_date, klucz, nowy_status):
        return {
            "zrodlo": source,
            "spotkanie": {"data": meeting_date},
            "aktualizacje_spraw": [{
                "klucz_sprawy": klucz,
                "nowy_status": nowy_status,
                "cytat": "cytat testowy",
                "uzasadnienie": "uzasadnienie testowe",
            }],
        }

    def _karta(self, klucz, issue_source, issue_date):
        return {
            "zakazy": [],
            "otwarte_sprawy": {
                klucz: {
                    "linear_id": "fake-uuid",
                    "identifier": "RIN-99",
                    "url": "https://linear.app/test/RIN-99",
                    "tytul": "Sprawa testowa",
                    "zrodla": [issue_source],
                    "data_spotkania": issue_date,
                }
            },
        }

    def test_ta_sama_rozmowa_odrzucona(self):
        src = "ops/transkrypcje/klient/2026-10-06-call.md"
        wynik = self._wynik(src, "2026-10-06", "test-klucz", "zrob_teraz")
        karta = self._karta("test-klucz", src, "2026-10-06")
        n = process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True, meeting_date="2026-10-06")
        self.assertEqual(n, 0, "Ta sama rozmowa nie powinna aktualizować spraw")

    def test_ta_sama_data_odrzucona(self):
        src_old = "ops/transkrypcje/klient/2026-10-06-call.md"
        src_new = "ops/transkrypcje/klient/2026-10-06-call2.md"
        wynik = self._wynik(src_new, "2026-10-06", "test-klucz", "zrob_teraz")
        karta = self._karta("test-klucz", src_old, "2026-10-06")
        n = process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True, meeting_date="2026-10-06")
        self.assertEqual(n, 0, "Rozmowa z tą samą datą nie powinna aktualizować")

    def test_pozniejsza_data_akceptowana(self):
        src_old = "ops/transkrypcje/klient/2026-10-06-call.md"
        src_new = "ops/transkrypcje/klient/2026-10-14-call.md"
        wynik = self._wynik(src_new, "2026-10-14", "test-klucz", "zrob_teraz")
        karta = self._karta("test-klucz", src_old, "2026-10-06")
        n = process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True, meeting_date="2026-10-14")
        self.assertEqual(n, 1, "Późniejsza rozmowa powinna aktualizować")

    def test_nieznana_sprawa_pomijana(self):
        src = "ops/transkrypcje/klient/2026-10-14-call.md"
        wynik = self._wynik(src, "2026-10-14", "nieznana-sprawa", "zrob_teraz")
        karta = {"zakazy": [], "otwarte_sprawy": {}}
        n = process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True, meeting_date="2026-10-14")
        self.assertEqual(n, 0, "Sprawa nieznana z karty powinna być pominięta")


# ── daty.py: compute_windows ──────────────────────────────────────────────────

class TestComputeWindows(unittest.TestCase):

    def test_blokada_globalna_pokrywa_wszystkie_dni(self):
        start = date(2026, 10, 7)
        blocks = [(date(2026, 10, 7), date(2026, 10, 9))]
        windows = compute_windows(start, blocks)
        # Pierwsze okno powinno zacząć się od dnia roboczego po blokadzie
        self.assertTrue(len(windows) >= 1)
        self.assertEqual(windows[0]["od"], "2026-10-12")

    def test_brak_blokad_daje_ciagly_horyzont(self):
        start = date(2026, 10, 7)
        windows = compute_windows(start, [])
        self.assertEqual(len(windows), 1)
        self.assertIsNone(windows[0]["do"], "Bez deadline okno powinno być otwarte")

    def test_weekendy_pomijane(self):
        # 2026-10-10 to sobota, więc kolejny dzień roboczy = poniedziałek 2026-10-12
        start = date(2026, 10, 7)
        blocks = [(date(2026, 10, 7), date(2026, 10, 10))]
        windows = compute_windows(start, blocks)
        self.assertEqual(windows[0]["od"], "2026-10-12", "Po blokadzie Mon 10-12, nie Tue 10-13")

    def test_deadline_osiagalny_ogranicza_okno(self):
        # deadline po blokadzie: okno od 10-12 (Mon) do 10-14 (Wed)
        start = date(2026, 10, 7)
        blocks = [(date(2026, 10, 7), date(2026, 10, 10))]
        windows = compute_windows(start, blocks, deadline=date(2026, 10, 14))
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["od"], "2026-10-12")
        self.assertEqual(windows[0]["do"], "2026-10-14")


# ── daty.py: has_temporal_word ────────────────────────────────────────────────

class TestHasTemporalWord(unittest.TestCase):

    def test_urlop_wykrywany(self):
        self.assertTrue(has_temporal_word("mam urlop od poniedzialku"))

    def test_po_urlopie_wykrywany(self):
        self.assertTrue(has_temporal_word("zrobimy to po urlopie"))

    def test_nie_wczesniej_wykrywany(self):
        self.assertTrue(has_temporal_word("nie wcześniej niż w przyszłym tygodniu"))

    def test_miesiecznie_wykrywany(self):
        self.assertTrue(has_temporal_word("rozliczane miesięcznie"))

    def test_neutralny_cytat_nie_wykrywany(self):
        self.assertFalse(has_temporal_word("zadzwonił w sobotę rano"))

    def test_sam_dzien_tygodnia_nie_wykrywany(self):
        self.assertFalse(has_temporal_word("spotkanie odbyło się we wtorek"))


# ── update_risk_counter ───────────────────────────────────────────────────────

class TestRiskCounter(unittest.TestCase):

    def test_dwa_zrodla_eskaluja(self):
        karta = {}
        item = {"temat_ryzyka": "konkurencja", "cytat": ["cytat"]}
        esc1, _ = update_risk_counter(karta, item, "src1.md", "2026-10-01")
        esc2, _ = update_risk_counter(karta, item, "src2.md", "2026-10-02")
        self.assertFalse(esc1, "Pierwsze źródło nie eskaluje")
        self.assertTrue(esc2, "Drugie różne źródło powinno eskalować")

    def test_to_samo_zrodlo_nie_eskaluje(self):
        karta = {}
        item = {"temat_ryzyka": "konkurencja", "cytat": ["cytat"]}
        update_risk_counter(karta, item, "src1.md", "2026-10-01")
        esc2, _ = update_risk_counter(karta, item, "src1.md", "2026-10-02")
        self.assertFalse(esc2, "To samo źródło dwa razy nie eskaluje")

    def test_rozne_tematy_nie_mieszaja(self):
        karta = {}
        item_konk = {"temat_ryzyka": "konkurencja", "cytat": ["c"]}
        item_cena = {"temat_ryzyka": "cena_budzet", "cytat": ["c"]}
        update_risk_counter(karta, item_konk, "src1.md", "2026-10-01")
        esc, _ = update_risk_counter(karta, item_cena, "src2.md", "2026-10-02")
        self.assertFalse(esc, "Różne tematy ryzyka nie powinny sumować się")


# ── rejestr sha256 ────────────────────────────────────────────────────────────

class TestRegistry(unittest.TestCase):

    def test_ten_sam_hash_w_rejestrze(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="wb") as f:
            f.write(b"tresc transkrypcji testowej")
            path = f.name
        try:
            h = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            registry = {h: {"klient": "test", "przetworzone": "2026-10-01 00:00:00"}}
            self.assertIn(h, registry, "Hash transkrypcji powinien być w rejestrze")
        finally:
            os.unlink(path)

    def test_inna_tresc_inny_hash(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="wb") as f:
            f.write(b"tresc A")
            path_a = f.name
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="wb") as f:
            f.write(b"tresc B")
            path_b = f.name
        try:
            ha = hashlib.sha256(Path(path_a).read_bytes()).hexdigest()
            hb = hashlib.sha256(Path(path_b).read_bytes()).hexdigest()
            self.assertNotEqual(ha, hb, "Różne treści dają różne hashe")
        finally:
            os.unlink(path_a)
            os.unlink(path_b)


# ── strażnik aktualizacji: liczy się pochodzenie sprawy, nie komentarze ────────

class TestStraznikAktualizacjiPochodzenie(unittest.TestCase):

    def _wynik(self, source, meeting_date, klucz="k"):
        return {"zrodlo": source, "spotkanie": {"data": meeting_date},
                "aktualizacje_spraw": [{"klucz_sprawy": klucz, "nowy_status": "zrob_teraz",
                                        "cytat": "c", "uzasadnienie": "u"}]}

    def _karta(self, zrodla, extra=None):
        info = {"linear_id": "x", "identifier": "RIN-1", "url": "u", "tytul": "t", "zrodla": zrodla}
        info.update(extra or {})
        return {"zakazy": [], "otwarte_sprawy": {"k": info}}

    def test_komentarz_z_pozniejszej_rozmowy_nie_blokuje_aktualizacji(self):
        # sprawa pochodzi z 10-06, 10-13 tylko dopisała komentarz; aktualizacja z 10-13 ma przejść
        a, b = "ops/t/2026-10-06-a.md", "ops/t/2026-10-13-b.md"
        n = process_aktualizacje(None, self._wynik(b, "2026-10-13"), self._karta([a, b]),
                                 {}, {}, dry_run=True, meeting_date="2026-10-13")
        self.assertEqual(n, 1)

    def test_starsza_rozmowa_nie_aktualizuje_sprawy_z_nowszej(self):
        a, b = "ops/t/2026-10-06-a.md", "ops/t/2026-10-13-b.md"
        n = process_aktualizacje(None, self._wynik(a, "2026-10-06"), self._karta([b]),
                                 {}, {}, dry_run=True, meeting_date="2026-10-06")
        self.assertEqual(n, 0)

    def test_juz_zastosowana_aktualizacja_pomijana(self):
        a, b = "ops/t/2026-10-06-a.md", "ops/t/2026-10-13-b.md"
        karta = self._karta([a, b], {"aktualizacje_zrodla": [b]})
        n = process_aktualizacje(None, self._wynik(b, "2026-10-13"), karta,
                                 {}, {}, dry_run=True, meeting_date="2026-10-13")
        self.assertEqual(n, 0)


# ── zakazy: unikalne id między rozmowami ──────────────────────────────────────

class TestDodajZakazy(unittest.TestCase):

    def _z(self, zid, klucz, cytat, tytul="t"):
        return {"id": zid, "sekcja": 4, "klucz_sprawy": klucz, "tytul": tytul,
                "opis": "", "cytat": [cytat], "wlasciciel": "M"}

    def test_kolizja_id_dostaje_nowy_numer_zamiast_zostac_pominieta(self):
        karta = {"zakazy": [{"id": "Z1", "tytul": "stary", "cytat": ["stary cytat"]},
                            {"id": "Z2", "tytul": "stary2", "cytat": ["stary cytat 2"]}],
                 "historia_zakazow": [{"id": "Z3", "tytul": "uchylony", "cytat": ["x"]}]}
        n = dodaj_zakazy(karta, [self._z("Z1", "nowy", "nowy cytat")], "src-nowe.md")
        self.assertEqual(n, 1)
        ids = [z["id"] for z in karta["zakazy"]]
        self.assertEqual(ids, ["Z1", "Z2", "Z4"], "nowy zakaz dostaje Z4 (Z3 jest w historii)")
        self.assertEqual(karta["zakazy"][-1]["klucz_sprawy"], "nowy")
        self.assertEqual(karta["zakazy"][-1]["zrodlo"], "src-nowe.md")

    def test_ponowna_analiza_nie_dubluje_zakazow(self):
        karta = {"zakazy": [], "historia_zakazow": []}
        z = self._z("Z1", "nowy", "cytat")
        self.assertEqual(dodaj_zakazy(karta, [z], "src.md"), 1)
        self.assertEqual(dodaj_zakazy(karta, [z], "src.md"), 0)
        self.assertEqual(len(karta["zakazy"]), 1)

    def test_stary_zakaz_bez_klucza_rozpoznany_po_id_i_tytule(self):
        karta = {"zakazy": [{"id": "Z1", "tytul": "t", "cytat": ["a"]}]}
        self.assertEqual(dodaj_zakazy(karta, [self._z("Z1", "k", "b", tytul="t")], "s.md"), 0)


# ── licznik ryzyk: ponowna analiza nie zawyża ─────────────────────────────────

class TestRiskCounterIdempotencja(unittest.TestCase):

    def test_ta_sama_wzmianka_dwa_razy_zapisana_raz(self):
        karta = {}
        item = {"temat_ryzyka": "konkurencja", "cytat": ["ten sam cytat"]}
        update_risk_counter(karta, item, "src.md", "2026-10-13")
        update_risk_counter(karta, item, "src.md", "2026-10-14")
        self.assertEqual(len(karta["ryzyka"]["konkurencja"]), 1)


# ── czyszczenie kluczy ────────────────────────────────────────────────────────

class TestCzyszczenieKluczy(unittest.TestCase):

    def test_usuwa_biale_i_niewidoczne_znaki(self):
        brudny = "lin_api_ABC\u2028123\n \u2029\u00a0\ufeff\u200b\t"
        self.assertEqual(czysc(brudny), "lin_api_ABC123")

    def test_czysty_klucz_bez_zmian(self):
        self.assertEqual(czysc("sk-ant-oat01-abc_DEF-123"), "sk-ant-oat01-abc_DEF-123")

    def test_none_daje_pusty(self):
        self.assertEqual(czysc(None), "")

    def test_wyczysc_srodowisko_zmienia_tylko_sekrety_i_nie_drukuje_wartosci(self):
        import os, io, contextlib
        stare = {k: os.environ.get(k) for k in ("LINEAR_API_KEY", "RINVO_MODEL")}
        try:
            os.environ["LINEAR_API_KEY"] = "lin_api_SEKRET\u2028\n"
            os.environ["RINVO_MODEL"] = "model z spacja "
            bufor = io.StringIO()
            with contextlib.redirect_stderr(bufor):
                zmienione = wyczysc_srodowisko()
            self.assertEqual(zmienione, ["LINEAR_API_KEY"])
            self.assertEqual(os.environ["LINEAR_API_KEY"], "lin_api_SEKRET")
            self.assertEqual(os.environ["RINVO_MODEL"], "model z spacja ")
            self.assertNotIn("SEKRET", bufor.getvalue())
        finally:
            for k, v in stare.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


# ── Slack: stałe linie także gdy 0 ────────────────────────────────────────────

class TestSlack(unittest.TestCase):

    def _wynik(self):
        import tempfile
        d = {"spotkanie": {"data": "2026-10-13"},
             "pozycje": [{"id": "T1", "sekcja": 1, "tytul": "Zadanie", "klucz_sprawy": "k",
                          "pewnosc": "wysoka", "konflikt_z_zakazem": None}],
             "aktualizacje_spraw": [], "ostrzezenia_dat": []}
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(d, f)
        f.close()
        return Path(f.name)

    def test_wszystkie_linie_obecne_nawet_gdy_zero(self):
        import przetworz
        p = self._wynik()
        try:
            msg = przetworz.build_slack_summary("klient-testowy", p, "")
        finally:
            p.unlink()
        for nazwa in ("Zamknięte: 0", "Wznowione: 0", "Zablokowane przez zakaz: 0",
                      "Powtarzające się ryzyka: 0", "Wielu klientów: 0", "Do weryfikacji: 0"):
            self.assertIn(nazwa, msg)

    def test_parsowanie_zdarzen_z_linear_sync(self):
        import przetworz
        out = ("  ✓ RIN-39 (adres) → zamknieta\n  ✓ RIN-48 (wstep) → zrob_teraz\n"
               "  = RIN-51 (paw) → zrob_teraz (już w tym stanie, bez zmian)\n"
               "  [pominięto aktualizację] RIN-1 (x): ta sama rozmowa (s)\n"
               "  ↑ Powtarzające się ryzyko: RIN-62 (vd) | Tytuł ryzyka\n"
               "  ★ Wielu klientów: RIN-76 (excel) | Tytuł funkcji\n")
        z = przetworz.parse_sync_zdarzenia(out)
        self.assertEqual(z["zamkniete"], [("RIN-39", "adres")])
        self.assertEqual(z["wznowione"], [("RIN-48", "wstep")], "pominięte i już-w-stanie nie liczą się")
        self.assertEqual(z["ryzyka"], [("RIN-62", "vd", "Tytuł ryzyka")])
        self.assertEqual(z["wielu_klientow"], [("RIN-76", "excel", "Tytuł funkcji")])


# ── daty.py: termin z zakresem ────────────────────────────────────────────────

class TestTerminZZakresem(unittest.TestCase):

    def _okna(self, fakty, klucz="wstep"):
        import subprocess, tempfile
        d = {"spotkanie": {"data": "2026-10-13"},
             "pozycje": [{"id": "K1", "sekcja": 2, "klucz_sprawy": klucz, "cytat": ["x"]}],
             "fakty_czasowe": fakty}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "wynik.json"
            f.write_text(json.dumps(d), encoding="utf-8")
            subprocess.run([sys.executable, "-I", str(Path(__file__).parent.parent / "daty.py"), str(f)],
                           check=True, capture_output=True)
            wynik = json.loads(f.read_text(encoding="utf-8"))
        return next(o["okna"] for o in wynik["okna_czasowe"] if o["klucz_sprawy"] == klucz)

    def test_koniec_zakresu_terminu_jest_deadlinem(self):
        # „środa i czwartek": termin 14–15.10 → okno 14–15, a nie samo 14
        okna = self._okna([{"typ": "termin", "od": "2026-10-14", "do": "2026-10-15",
                            "dotyczy": "wstep", "cytat": "x"}])
        self.assertEqual(okna, [{"od": "2026-10-14", "do": "2026-10-15"}])

    def test_termin_bez_do_dziala_jak_dawniej(self):
        okna = self._okna([{"typ": "termin", "od": "2026-10-15", "dotyczy": "wstep", "cytat": "x"}])
        self.assertEqual(okna, [{"od": "2026-10-14", "do": "2026-10-15"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
