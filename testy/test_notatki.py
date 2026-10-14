#!/usr/bin/env python3
"""test_notatki.py – jedna notatka przed spotkaniem zamiast zadania na każde ryzyko (notatki.py).

Bez sieci i bez modelu (Linear podmieniony atrapą). Uruchomienie:  python3 testy/test_notatki.py
"""

import contextlib
import copy
import io
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import linear_sync
import notatki
import zasady

Z = zasady.wczytaj_zasady()
DZIS = date(2026, 10, 14)
URL = "https://linear.app/ws/issue/{}/x"


def wpis(ident, tytul, **extra):
    w = {"linear_id": f"id-{ident}", "identifier": ident, "url": URL.format(ident), "tytul": tytul, "zrodla": ["z.md"]}
    w.update(extra)
    return w


def pozycja(klucz, sekcja, typ, tytul, termin="brak", **extra):
    p = {"id": "X", "klucz_sprawy": klucz, "sekcja": sekcja, "typ": typ, "tytul": tytul, "termin": termin,
         "opis": "", "cytat": [f"Cytat do {klucz}."]}
    p.update(extra)
    return p


def karta_auto_tama():
    """Stan sprzed scalenia: trzy zadania przygotowawcze na ryzyka (RIN-78/79/80)."""
    return {"otwarte_sprawy": {
        "ryzyko-voicedesk": wpis("RIN-62", "VoiceDesk oferta"),
        "ryzyko-zla-interpretacja": wpis("RIN-63", "Paweł chciał wyłączyć agenta"),
        "ryzyko-crm": wpis("RIN-64", "Brak integracji CRM"),
        "spotkanie-z-pawlem": wpis("RIN-51", "Spotkanie z Pawłem 15.10 10:00"),
        "szkolenie-handlowcow": wpis("RIN-61", "Szkolenie handlowców: 27.10 10:00"),
        "swieze-leady": wpis("RIN-49", "Plik świeżych leadów", przypisanie={"komu": "agent"}),
        "decyzja-opel": wpis("RIN-75", "Decyzja o Oplu"),
        "przygotowanie-ryzyko-voicedesk": wpis("RIN-78", "Notatka: VoiceDesk"),
        "przygotowanie-ryzyko-zla-interpretacja": wpis("RIN-79", "Notatka: interpretacja"),
        "przygotowanie-ryzyko-crm": wpis("RIN-80", "Notatka: CRM"),
    }}


def najnowsze_auto_tama():
    wszystko = [
        pozycja("ryzyko-voicedesk", 5, "ryzyko_handlowe", "VoiceDesk oferta"),
        pozycja("ryzyko-zla-interpretacja", 5, "ryzyko_handlowe", "Paweł chciał wyłączyć agenta"),
        pozycja("ryzyko-crm", 5, "ryzyko_handlowe", "Brak integracji CRM"),
        pozycja("spotkanie-z-pawlem", 1, "spotkanie", "Spotkanie z Pawłem 15.10 10:00", termin="2026-10-15"),
        pozycja("szkolenie-handlowcow", 1, "spotkanie", "Szkolenie handlowców: 27.10 10:00", termin="2026-10-27"),
        pozycja("swieze-leady", 2, "czeka_na_klienta", "Plik świeżych leadów", termin="2026-10-15"),
        pozycja("decyzja-opel", 2, "czeka_na_klienta", "Decyzja o Oplu"),
    ]
    return {p["klucz_sprawy"]: (p, "ops/transkrypcje/auto-tama/2026-10-13-call.md") for p in wszystko}


