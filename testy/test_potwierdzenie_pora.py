#!/usr/bin/env python3
"""test_potwierdzenie_pora.py – potwierdzenie karty i zwolnienie spraw działają o KAŻDEJ porze i w KAŻDY dzień (po 18:00, w niedzielę, w święto),
a okno wysyłki 8–18 blokuje wyłącznie wysyłkę maili do klienta. Bez sieci i bez modelu. Uruchomienie: python3 testy/test_potwierdzenie_pora.py
"""

import copy
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import karta_klienta as kk
import wyslij as wy
import zasady
import test_wysylka as tw

Z = zasady.wczytaj_zasady()
W = Z["wysylka"]
E = Z["etykiety"]

KARTA_NOWA = {"klient": "motor-lux", "nazwa": "Motor-Lux", "nowy_klient": True, "kontakty": [
    {"imie": "Agnieszka Wróbel", "email": "agnieszka@motorlux.pl", "rola": "koordynatorka", "potwierdzony": False}],
    "decydenci": [], "decydenci_wniosek": [{"imie": "Agnieszka Wróbel", "rola": "wniosek z rozmowy, do potwierdzenia"}],
    "zakazy": [], "otwarte_sprawy": {}, "ryzyka": {}}

# (opis, moment UTC): lato 2026 = UTC+2; okno wysyłki to dni robocze 8:00–18:00 czasu polskiego
MOMENTY = [
    ("środa 07:00 PL (przed oknem)", datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc), False),
    ("środa 12:00 PL (w oknie)", datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc), True),
    ("środa 17:59 PL (ostatnia minuta okna)", datetime(2026, 10, 14, 15, 59, tzinfo=timezone.utc), True),
    ("środa 18:00 PL (po oknie)", datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc), False),
    ("środa 23:30 PL (noc)", datetime(2026, 10, 14, 21, 30, tzinfo=timezone.utc), False),
    ("sobota 11:00 PL", datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc), False),
    ("niedziela 03:00 PL", datetime(2026, 10, 18, 1, 0, tzinfo=timezone.utc), False),
    ("niedziela 12:00 PL", datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc), False),
    ("niedziela 22:00 PL", datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc), False),
]
if W.get("swieta"):
    d = datetime.fromisoformat(W["swieta"][0])
    MOMENTY.append((f"święto {W['swieta'][0]} 12:00", datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc), False))


def srodowisko(teraz, potwierdzona=True):
    """Środowisko jak w jobie wysyłki: zgłoszenie karty (Done albo nie), 2 sprawy wstrzymane motor-lux, 1 sprawa innego klienta wstrzymana
    i szkic maila czekający na „Wyślij”."""
    karta_mail = copy.deepcopy(tw.KARTA)
    zgl = [tw.zg(41, labels=("Konfiguracja", "Wyślij", "Szkic gotowy"), stan="Done"),
           tw.zg(50, klient="motor-lux", labels=("Do weryfikacji", E["karta"]), stan="Done" if potwierdzona else "Todo", tytul="Potwierdź kartę klienta Motor-Lux"),
           tw.zg(51, klient="motor-lux", labels=("Konfiguracja", "Dla agenta", E["wstrzymane"]), stan="Todo", tytul="Niedziela jazdy"),
           tw.zg(52, klient="motor-lux", labels=("Czeka na klienta", E["wstrzymane"]), stan="Todo", tytul="Lista modeli"),
           tw.zg(53, klient="inny", labels=("Dla agenta", E["wstrzymane"]), stan="Todo", tytul="Sprawa innego klienta")]
    s = tw.Srodowisko(zgl, {"RIN-41": [tw.komentarz_szkicu()]}, karta=karta_mail, teraz=teraz)
    karty = {"motor-lux": copy.deepcopy(KARTA_NOWA), "inny": {"klient": "inny", "nowy_klient": True}}
    s.wczytaj_karte = lambda klient: karty.get(klient, s.karta)
    s.zapisz_karte = lambda klient, karta: karty.__setitem__(klient, karta) if klient in karty else setattr(s, "karta", karta)
    s.karty = karty
    return s


