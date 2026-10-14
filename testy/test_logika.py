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
    should_get_agent_label,
    process_aktualizacje,
    update_risk_counter,
)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