class TestZbierzZadania(unittest.TestCase):

    def test_jedno_zadanie_na_zaplanowane_spotkanie_ze_wszystkimi_ryzykami_i_tematami(self):
        zad = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najnowsze_auto_tama(), Z, DZIS)
        self.assertEqual([z["klucz"] for z in zad], ["notatka-spotkanie-z-pawlem"],
                         "trzy ryzyka i jedno spotkanie z klientem = jedna notatka (szkolenie handlowców nie jest takim spotkaniem)")
        opis = zad[0]["item"]["opis"]
        self.assertIn("Ryzyka (3):", opis)
        for tytul in ("VoiceDesk oferta", "Paweł chciał wyłączyć agenta", "Brak integracji CRM"):
            self.assertIn(tytul, opis)
        self.assertIn("Otwarte tematy (", opis)
        self.assertIn("Plik świeżych leadów", opis)
        self.assertIn("Szkolenie handlowców", opis, "szkolenie jest otwartym tematem, choć nie osobną notatką")
        self.assertIn("(czeka na klienta, termin 15.10)", opis)
        self.assertIn("(otwarte, termin 27.10)", opis)
        self.assertNotIn("Notatka: VoiceDesk", opis, "dawne zadania przygotowawcze nie są tematami")
        self.assertIn("[Spotkanie z Pawłem 15.10 10:00](https://linear.app/ws/issue/RIN-51/x), 15.10.2026", opis)
        self.assertIn("„Cytat do ryzyko-voicedesk.”", opis, "ryzyka z cytatem")

    def test_status_tematu_wznowionego_przez_agenta_i_czekajacego(self):
        najn = najnowsze_auto_tama()
        najn["swieze-leady"][0]["sekcja"] = 1                    # wznowione po dostarczeniu pliku
        opis = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS)[0]["item"]["opis"]
        self.assertIn("(u agenta, termin 15.10)", opis)
        self.assertIn("(czeka na klienta)", opis)

    def test_nazwa_spotkania_z_tytulu_zgloszenia_a_nie_z_ostatniej_czynnosci(self):
        najn = najnowsze_auto_tama()
        najn["spotkanie-z-pawlem"][0]["tytul"] = "Wysłać zaproszenie na spotkanie z Pawłem"   # tytuł czynności
        zad = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS)[0]
        self.assertEqual(zad["tytul"], "Notatka przed spotkaniem: Spotkanie z Pawłem 15.10 10:00")
        self.assertNotIn("Wysłać zaproszenie", zad["item"]["opis"].split("**Ryzyka")[0])

    def test_listy_markdown_maja_puste_linie_przed_i_po_naglowkach(self):
        opis = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najnowsze_auto_tama(), Z, DZIS)[0]["item"]["opis"]
        self.assertIn("\n\n**Ryzyka (3):**\n\n- [", opis)
        self.assertIn("\n\n**Otwarte tematy (", opis)

    def test_zadanie_ma_kryteria_repo_i_idzie_do_agenta(self):
        item = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najnowsze_auto_tama(), Z, DZIS)[0]["item"]
        self.assertEqual(len(item["kryteria_akceptacji"]), 5)
        self.assertEqual(item["repo"], "rinvo-ops")
        self.assertEqual(item["termin"], "2026-10-15")
        self.assertEqual(zasady.przypisz(item, Z, {})["komu"], "agent")

    def test_dwa_spotkania_to_dwie_notatki_z_ta_sama_trescia(self):
        najn = najnowsze_auto_tama()
        najn["spotkanie-2"] = (pozycja("spotkanie-2", 2, "spotkanie", "Rozmowa z właścicielem", termin="2026-10-20"), "z.md")
        karta = karta_auto_tama()
        karta["otwarte_sprawy"]["spotkanie-2"] = wpis("RIN-90", "Rozmowa z właścicielem")
        zad = notatki.zbierz_zadania("auto-tama", karta, najn, Z, DZIS)
        self.assertEqual([z["klucz"] for z in zad], ["notatka-spotkanie-z-pawlem", "notatka-spotkanie-2"])
        for z in zad:
            self.assertIn("Ryzyka (3):", z["item"]["opis"])

    def test_bez_zaplanowanego_spotkania_jedno_zadanie_na_klienta(self):
        najn = najnowsze_auto_tama()
        del najn["spotkanie-z-pawlem"]
        zad = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS)
        self.assertEqual([z["klucz"] for z in zad], ["notatka-auto-tama"])
        self.assertEqual(zad[0]["tytul"], "Notatka o kliencie: ryzyka i otwarte tematy")
        self.assertIn("Ryzyka (3):", zad[0]["item"]["opis"])
        self.assertEqual(zad[0]["item"]["termin"], "brak")

    def test_spotkanie_z_przeszlosci_nie_liczy_sie(self):
        najn = najnowsze_auto_tama()
        najn["spotkanie-z-pawlem"][0]["termin"] = "2026-10-10"
        zad = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS)
        self.assertEqual([z["klucz"] for z in zad], ["notatka-auto-tama"])

    def test_bez_ryzyk_i_bez_spotkania_brak_zadania(self):
        najn = {k: v for k, v in najnowsze_auto_tama().items() if v[0]["sekcja"] != 5 and v[0]["typ"] != "spotkanie"}
        self.assertEqual(notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS), [])

    def test_spotkanie_bez_ryzyk_tez_dostaje_notatke_z_otwartymi_tematami(self):
        najn = {k: v for k, v in najnowsze_auto_tama().items() if v[0]["sekcja"] != 5}
        zad = notatki.zbierz_zadania("auto-tama", karta_auto_tama(), najn, Z, DZIS)
        self.assertEqual([z["klucz"] for z in zad], ["notatka-spotkanie-z-pawlem"])
        self.assertIn("Ryzyka (0):", zad[0]["item"]["opis"])

    def test_data_spotkania_z_tytulu_gdy_termin_brak(self):
        najn = {"ryzyko": (pozycja("ryzyko", 5, "ryzyko_handlowe", "R"), "z.md"),
                "sp": (pozycja("sp", 2, "spotkanie", "Potwierdzenie spotkania (środa 21.10, 9:00)"), "z.md")}
        karta = {"otwarte_sprawy": {"ryzyko": wpis("RIN-1", "R"), "sp": wpis("RIN-2", "Spotkanie")}}
        zad = notatki.zbierz_zadania("klinika", karta, najn, Z, DZIS)
        self.assertEqual(zad[0]["klucz"], "notatka-sp")
        self.assertEqual(zad[0]["item"]["termin"], "2026-10-21")

    def test_zamkniete_sprawy_nie_wchodza_do_notatki(self):
        karta = karta_auto_tama()
        karta["zamkniete_sprawy"] = {"adres": wpis("RIN-39", "Adres Włocławek", status_koncowy="zamknieta")}
        najn = najnowsze_auto_tama()
        najn["adres"] = (pozycja("adres", 1, "poprawka_bazy_wiedzy", "Adres Włocławek"), "z.md")
        opis = notatki.zbierz_zadania("auto-tama", karta, najn, Z, DZIS)[0]["item"]["opis"]
        self.assertNotIn("Adres Włocławek", opis)