class TestPotwierdzenieOKazdejPorze(unittest.TestCase):

    def test_zwolnienie_dziala_o_kazdej_porze_i_w_kazdy_dzien(self):
        for opis, teraz, _w_oknie in MOMENTY:
            with self.subTest(moment=opis):
                s = srodowisko(teraz)
                w = kk.zwolnij_potwierdzone(s)
                self.assertEqual(w, [{"klient": "motor-lux", "zwolnione": ["RIN-51", "RIN-52"]}], opis)
                for ident in ("RIN-51", "RIN-52"):
                    self.assertNotIn(E["wstrzymane"], s.linear.zgloszenia[ident]["labels"], f"{opis}: {ident} wraca do obiegu")
                self.assertIn(E["wstrzymane"], s.linear.zgloszenia["RIN-53"]["labels"], "inny klient nietknięty")
                self.assertNotIn("nowy_klient", s.karty["motor-lux"], "karta potwierdzona")
                self.assertTrue(any("Karta klienta Motor-Lux potwierdzona" in m for m in s.slack.wiadomosci), opis)

    def test_niepotwierdzona_karta_nie_jest_zwalniana_o_zadnej_porze(self):
        for opis, teraz, _ in MOMENTY:
            with self.subTest(moment=opis):
                s = srodowisko(teraz, potwierdzona=False)
                self.assertEqual(kk.zwolnij_potwierdzone(s), [])
                self.assertIn(E["wstrzymane"], s.linear.zgloszenia["RIN-51"]["labels"])

    def test_okno_wysylki_blokuje_tylko_maile_a_nie_zwolnienie(self):
        for opis, teraz, w_oknie in MOMENTY:
            with self.subTest(moment=opis):
                s = srodowisko(teraz)
                self.assertEqual(wy.okno_wysylki(teraz, W)[0], w_oknie, f"{opis}: okno wysyłki")
                wyniki = wy.uruchom(s)                                # mail do klienta: tylko w oknie
                mail = next(x for x in wyniki if x.get("zgloszenie") == "RIN-41")
                self.assertEqual(mail["status"], "wyslane" if w_oknie else "czeka", opis)
                self.assertEqual(len(s.poczta.wyslane), 1 if w_oknie else 0, opis)
                w = kk.zwolnij_potwierdzone(s)                        # potwierdzenie karty: zawsze, także gdy mail czeka na okno
                self.assertEqual([x["zwolnione"] for x in w], [["RIN-51", "RIN-52"]], opis)

    def test_zwolnienie_dziala_mimo_bledu_poczty(self):
        s = srodowisko(MOMENTY[1][1])
        s.poczta.blad = "SMTP niedostępny"
        self.assertEqual(wy.uruchom(s)[-1]["status"], "czeka")
        self.assertEqual(len(kk.zwolnij_potwierdzone(s)), 1)

    def test_kod_zwolnienia_nie_czyta_czasu_ani_okna(self):
        kod = (ROOT / "karta_klienta.py").read_text(encoding="utf-8")
        wykonywalny = re.sub(r'""".*?"""', "", kod, flags=re.S)
        for zakazane in ("teraz", "okno_wysylki", "lokalnie", "godziny", "dni_robocze", "swieta", "datetime", "weekday"):
            self.assertNotIn(zakazane, wykonywalny, f"karta_klienta.py nie może zależeć od pory ({zakazane})")

    def test_workflow_ma_osobny_krok_bez_warunku_czasu_przed_wysylka(self):
        t = (ROOT / ".github/workflows/sprawdz-maile.yml").read_text(encoding="utf-8")
        a = t.index("- name: Potwierdzenia kart i zwolnienie wstrzymanych spraw")
        b = t.index("- name: Wyślij zatwierdzone maile")
        self.assertLess(a, b, "zwolnienie przed wysyłką: błąd poczty go nie blokuje")
        krok = t[a:b]
        self.assertIn("python3 karta_klienta.py", krok)
        self.assertIn("if: ${{ !cancelled() }}", krok)
        for zakazane in ("hour", "date ", "weekday", "godzin"):
            self.assertNotIn(zakazane, krok)
        self.assertIn('cron: "*/15 * * * *"', t, "cron co 15 minut o każdej porze")
        self.assertNotRegex(t, r"cron: \"[^\"]*\d+-\d+[^\"]*\"", "cron bez ograniczenia godzin")

    def test_wysylka_main_ma_bezpiecznik_ktory_nie_blokuje_poczty(self):
        kod = (ROOT / "wyslij.py").read_text(encoding="utf-8")
        self.assertIn("karta_klienta.zwolnij_potwierdzone(s)", kod)
        self.assertRegex(kod, r"try:[^\n]*\n\s+for w in karta_klienta\.zwolnij_potwierdzone\(s\):")


if __name__ == "__main__":
    unittest.main(verbosity=1)