class AtrapaLinear:
    """Podmienia linear_sync.gql: zapisuje wywołania i zwraca sztuczne odpowiedzi."""

    def __init__(self):
        self.wywolania = []

    def __call__(self, api_key, query, variables=None, **kw):
        self.wywolania.append((query, variables or {}))
        if "issueCreate" in query:
            return {"issueCreate": {"issue": {"id": "id-nowe", "identifier": "RIN-99", "url": URL.format("RIN-99")}}}
        return {}

    def mutacje(self, fragment):
        return [v for q, v in self.wywolania if fragment in q]


class TestSynchronizacjaNotatek(unittest.TestCase):

    def setUp(self):
        self.atrapa = AtrapaLinear()
        self.stary = linear_sync.gql
        linear_sync.gql = self.atrapa
        self.addCleanup(lambda: setattr(linear_sync, "gql", self.stary))
        self.etykiety = {"Dla agenta": "L-agent", "Zadanie": "L-zadanie"}
        self.stany = {"anulowana": "S-anulowana"}

    def _sync(self, karta, najn, dry_run=False, dzis=DZIS):
        return notatki.synchronizuj_notatki(
            linear_sync, "klucz", "TEAM", karta, "auto-tama", najn, Z, self.etykiety, "S-todo", self.stany,
            "ops/transkrypcje/auto-tama/2026-10-13-call.md", "2026-10-13", dzis, dry_run=dry_run)

    def test_scalenie_rin_78_79_80_w_jedno_zadanie(self):
        karta = karta_auto_tama()
        self._sync(karta, najnowsze_auto_tama())
        o = karta["otwarte_sprawy"]
        # RIN-78 przekształcony w notatkę na spotkanie, RIN-79 i RIN-80 zniknęły z otwartych
        self.assertEqual(o["notatka-spotkanie-z-pawlem"]["identifier"], "RIN-78")
        self.assertNotIn("przygotowanie-ryzyko-voicedesk", o)
        self.assertNotIn("przygotowanie-ryzyko-zla-interpretacja", o)
        self.assertNotIn("przygotowanie-ryzyko-crm", o)
        aktualizacje = self.atrapa.mutacje("issueUpdate")
        notatka = next(v for v in aktualizacje if v["id"] == "id-RIN-78")
        self.assertEqual(notatka["input"]["title"], "[auto-tama] Notatka przed spotkaniem: Spotkanie z Pawłem 15.10 10:00")
        self.assertIn("Ryzyka (3):", notatka["input"]["description"])
        self.assertEqual(notatka["input"]["dueDate"], "2026-10-15")

    def test_nadmiarowe_zarchiwizowane_z_komentarzem_gdzie_przeniesiono_tresc(self):
        karta = karta_auto_tama()
        self._sync(karta, najnowsze_auto_tama())
        komentarze = {v["issueId"]: v["body"] for v in self.atrapa.mutacje("commentCreate")}
        for nadmiarowe in ("id-RIN-79", "id-RIN-80"):
            self.assertIn("RIN-78", komentarze[nadmiarowe])
            self.assertIn("przeniesiono", komentarze[nadmiarowe])
        stany = {v["id"]: v["input"]["stateId"] for v in self.atrapa.mutacje("issueUpdate")
                 if "stateId" in v["input"]}
        self.assertEqual(stany, {"id-RIN-79": "S-anulowana", "id-RIN-80": "S-anulowana"})
        zarchiwizowane = {v["id"] for v in self.atrapa.mutacje("issueArchive")}
        self.assertEqual(zarchiwizowane, {"id-RIN-79", "id-RIN-80"})
        self.assertNotIn("id-RIN-78", zarchiwizowane)
        zam = karta["zamkniete_sprawy"]
        self.assertEqual(zam["przygotowanie-ryzyko-zla-interpretacja"]["przeniesiono_do"], "notatka-spotkanie-z-pawlem")
        self.assertEqual(zam["przygotowanie-ryzyko-crm"]["status_koncowy"], "anulowana")

    def test_ponowne_uruchomienie_niczego_nie_zmienia(self):
        karta = karta_auto_tama()
        self._sync(karta, najnowsze_auto_tama())
        self.atrapa.wywolania.clear()
        zdarzenia = self._sync(karta, najnowsze_auto_tama())
        self.assertEqual(zdarzenia, [])
        self.assertEqual(self.atrapa.wywolania, [], "ta sama notatka: bez wywołań Lineara")

    def test_nowy_temat_odswieza_opis_tej_samej_notatki(self):
        karta, najn = karta_auto_tama(), najnowsze_auto_tama()
        self._sync(karta, najn)
        self.atrapa.wywolania.clear()
        karta["otwarte_sprawy"]["nowe-ryzyko"] = wpis("RIN-100", "Nowe ryzyko cenowe")
        najn["nowe-ryzyko"] = (pozycja("nowe-ryzyko", 5, "ryzyko_handlowe", "Nowe ryzyko cenowe"), "z.md")
        self._sync(karta, najn)
        aktualizacje = self.atrapa.mutacje("issueUpdate")
        self.assertEqual(len(aktualizacje), 1)
        self.assertIn("Ryzyka (4):", aktualizacje[0]["input"]["description"])
        self.assertIn("Nowe ryzyko cenowe", aktualizacje[0]["input"]["description"])

    def test_nowy_klient_bez_dawnych_zadan_dostaje_nowe_zadanie_dla_agenta(self):
        karta = karta_auto_tama()
        for k in [k for k in karta["otwarte_sprawy"] if k.startswith("przygotowanie-")]:
            del karta["otwarte_sprawy"][k]
        self._sync(karta, najnowsze_auto_tama())
        tworzenie = self.atrapa.mutacje("issueCreate")
        self.assertEqual(len(tworzenie), 1)
        wejscie = tworzenie[0]["input"]
        self.assertEqual(wejscie["labelIds"], ["L-agent", "L-zadanie"])
        self.assertEqual(wejscie["stateId"], "S-todo")
        self.assertEqual(wejscie["dueDate"], "2026-10-15")
        self.assertEqual(karta["otwarte_sprawy"]["notatka-spotkanie-z-pawlem"]["identifier"], "RIN-99")

    def test_klient_traci_ryzyka_i_spotkanie_wszystkie_notatki_archiwizowane_bez_zastepnika(self):
        karta = karta_auto_tama()
        najn = {k: v for k, v in najnowsze_auto_tama().items() if v[0]["sekcja"] != 5 and v[0]["typ"] != "spotkanie"}
        self._sync(karta, najn)
        komentarze = [v["body"] for v in self.atrapa.mutacje("commentCreate")]
        self.assertEqual(len(komentarze), 3)
        self.assertTrue(all("nie jest już potrzebne" in k for k in komentarze))
        self.assertEqual(len(self.atrapa.mutacje("issueArchive")), 3)

    def test_podglad_nie_zmienia_karty_i_nie_wola_lineara(self):
        karta = karta_auto_tama()
        przed = copy.deepcopy(karta)
        zdarzenia = self._sync(copy.deepcopy(karta), najnowsze_auto_tama(), dry_run=True)
        self.assertEqual(self.atrapa.wywolania, [])
        self.assertEqual(karta, przed)
        self.assertTrue(any("RIN-78" in z and "notatka-spotkanie-z-pawlem" in z for z in zdarzenia))
        self.assertTrue(any("RIN-79" in z and "→ RIN-78" in z for z in zdarzenia), "podgląd wskazuje, dokąd przeniesiono")

    def test_opis_zgloszenia_ma_staly_uklad_dla_agenta(self):
        karta = karta_auto_tama()
        self._sync(karta, najnowsze_auto_tama())
        opis = next(v for v in self.atrapa.mutacje("issueUpdate") if v["id"] == "id-RIN-78")["input"]["description"]
        naglowki = [l for l in opis.splitlines() if l.startswith("## ")]
        self.assertEqual(naglowki, ["## Cel", "## Kontekst", "## Kryteria akceptacji", "## Jak sprawdzić",
                                    "## Repo", "## Czego nie ruszać", "## Źródło"])
        self.assertIn("- [ ] Każde ryzyko z listy ma w notatce streszczenie", opis)


if __name__ == "__main__":
    unittest.main(verbosity=2)
