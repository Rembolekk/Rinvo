#!/usr/bin/env python3
"""test_zasady.py – testy offline zasad AI-first (ops/zasady.json), opisu zgłoszenia dla agenta,
przeliczania istniejących zgłoszeń i codziennego podsumowania (w tym strefy czasowej i przypomnień).

Bez sieci i bez modelu. Uruchomienie:  python3 testy/test_zasady.py
"""

import contextlib
import copy
import io
import json
import re
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import linear_sync
import podsumowanie
import przelicz
import zasady

Z = zasady.wczytaj_zasady()
KRYT = ["Punkt do sprawdzenia"]


def poz(**kw):
    p = {"id": "T1", "sekcja": 1, "typ": "bug", "tytul": "Błąd listy kontaktów", "opis": "Lista nie działa.",
         "pewnosc": "wysoka", "klucz_sprawy": "lista", "konflikt_z_zakazem": None, "cytat": ["cytat"],
         "kryteria_akceptacji": KRYT}
    p.update(kw)
    return p


def karta():
    return {"klient": "k", "decydenci": [{"imie": "Kasia"}],
            "kontakty": [{"imie": "Kasia Malinowska", "email": "k@x.pl", "potwierdzony": True}],
            "decyzje_zastrzezone": [{"opis": "Opel: Kasia", "zastrzezone_dla": "Kasia Malinowska",
                                     "zakazy": ["Z4"], "klucze_spraw": ["opel"]}],
            "zakazy": [{"id": "Z4", "tytul": "Nie włączać Opla", "cytat": ["Opla nie ruszam"]}],
            "otwarte_sprawy": {}}


def komu(item, **kw):
    return zasady.przypisz(item, Z, kw.pop("karta", karta()), kw.pop("wielu", False))["komu"]


def reguly(item, **kw):
    return [p["regula"] for p in zasady.przypisz(item, Z, kw.pop("karta", karta()), kw.pop("wielu", False))["powody"]]


class TestPlikZasad(unittest.TestCase):

    def test_plik_ma_wszystkie_sekcje_i_etykiety(self):
        for klucz in ("domyslnie", "etykiety", "czlowiek_gdy", "produkt", "agent", "ryzyka", "repo",
                      "przypomnienia", "podsumowanie", "nadpisania"):
            self.assertIn(klucz, Z)
        self.assertEqual(Z["domyslnie"], "agent")
        self.assertEqual(Z["etykiety"]["agent"], "Dla agenta")
        self.assertEqual(Z["etykiety"]["czlowiek"], "Decyzja człowieka")
        for regula in ("pieniadze", "do_klienta", "zakaz", "decyzja_zastrzezona", "pewnosc_niska", "nieodwracalne"):
            self.assertIn(regula, Z["czlowiek_gdy"])

    def test_etykieta_decyzja_czlowieka_jest_wymagana_w_linearze(self):
        self.assertIn("Decyzja człowieka", linear_sync.REQUIRED_LABELS)


class TestDomyslnieAgent(unittest.TestCase):

    def test_zwykla_pozycja_idzie_do_agenta(self):
        self.assertEqual(komu(poz()), "agent")
        self.assertEqual(zasady.etykiety_pozycji(poz(), Z, karta()), ["Błąd", "Dla agenta"])

    def test_kazdy_typ_techniczny_idzie_do_agenta(self):
        for typ in ("bug", "zmiana_konfiguracji", "poprawka_bazy_wiedzy", "zobowiazanie_nasze"):
            self.assertEqual(komu(poz(typ=typ)), "agent", typ)


class TestReguly(unittest.TestCase):
    """Każda reguła z czlowiek_gdy: pozycja trafia do człowieka z powodem (etykieta Decyzja człowieka)."""

    def _czlowiek(self, item, regula, **kw):
        self.assertEqual(komu(item, **kw), "czlowiek")
        self.assertIn(regula, reguly(item, **kw))
        self.assertIn("Decyzja człowieka", zasady.etykiety_pozycji(item, Z, kw.get("karta", karta()), kw.get("wielu", False)))
        self.assertNotIn("Dla agenta", zasady.etykiety_pozycji(item, Z, kw.get("karta", karta()), kw.get("wielu", False)))

    def test_pieniadze_typ_finanse(self):
        self._czlowiek(poz(typ="finanse", tytul="Korekta kwoty"), "pieniadze")

    def test_pieniadze_slowa_sms_cena_rabat_umowa(self):
        for tytul in ("Wycena SMS-ów", "Zmiana ceny abonamentu", "Rabat dla klienta", "Aneks do umowy"):
            self._czlowiek(poz(tytul=tytul, opis=""), "pieniadze")

    def test_do_klienta_mail_przypomnienie_oferta_ze_szkicem(self):
        for tytul in ("Wysłać Kasi zestawienie", "Przypomnienie o pliku", "Oferta dla klienta",
                      "Wysłać zaproszenie dla Pawła"):
            item = poz(tytul=tytul, opis="")
            self._czlowiek(item, "do_klienta")
            self.assertTrue(zasady.przypisz(item, Z, karta())["wymaga_szkicu"], tytul)

    def test_konflikt_z_zakazem(self):
        item = poz(konflikt_z_zakazem={"zakaz": "Z4", "uzasadnienie": "włączenie Opla"})
        self._czlowiek(item, "zakaz")
        self.assertIn("Zablokowane przez zakaz", zasady.etykiety_pozycji(item, Z, karta()))

    def test_decyzja_zastrzezona_w_karcie(self):
        self._czlowiek(poz(klucz_sprawy="opel", tytul="Decyzja o Oplu"), "decyzja_zastrzezona")

    def test_pewnosc_niska(self):
        item = poz(pewnosc="niska")
        self._czlowiek(item, "pewnosc_niska")
        self.assertIn("Do weryfikacji", zasady.etykiety_pozycji(item, Z, karta()))

    def test_nieodwracalne_wylaczenie_usuniecie_zmiana_umowy(self):
        for tytul, opis in (("Wyłączyć agenta u klienta", ""), ("Usunąć dane pacjentów", ""),
                            ("Porządki", "To skasowanie bazy"), ("Zmiana umowy", "")):
            self._czlowiek(poz(tytul=tytul, opis=opis), "nieodwracalne")

    def test_powod_jest_czytelny_i_z_pliku_zasad(self):
        p = zasady.przypisz(poz(typ="finanse"), Z, karta())
        self.assertIn(Z["czlowiek_gdy"]["pieniadze"]["powod"], zasady.powody_tekst(p)[0])

    def test_zmiana_zasad_w_pliku_zmienia_decyzje_bez_zmiany_kodu(self):
        z2 = copy.deepcopy(Z)
        item = poz(tytul="Wycena SMS-ów", opis="")
        self.assertEqual(zasady.przypisz(item, Z, karta())["komu"], "czlowiek")
        z2["czlowiek_gdy"]["pieniadze"]["slowa"] = [s for s in z2["czlowiek_gdy"]["pieniadze"]["slowa"]
                                                     if s not in ("sms", "wycen")]
        self.assertEqual(zasady.przypisz(item, z2, karta())["komu"], "agent")

    def test_nadpisanie_recznym_wyjatkiem(self):
        z2 = copy.deepcopy(Z)
        z2["nadpisania"]["lista"] = "czlowiek"
        self.assertEqual(zasady.przypisz(poz(), z2, karta())["komu"], "czlowiek")
        z3 = copy.deepcopy(Z)
        z3["nadpisania"]["lista"] = "agent"
        self.assertEqual(zasady.przypisz(poz(typ="finanse"), z3, karta())["komu"], "agent")


class TestBrakKryteriow(unittest.TestCase):

    def test_bez_kryteriow_do_weryfikacji_a_nie_do_agenta(self):
        for brak in ({"kryteria_akceptacji": []}, {"kryteria_akceptacji": ["  "]}, {"kryteria_akceptacji": None}):
            item = poz(**brak)
            p = zasady.przypisz(item, Z, karta())
            self.assertEqual(p["komu"], "weryfikacja")
            self.assertEqual(zasady.powody_tekst(p), ["brak kryteriów"])
            et = zasady.etykiety_pozycji(item, Z, karta())
            self.assertIn("Do weryfikacji", et)
            self.assertNotIn("Dla agenta", et)
            self.assertNotIn("Decyzja człowieka", et)

    def test_brak_pola_kryteriow_tez(self):
        item = poz()
        del item["kryteria_akceptacji"]
        self.assertEqual(komu(item), "weryfikacja")

    def test_pozycja_dla_czlowieka_nie_wymaga_kryteriow(self):
        self.assertEqual(komu(poz(typ="finanse", kryteria_akceptacji=[])), "czlowiek")


class TestProsbyProduktowe(unittest.TestCase):

    def _prosba(self, **kw):
        return poz(sekcja=3, typ="pomysl_produktowy", rodzaj="nowa_funkcja", klucz_funkcji="eksport", **kw)

    def test_pojedyncza_duza_funkcja_to_priorytet_produktowy(self):
        item = self._prosba()
        p = zasady.przypisz(item, Z, karta())
        self.assertEqual(p["komu"], "czlowiek")
        self.assertIn("priorytet produktowy", zasady.powody_tekst(p))
        self.assertEqual(zasady.etykiety_pozycji(item, Z, karta()), ["Produkt", "Decyzja człowieka"])

    def test_wielu_klientow_idzie_do_agenta(self):
        item = self._prosba()
        self.assertEqual(zasady.etykiety_pozycji(item, Z, karta(), wielu=True),
                         ["Produkt", "Dla agenta", "Wielu klientów"])

    def test_wielu_klientow_liczone_z_prosby_json(self):
        prosby = {"eksport": {"prosby": [{"klient": "a"}, {"klient": "b"}]}}
        self.assertTrue(zasady.wielu_klientow(prosby, Z, self._prosba(), "a"))
        self.assertFalse(zasady.wielu_klientow({"eksport": {"prosby": [{"klient": "a"}]}}, Z, self._prosba(), "a"))
        self.assertTrue(zasady.wielu_klientow({"eksport": {"prosby": [{"klient": "a"}]}}, Z, self._prosba(), "b"))

    def test_drobna_zmiana_z_wysoka_pewnoscia_idzie_do_agenta(self):
        item = poz(sekcja=3, typ="pomysl_produktowy", rodzaj="zmiana", klucz_funkcji="mail")
        self.assertEqual(komu(item), "agent")

    def test_drobna_zmiana_z_niska_pewnoscia_do_czlowieka(self):
        item = poz(sekcja=3, typ="pomysl_produktowy", rodzaj="zmiana", pewnosc="niska")
        self.assertEqual(komu(item), "czlowiek")


class TestRyzykaICzeka(unittest.TestCase):

    def test_ryzyko_zostaje_dla_ludzi_z_etykieta_ryzyko(self):
        item = poz(sekcja=5, typ="ryzyko_handlowe", tytul="VoiceDesk złożył ofertę z cennikiem")
        self.assertEqual(komu(item), "ryzyko")
        self.assertEqual(zasady.etykiety_pozycji(item, Z, karta()), ["Ryzyko"])

    def test_notatka_przed_spotkaniem_idzie_do_agenta_mimo_slow_o_cenach_w_ryzyku(self):
        """ZMIENIONE ŚWIADOMIE: zamiast osobnego zadania na każde ryzyko jest jedna notatka na spotkanie
        (szczegóły w test_notatki.py); tu sprawdzamy tylko routing: notatka zawsze idzie do agenta."""
        import notatki
        najn = {"r": (poz(sekcja=5, typ="ryzyko_handlowe", klucz_sprawy="r", tytul="VoiceDesk złożył ofertę z cennikiem"), "z.md"),
                "sp": (poz(sekcja=1, typ="spotkanie", klucz_sprawy="sp", tytul="Spotkanie", termin="2026-10-20"), "z.md")}
        k = {"otwarte_sprawy": {"r": {"identifier": "RIN-1", "url": "u"}, "sp": {"identifier": "RIN-2", "url": "u"}}}
        item = notatki.zbierz_zadania("k", k, najn, Z, date(2026, 10, 14))[0]["item"]
        self.assertIn("cennikiem", item["opis"])
        self.assertTrue(zasady.kryteria_ok(item))
        self.assertEqual(zasady.przypisz(item, Z, karta())["komu"], "agent")

    def test_sekcja_2_czeka_na_klienta_bez_przypisania(self):
        item = poz(sekcja=2, typ="czeka_na_klienta")
        self.assertEqual(komu(item), "czeka")
        self.assertEqual(zasady.etykiety_pozycji(item, Z, karta()), ["Czeka na klienta"])

    def test_ocena_po_wznowieniu(self):
        item = poz(sekcja=2, typ="finanse")
        self.assertEqual(zasady.przypisz(item, Z, karta(), sekcja=1)["komu"], "czlowiek")


class TestOpisZgloszenia(unittest.TestCase):

    def _opis(self, item, przyp=None):
        return linear_sync.build_description(item, "ops/zrodlo.md", karta(), przyp, Z)

    def test_staly_uklad_sekcji_w_kolejnosci(self):
        item = poz(cel="Naprawić listę", jak_sprawdzic="Otworzyć listę i filtrować", repo="rinvo",
                   kryteria_akceptacji=["Filtr zawęża listę", "Filtr dat działa"])
        opis = self._opis(item, zasady.przypisz(item, Z, karta()))
        naglowki = [l for l in opis.splitlines() if l.startswith("## ")]
        self.assertEqual(naglowki, ["## Cel", "## Kontekst", "## Kryteria akceptacji", "## Jak sprawdzić",
                                    "## Repo", "## Czego nie ruszać", "## Źródło"])
        self.assertIn("- [ ] Filtr zawęża listę", opis)
        self.assertIn("- [ ] Filtr dat działa", opis)
        self.assertIn("> cytat", opis, "kontekst z cytatami")
        self.assertIn("`rinvo`", opis)

    def test_czego_nie_ruszac_zawiera_zakazy_i_decyzje_zastrzezone(self):
        opis = self._opis(poz())
        self.assertIn("Zakaz Z4: Nie włączać Opla", opis)
        self.assertIn("Decyzja zastrzeżona dla Kasia Malinowska", opis)

    def test_zgloszenie_dla_czlowieka_ma_powody_i_szkic(self):
        item = poz(tytul="Wysłać Kasi zestawienie", szkic_klienta="Cześć Kasiu,\n\nzestawienie w załączniku.")
        przyp = zasady.przypisz(item, Z, karta())
        opis = self._opis(item, przyp)
        self.assertIn("## Dlaczego człowiek", opis)
        self.assertIn("## Szkic dla klienta (do wysłania przez człowieka)", opis)
        self.assertIn("> zestawienie w załączniku.", opis)

    def test_zgloszenie_bez_kryteriow_ma_sekcje_do_weryfikacji(self):
        item = poz(kryteria_akceptacji=[])
        opis = self._opis(item, zasady.przypisz(item, Z, karta()))
        self.assertIn("## Do weryfikacji", opis)
        self.assertIn("- brak kryteriów", opis)
        self.assertIn("_brak: uzupełnij", opis)

    def test_komentarz_z_powodem(self):
        k = linear_sync.komentarz_przypisania("czlowiek", ["kosztuje pieniądze"], True)
        self.assertIn("**Decyzja człowieka**", k)
        self.assertIn("kosztuje pieniądze", k)
        self.assertIn("gotowy szkic", k)
        self.assertIn("brak kryteriów", linear_sync.komentarz_przypisania("weryfikacja", ["brak kryteriów"]))
        self.assertIsNone(linear_sync.komentarz_przypisania("agent", []))


class TestPrzypomnieniaStan(unittest.TestCase):

    def _st(self, przyp, k=None):
        return linear_sync.przypomnienie_z_pozycji(poz(klucz_sprawy="plik", przypomnienie=przyp), Z, k)

    def test_limit_z_rozmowy(self):
        self.assertEqual(self._st({"limit": "1 raz"})["limit"], 1)
        self.assertEqual(self._st({"limit": "2 maile"})["limit"], 2)

    def test_brak_limitu_to_limit_domyslny(self):
        self.assertEqual(self._st({"limit": "brak"})["limit"], Z["przypomnienia"]["domyslny_limit"])
        self.assertEqual(self._st({"limit": "2026-10-15"})["limit"], Z["przypomnienia"]["domyslny_limit"],
                         "data w polu limit nie jest limitem")

    def test_nie_przypominaj_z_limitu_zero(self):
        st = self._st({"limit": "0", "uwagi": "klient prosi, żeby nie przypominać"})
        self.assertTrue(st["nie_przypominac"])
        self.assertEqual(st["limit"], 0)

    def test_nie_przypominaj_z_zakazu_w_karcie(self):
        k = karta()
        k["zakazy"].append({"id": "Z9", "klucz_sprawy": "plik", "tytul": "Nie przypominać Kasi o pliku", "cytat": []})
        self.assertTrue(self._st({"limit": "1 raz"}, k)["nie_przypominac"])

    def test_licznik_wykorzystanych_nie_wraca_do_zera(self):
        entry = {"przypomnienie": {"limit": 1, "wykorzystane": 1, "nie_przypominac": False, "ostatni_szkic": "2026-10-16"}}
        linear_sync.zapisz_przypisanie(entry, poz(sekcja=2, klucz_sprawy="plik", przypomnienie={"limit": "1 raz"}),
                                       Z, karta(), False)
        self.assertEqual(entry["przypomnienie"]["wykorzystane"], 1)


def zgl(ident, tytul, etykiety, termin=None, klient="k"):
    return {"id": f"id-{ident}", "identifier": ident, "url": f"https://linear.app/ws/issue/{ident}", "title": f"[{klient}] {tytul}",
            "createdAt": "2026-10-14T05:00:00Z", "dueDate": termin, "state": {"name": "Todo", "type": "unstarted"},
            "labels": {"nodes": [{"name": n} for n in etykiety]}}


def karta_z_czekajacym(przyp):
    k = karta()
    k["otwarte_sprawy"] = {"plik": {"linear_id": "id-RIN-1", "identifier": "RIN-1", "przypomnienie": przyp}}
    return k


DZIS = date(2026, 10, 16)


class TestPodsumowanieZasadyPrzypomnien(unittest.TestCase):

    def _zbierz(self, zgloszenie, przyp):
        karty = {"k": karta_z_czekajacym(przyp)}
        return podsumowanie.zbierz([zgloszenie], [], karty, Z, DZIS)["k"], karty

    def test_po_terminie_limit_niewyczerpany_daje_szkic(self):
        d, _ = self._zbierz(zgl("RIN-1", "Plik leadów", ["Czeka na klienta"], "2026-10-15"),
                            {"limit": 1, "wykorzystane": 0, "nie_przypominac": False})
        self.assertEqual(len(d["szkice"]), 1)
        self.assertEqual(len(d["po_terminie"]), 1)
        tekst = d["szkice"][0]["tekst"]
        self.assertIn("Plik leadów", tekst)
        self.assertIn("15.10.2026", tekst)
        self.assertTrue(tekst.startswith("Cześć Kasia,"))

    def test_limit_wyczerpany_brak_szkicu(self):
        d, _ = self._zbierz(zgl("RIN-1", "Plik", ["Czeka na klienta"], "2026-10-15"),
                            {"limit": 1, "wykorzystane": 1, "nie_przypominac": False})
        self.assertEqual(d["szkice"], [])

    def test_klient_prosil_o_brak_przypomnien_brak_szkicu(self):
        d, _ = self._zbierz(zgl("RIN-1", "Plik", ["Czeka na klienta"], "2026-10-15"),
                            {"limit": 0, "wykorzystane": 0, "nie_przypominac": True})
        self.assertEqual(d["szkice"], [])
        self.assertEqual(len(d["po_terminie"]), 1, "dalej widoczna jako po terminie")

    def test_termin_jeszcze_nie_minal_brak_szkicu(self):
        d, _ = self._zbierz(zgl("RIN-1", "Plik", ["Czeka na klienta"], "2026-10-16"),
                            {"limit": 1, "wykorzystane": 0, "nie_przypominac": False})
        self.assertEqual(d["szkice"], [])
        self.assertEqual(len(d["czeka"]), 1)
        self.assertEqual(d["po_terminie"], [])

    def test_bez_terminu_brak_szkicu(self):
        d, _ = self._zbierz(zgl("RIN-1", "Plik", ["Czeka na klienta"], None),
                            {"limit": 1, "wykorzystane": 0, "nie_przypominac": False})
        self.assertEqual(d["szkice"], [])

    def test_szkic_liczy_sie_jako_wykorzystane_przypomnienie_i_limit_nie_zostanie_przekroczony(self):
        zg = zgl("RIN-1", "Plik leadów", ["Czeka na klienta"], "2026-10-15")
        d, karty = self._zbierz(zg, {"limit": 1, "wykorzystane": 0, "nie_przypominac": False})
        wywolania = []
        stary = linear_sync.gql
        linear_sync.gql = lambda api_key, q, v=None, **kw: wywolania.append(v) or {}
        try:
            zmienione = podsumowanie.zapisz_szkice("klucz", {"k": d}, karty, "2026-10-16")
        finally:
            linear_sync.gql = stary
        self.assertEqual(zmienione, {"k"})
        self.assertEqual(karty["k"]["otwarte_sprawy"]["plik"]["przypomnienie"]["wykorzystane"], 1)
        self.assertIn("Szkic przypomnienia", wywolania[0]["body"])
        self.assertIn("niczego nie wysłano", wywolania[0]["body"])
        # kolejne podsumowanie: limit wyczerpany, drugi szkic już nie powstaje
        d2 = podsumowanie.zbierz([zg], [], karty, Z, date(2026, 10, 17))["k"]
        self.assertEqual(d2["szkice"], [])

    def test_stary_wpis_bez_przypomnienia_ma_limit_domyslny_i_zakazy_z_karty(self):
        k = karta()
        k["otwarte_sprawy"] = {"plik": {"linear_id": "x", "identifier": "RIN-1"}}
        k["zakazy"].append({"id": "Z9", "klucz_sprawy": "plik", "tytul": "Nie przypominać o pliku", "cytat": []})
        d = podsumowanie.zbierz([zgl("RIN-1", "Plik", ["Czeka na klienta"], "2026-10-10")], [], {"k": k}, Z, DZIS)["k"]
        self.assertEqual(d["szkice"], [], "zakaz z karty działa także dla starszych wpisów")
        k["zakazy"] = [z for z in k["zakazy"] if z["id"] != "Z9"]
        d = podsumowanie.zbierz([zgl("RIN-1", "Plik", ["Czeka na klienta"], "2026-10-10")], [], {"k": k}, Z, DZIS)["k"]
        self.assertEqual(len(d["szkice"]), 1)

    def test_podsumowanie_nigdy_nie_wysyla_do_klienta(self):
        kod = Path(podsumowanie.__file__).read_text(encoding="utf-8")
        for zakazane in ("smtplib", "imaplib", "sendmail", "send_message"):
            self.assertNotIn(zakazane, kod)


class TestStrefaCzasowa(unittest.TestCase):
    """Cron GitHuba jest w UTC: czas polski liczy skrypt (lato UTC+2, zima UTC+1)."""

    def _utc(self, r, m, d, h, mi=0):
        return datetime(r, m, d, h, mi, tzinfo=timezone.utc)

    def test_lato_06_utc_to_08_w_polsce(self):
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 7, 1, 6)).hour, 8)

    def test_zima_07_utc_to_08_w_polsce(self):
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 1, 15, 7)).hour, 8)

    def test_zmiana_czasu_jesienia_2026(self):
        # czas letni kończy się w niedzielę 25.10.2026 o 01:00 UTC
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 10, 24, 6)).hour, 8)
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 10, 25, 6)).hour, 7)
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 10, 25, 7)).hour, 8)

    def test_zmiana_czasu_wiosna_2026(self):
        # czas letni zaczyna się w niedzielę 29.03.2026 o 01:00 UTC
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 3, 28, 7)).hour, 8)
        self.assertEqual(podsumowanie.czas_polski(self._utc(2026, 3, 29, 6)).hour, 8)

    def test_reguła_ue_bez_bazy_stref_daje_to_samo(self):
        import zoneinfo
        orig = zoneinfo.ZoneInfo
        zoneinfo.ZoneInfo = lambda *_: (_ for _ in ()).throw(zoneinfo.ZoneInfoNotFoundError("brak"))
        try:
            for t, h in ((self._utc(2026, 7, 1, 6), 8), (self._utc(2026, 1, 15, 7), 8),
                         (self._utc(2026, 10, 25, 6), 7), (self._utc(2026, 3, 29, 6), 8)):
                self.assertEqual(podsumowanie.czas_polski(t).hour, h, t)
        finally:
            zoneinfo.ZoneInfo = orig

    def test_cron_dwa_razy_wysyla_raz_dziennie_o_8_czasu_polskiego(self):
        # lato: cron 06:00 UTC wysyła, cron 07:00 UTC (09:00 w Polsce) już nie, bo dziś wysłano
        stan = {}
        t1 = self._utc(2026, 7, 1, 6)
        self.assertTrue(podsumowanie.czy_pora(t1, stan, Z))
        stan["ostatnie_wyslane"] = podsumowanie.czas_polski(t1).date().isoformat()
        self.assertFalse(podsumowanie.czy_pora(self._utc(2026, 7, 1, 7), stan, Z))
        # zima: cron 06:00 UTC = 07:00 w Polsce jest za wcześnie, 07:00 UTC wysyła
        self.assertFalse(podsumowanie.czy_pora(self._utc(2026, 1, 15, 6), {}, Z))
        self.assertTrue(podsumowanie.czy_pora(self._utc(2026, 1, 15, 7), {}, Z))

    def test_okno_znosi_opoznienie_crona_ale_nie_wysyla_po_poludniu(self):
        self.assertTrue(podsumowanie.czy_pora(self._utc(2026, 7, 1, 8), {}, Z), "opóźnienie do 10:00 w Polsce")
        self.assertFalse(podsumowanie.czy_pora(self._utc(2026, 7, 1, 11), {}, Z), "13:00 w Polsce")
        self.assertFalse(podsumowanie.czy_pora(self._utc(2026, 7, 1, 3), {}, Z), "05:00 w Polsce")

    def test_wymus_ignoruje_godzine_i_stan(self):
        self.assertTrue(podsumowanie.czy_pora(self._utc(2026, 7, 1, 20), {"ostatnie_wyslane": "2026-07-01"}, Z, True))

    def test_workflow_ma_dwa_crony_utc_i_wspolna_grupe_concurrency(self):
        tekst = (Path(__file__).parent.parent / ".github/workflows/podsumowanie.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 6 * * *"', tekst)
        self.assertIn('cron: "0 7 * * *"', tekst)
        self.assertIn("group: przetworz-rozmowy", tekst)
        self.assertIn("workflow_dispatch", tekst)
        self.assertIn("--wymus", tekst)
        self.assertEqual(Z["podsumowanie"]["strefa"], "Europe/Warsaw")


def tekst_widoczny(tekst):
    """Tekst bez adresów w linkach <url|tekst>: to, co człowiek widzi w Slacku."""
    return re.sub(r"<[^|>]+\|([^>]*)>", r"\1", tekst)


class TestWiadomoscPodsumowania(unittest.TestCase):
    """Wiadomość do przeczytania w 10 sekund: zdanie na górze, „Wymaga człowieka” (max 5), „Uwaga” tylko gdy są,
    linijka o agentach, o czekaniu i link do Lineara. ZMIENIONE ŚWIADOMIE (podsumowanie bez powtórek): każde
    zgłoszenie występuje raz, w najważniejszej kategorii (ryzyka, po terminie, decyzje, weryfikacja, czeka,
    agenci, nowe), więc np. sprawa po terminie ze szkicem przypomnienia jest w „Uwadze”, a nie w „Wymaga człowieka”."""

    def _dane(self, dodatkowe=None, ryzyka=True):
        karty = {"k": karta_z_czekajacym({"limit": 1, "wykorzystane": 0, "nie_przypominac": False}),
                 "pusty": karta()}
        karty["k"]["otwarte_sprawy"]["sms"] = {"identifier": "RIN-8", "linear_id": "x",
                                               "przypisanie": {"komu": "czlowiek", "reguly": ["pieniadze"]}}
        otwarte = [
            zgl("RIN-1", "Plik leadów", ["Czeka na klienta"], "2026-10-15"),     # po terminie, ze szkicem
            zgl("RIN-2", "Decyzja o integracji <!channel>", ["Decyzja człowieka"]),
            zgl("RIN-3", "Naprawa", ["Dla agenta"]),
            zgl("RIN-4", "Druga naprawa", ["Dla agenta"]),
            zgl("RIN-5", "Czeka z terminem", ["Czeka na klienta"], "2026-10-20"),
            zgl("RIN-7", "Brak kryteriów", ["Do weryfikacji"]),
            zgl("RIN-8", "Wycena SMS-ów", ["Decyzja człowieka"]),
        ]
        if ryzyka:
            otwarte.append(zgl("RIN-6", "VoiceDesk", ["Ryzyko", "Powtarzające się ryzyko"]))
        otwarte += dodatkowe or []
        skonczone = [zgl("RIN-30", "Zrobione przez agenta", ["Dla agenta"])]
        return podsumowanie.przygotuj(otwarte, skonczone, karty, Z, DZIS), karty

    def _msg(self, **kw):
        dane, _ = self._dane(**kw)
        return podsumowanie.buduj_wiadomosc(dane, DZIS)

    def _msg_z(self, otwarte, skonczone=(), karty=None):
        karty = karty or {"k": karta()}
        return podsumowanie.buduj_wiadomosc(podsumowanie.przygotuj(otwarte, list(skonczone), karty, Z, DZIS), DZIS)

    def test_pierwsza_linijka_liczy_sprawy_wymagajace_czlowieka(self):
        tekst, _ = self._msg()
        # decyzje (RIN-2, RIN-8) + weryfikacja (RIN-7); RIN-1 jest po terminie, więc w „Uwadze”
        self.assertEqual(tekst.splitlines()[0], "*Dziś potrzebujemy Cię w 3 sprawach*")

    def test_forma_dla_jednej_sprawy_i_dla_zera(self):
        tekst, _ = self._msg_z([zgl("RIN-2", "Jedna", ["Decyzja człowieka"])])
        self.assertEqual(tekst.splitlines()[0], "*Dziś potrzebujemy Cię w 1 sprawie*")
        tekst, _ = self._msg_z([zgl("RIN-3", "Agent", ["Dla agenta"])])
        self.assertEqual(tekst.splitlines()[0], "*Dziś nic nie wymaga człowieka.*")
        self.assertNotIn("Wymaga człowieka", tekst)

    def test_wymaga_czlowieka_jedna_linijka_na_pozycje_z_linkiem_klientem_i_slowem_powodu(self):
        tekst, _ = self._msg()
        sekcja = tekst.split("*Wymaga człowieka*\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(len(sekcja), 3)
        self.assertTrue(all(l.startswith("• <https://linear.app/ws/issue/") for l in sekcja), sekcja)
        self.assertTrue(next(l for l in sekcja if "Wycena SMS-ów" in l).endswith("· k · pieniądze"))
        self.assertTrue(next(l for l in sekcja if "Brak kryteriów" in l).endswith("· k · weryfikacja"))
        self.assertTrue(next(l for l in sekcja if "Decyzja o integracji" in l).endswith("· k · decyzja"))
        self.assertFalse(any("Plik leadów" in l for l in sekcja), "sprawa po terminie jest tylko w „Uwadze”")
        slowa = {l.rsplit(" · ", 1)[1] for l in sekcja}
        self.assertTrue(slowa <= {"pieniądze", "klient", "zakaz", "decyzja", "weryfikacja"}, slowa)

    def test_maksymalnie_5_pozycji_reszta_w_jednej_linijce(self):
        wiele = [zgl(f"RIN-{100 + i}", f"Decyzja numer {i}", ["Decyzja człowieka"]) for i in range(8)]
        tekst, _ = self._msg(dodatkowe=wiele)
        sekcja = tekst.split("*Wymaga człowieka*\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(len([l for l in sekcja if l.startswith("• ")]), 5)
        self.assertRegex(sekcja[-1], r"^… i \d+ więcej")

    def test_tytul_do_60_znakow_bez_prefiksu_klienta(self):
        tekst, _ = self._msg(dodatkowe=[zgl("RIN-90", "A" * 100, ["Decyzja człowieka"])])
        linia = next(l for l in tekst.splitlines() if "RIN-90" in l)
        tytul = tekst_widoczny(linia).removeprefix("• ").split(" · ")[0]
        self.assertLessEqual(len(tytul), 60)
        self.assertTrue(tytul.endswith("…"))
        self.assertNotIn("[k]", tekst)

    def test_uwaga_ryzyka_i_po_terminie_a_sekcja_znika_gdy_ich_nie_ma(self):
        tekst, _ = self._msg(dodatkowe=[zgl("RIN-91", "Zaległa sprawa", ["Czeka na klienta"], "2026-10-10")])
        uwaga = tekst.split("*Uwaga*\n")[1].split("\n\n")[0]
        self.assertIn("VoiceDesk", uwaga)
        self.assertTrue(next(l for l in uwaga.splitlines() if "VoiceDesk" in l).endswith("· k · ryzyko"))
        linia = next(l for l in uwaga.splitlines() if "Zaległa sprawa" in l)
        self.assertIn("termin 10.10", linia)
        self.assertTrue(linia.endswith("po terminie"), linia)
        self.assertLess(uwaga.index("VoiceDesk"), uwaga.index("Zaległa sprawa"), "ryzyka przed sprawami po terminie")
        tekst2, _ = self._msg_z([zgl("RIN-2", "Decyzja", ["Decyzja człowieka"]), zgl("RIN-3", "Naprawa", ["Dla agenta"])])
        self.assertNotIn("*Uwaga*", tekst2)

    def test_sprawa_po_terminie_ze_szkicem_jest_w_uwadze_z_dopiskiem_a_szkic_osobno(self):
        tekst, _ = self._msg()
        uwaga = tekst.split("*Uwaga*\n")[1].split("\n\n")[0]
        linia = next(l for l in uwaga.splitlines() if "Plik leadów" in l)
        self.assertIn("po terminie", linia)
        self.assertIn("szkic przypomnienia poniżej", linia)
        self.assertIn("*Szkic przypomnienia*", tekst)
        self.assertIn("> Cześć Kasia,", tekst)

    def test_kazde_zgloszenie_tylko_raz_w_calej_wiadomosci(self):
        dodatkowe = [
            zgl("RIN-40", "Wszystkie etykiety naraz", ["Powtarzające się ryzyko", "Decyzja człowieka", "Do weryfikacji",
                                                       "Czeka na klienta", "Dla agenta"], "2026-10-01"),
            zgl("RIN-41", "Decyzja i agent", ["Decyzja człowieka", "Dla agenta", "Czeka na klienta"]),
            zgl("RIN-42", "Weryfikacja i czeka", ["Do weryfikacji", "Czeka na klienta"]),
            zgl("RIN-43", "Agent po terminie", ["Dla agenta"], "2026-10-12"),
        ]
        tekst, _ = self._msg(dodatkowe=dodatkowe)
        for n in (1, 2, 3, 4, 5, 6, 7, 8, 40, 41, 42, 43):
            self.assertLessEqual(tekst.count(f"/issue/RIN-{n}|"), 1, f"RIN-{n} występuje więcej niż raz")

    def test_kategoria_wedlug_kolejnosci_waznosci(self):
        E = lambda *n: zgl("RIN-1", "t", list(n), "2026-10-01" if "po" in n else None)
        kat = lambda z, **kw: podsumowanie.kategoria(z, DZIS, Z, kw.get("nowe", ()))
        self.assertEqual(kat(zgl("RIN-1", "t", ["Powtarzające się ryzyko", "Decyzja człowieka"], "2026-10-01")), "ryzyko")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Decyzja człowieka"], "2026-10-01")), "po_terminie")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Dla agenta", "Czeka na klienta"], "2026-10-01")), "po_terminie")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Decyzja człowieka", "Do weryfikacji", "Dla agenta"])), "czlowiek")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Do weryfikacji", "Czeka na klienta", "Dla agenta"])), "weryfikacja")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Czeka na klienta", "Dla agenta"])), "czeka")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Dla agenta"]), nowe={"RIN-1"}), "agent")
        self.assertEqual(kat(zgl("RIN-1", "t", ["Zadanie"]), nowe={"RIN-1"}), "nowe")
        self.assertIsNone(kat(zgl("RIN-1", "t", ["Zadanie"])))
        self.assertEqual(podsumowanie.KATEGORIE, ["ryzyko", "po_terminie", "czlowiek", "weryfikacja", "czeka", "agent", "nowe"])

    def test_liczniki_agentow_i_czekania_nie_zawieraja_spraw_z_wazniejszej_kategorii(self):
        tekst, _ = self._msg_z([
            zgl("RIN-1", "Agent", ["Dla agenta"]),
            zgl("RIN-2", "Agent po terminie", ["Dla agenta"], "2026-10-12"),          # → Uwaga, nie agenci
            zgl("RIN-3", "Agent i decyzja", ["Dla agenta", "Decyzja człowieka"]),       # → człowiek, nie agenci
            zgl("RIN-4", "Czeka", ["Czeka na klienta"], "2026-10-20"),
            zgl("RIN-5", "Czeka po terminie", ["Czeka na klienta"], "2026-10-12"),     # → Uwaga, nie czeka
        ], skonczone=[zgl("RIN-30", "Zrobione", ["Dla agenta"])])
        self.assertIn("Agenci pracują nad 1 zadaniem, 1 skończone od wczoraj.", tekst)
        self.assertIn("Czekamy na klientów w 1 sprawie, najbliższy termin: 20.10", tekst)
        self.assertIn("Agent po terminie", tekst.split("*Uwaga*")[1])
        self.assertIn("Agent i decyzja", tekst.split("*Wymaga człowieka*")[1].split("*Uwaga*")[0])

    def test_linijka_o_agentach(self):
        tekst, _ = self._msg()
        self.assertIn("Agenci pracują nad 2 zadaniami, 1 skończone od wczoraj.", tekst)

    def test_linijka_o_czekaniu_z_najblizszym_terminem(self):
        tekst, _ = self._msg()
        linia = next(l for l in tekst.splitlines() if l.startswith("Czekamy na klientów"))
        self.assertIn("w 1 sprawie", linia, "RIN-1 jest po terminie, więc nie liczy się jako „czekamy”")
        self.assertIn("najbliższy termin: 20.10, <https://linear.app/ws/issue/RIN-5|Czeka z terminem>", linia)

    def test_link_na_dole_prowadzi_do_stron_a_nie_do_lineara(self):
        """ZMIANA ŚWIADOMA (widoki dla ludzi): dawniej link na dole wskazywał widok zgłoszeń w Linearze, teraz index.html na Pages."""
        tekst, bloki = self._msg()
        url = "https://rembolekk.github.io/Rinvo/index.html"
        self.assertIn(f"<{url}|Wszystko o klientach i prośbach: strony>", tekst)
        self.assertNotIn("Wszystkie otwarte zgłoszenia w Linearze", tekst)
        sekcje = [b["text"]["text"] for b in bloki if b["type"] == "section"]
        self.assertTrue(sekcje[-1].startswith(f"<{url}|"))

    def test_bez_adresu_stron_wraca_link_do_lineara(self):
        import copy
        Z2 = copy.deepcopy(Z)
        Z2.pop("strony")
        otwarte = [{"id": "i1", "identifier": "RIN-1", "title": "[k] Sprawa", "url": "https://linear.app/ws/issue/RIN-1/x", "state": {"name": "Todo", "type": "unstarted"},
                    "labels": {"nodes": []}, "dueDate": None, "createdAt": "2026-10-01T00:00:00Z"}]
        dane = podsumowanie.przygotuj(otwarte, [], {"k": karta()}, Z2, DZIS)
        tekst, _ = podsumowanie.buduj_wiadomosc(dane, DZIS)
        self.assertIn("Wszystkie otwarte zgłoszenia w Linearze", tekst)

    def test_bez_list_nowe_od_wczoraj_i_bez_technicznych_nazw_w_tekscie(self):
        tekst, _ = self._msg()
        self.assertNotIn("Nowe od wczoraj", tekst)
        widoczny = tekst_widoczny(tekst)
        self.assertNotRegex(widoczny, r"RIN-\d+", "identyfikatory tylko w linkach")
        self.assertNotIn("przygotowanie-", widoczny)

    def test_znaczniki_slacka_z_tytulow_sa_oczyszczone(self):
        tekst, _ = self._msg()
        self.assertNotIn("<!channel>", tekst)
        self.assertIn("&lt;!channel&gt;", tekst)

    def test_struktura_block_kit_sekcje_mrkdwn_i_kontekst_z_data(self):
        tekst, bloki = self._msg()
        self.assertTrue(all(b["type"] in ("section", "context") for b in bloki))
        self.assertEqual(bloki[0]["text"], {"type": "mrkdwn", "text": "*Dziś potrzebujemy Cię w 3 sprawach*"})
        self.assertEqual(bloki[-1]["type"], "context")
        self.assertIn("piątek 16.10.2026", bloki[-1]["elements"][0]["text"])
        json.dumps(bloki)


class TestSlackWidok(unittest.TestCase):

    def test_odmiana_liczebnikow(self):
        import slack_widok as sw
        self.assertEqual([sw.forma(n, "a", "b", "c") for n in (1, 2, 4, 5, 12, 14, 22, 25)],
                         ["a", "b", "b", "c", "c", "c", "b", "c"])

    def test_krotki_tytul_prefiks_i_limit(self):
        import slack_widok as sw
        self.assertEqual(sw.krotki_tytul("[auto-tama] Krótki"), "Krótki")
        self.assertLessEqual(len(sw.krotki_tytul("x" * 80)), 60)
        self.assertEqual(sw.krotki_tytul("x" * 60), "x" * 60)

    def test_slowo_powodu_z_regul_z_tekstow_i_z_etykiet(self):
        import slack_widok as sw
        self.assertEqual(sw.slowo_powodu({"reguly": ["zakaz", "pieniadze"]}, [], Z), "zakaz")
        self.assertEqual(sw.slowo_powodu({"powody": [Z["czlowiek_gdy"]["pieniadze"]["powod"] + " (typ: finanse)"]}, [], Z),
                         "pieniądze")
        self.assertEqual(sw.slowo_powodu({"powody": ["priorytet produktowy"]}, [], Z), "decyzja")
        self.assertEqual(sw.slowo_powodu({"powody": ["brak kryteriów"]}, [], Z), "weryfikacja")
        self.assertEqual(sw.slowo_powodu(None, ["Do weryfikacji"], Z), "weryfikacja")

    def test_widok_linear_url_z_linku_do_zgloszenia(self):
        import slack_widok as sw
        self.assertEqual(sw.widok_linear_url(["https://linear.app/ws/issue/RIN-1/tytul"]),
                         "https://linear.app/ws/team/RIN/active")
        self.assertIsNone(sw.widok_linear_url([None, "https://inny.pl/x"]))

    def test_send_slack_wysyla_bloki_i_tekst_zapasowy(self):
        import os, przetworz, urllib.request
        wyslane = {}

        class Odp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def falszywy_urlopen(req, timeout=0, context=None):
            wyslane["payload"] = json.loads(req.data.decode("utf-8"))
            return Odp()

        stary, stare_env = urllib.request.urlopen, os.environ.get("SLACK_WEBHOOK_URL")
        urllib.request.urlopen = falszywy_urlopen
        os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.example/test"
        try:
            ok, _ = przetworz.send_slack("zapas", blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "x"}}])
            self.assertTrue(ok)
            self.assertEqual(wyslane["payload"]["text"], "zapas")
            self.assertEqual(wyslane["payload"]["blocks"][0]["type"], "section")
            przetworz.send_slack("sam tekst")
            self.assertNotIn("blocks", wyslane["payload"])
        finally:
            urllib.request.urlopen = stary
            if stare_env is None:
                os.environ.pop("SLACK_WEBHOOK_URL", None)
            else:
                os.environ["SLACK_WEBHOOK_URL"] = stare_env


class TestWiadomoscPoPrzetworzeniu(unittest.TestCase):
    """Wiadomość po rozmowie albo mailu: zdanie, tylko to co wymaga człowieka, link."""

    def _msg(self, pozycje, sync="", **kw):
        import tempfile, przetworz
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "wynik.json"
            f.write_text(json.dumps({"spotkanie": {"data": "2026-10-13"}, "pozycje": pozycje}), encoding="utf-8")
            return przetworz.build_slack_message("klient-testowy", f, sync, **kw)

    def test_zdanie_na_gorze_mowi_co_sie_zmienilo(self):
        sync = "  ✓ RIN-1 (a) → zamknieta\n  ✓ RIN-2 (b) → zrob_teraz\n  Utworzono zgłoszeń:            3\n"
        tekst, _ = self._msg([], sync)
        self.assertEqual(tekst.splitlines()[0],
                         ":white_check_mark: *klient-testowy*: rozmowa z 13.10 przetworzona. "
                         "Nowych zgłoszeń: 3, zamkniętych: 1, wznowionych: 1.")

    def test_mail_mowi_ze_zrodlem_byl_mail_i_podaje_temat(self):
        tekst, _ = self._msg([], "", meta_maila={"data": "2026-10-14", "temat": "Re: Plik <!channel>"})
        self.assertTrue(tekst.startswith(":email: *klient-testowy*: mail „Re: Plik &lt;!channel&gt;” przetworzony."))
        self.assertIn("Bez zmian w zgłoszeniach.", tekst)

    def test_bez_spraw_dla_czlowieka_jedno_zdanie_zamiast_sekcji(self):
        tekst, _ = self._msg([poz(klucz_sprawy="a")])      # zwykła pozycja idzie do agenta
        self.assertIn("Nic nie wymaga człowieka.", tekst)
        self.assertNotIn("*Wymaga człowieka*", tekst)

    def test_tylko_to_co_wymaga_czlowieka_z_powodem_w_jednym_slowie(self):
        pozycje = [poz(klucz_sprawy="a", tytul="Naprawa listy"),
                   poz(klucz_sprawy="b", typ="finanse", tytul="Korekta kwoty faktury"),
                   poz(klucz_sprawy="c", tytul="Wysłać Kasi zestawienie")]
        tekst, _ = self._msg(pozycje)
        linie = [l for l in tekst.splitlines() if l.startswith("• ")]
        self.assertEqual(len(linie), 2, "zwykła naprawa idzie do agenta i nie pojawia się w wiadomości")
        self.assertTrue(any(l.endswith("Korekta kwoty faktury · klient-testowy · pieniądze") for l in map(tekst_widoczny, linie)))
        self.assertTrue(any(l.endswith("Wysłać Kasi zestawienie · klient-testowy · klient") for l in map(tekst_widoczny, linie)))
        self.assertNotIn("Naprawa listy", tekst)

    def test_nie_ma_zerowych_linii_ani_technicznych_nazw(self):
        tekst, _ = self._msg([poz(klucz_sprawy="a")], "  ✓ RIN-1 (klucz-sprawy) → zamknieta\n")
        for zakazane in ("Zamknięte: 0", "Wznowione: 0", "Do weryfikacji: 0", "klucz-sprawy", "Zrób teraz:"):
            self.assertNotIn(zakazane, tekst)
        self.assertNotRegex(tekst_widoczny(tekst), r"RIN-\d+")

    def test_odrzucona_zmiana_i_nieudane_testy_wymagaja_czlowieka(self):
        sync = "  ⛔ Odrzucono aktualizację: Z4 → anulowana | brak uprawnień\n"
        tekst, _ = self._msg([], sync, testy_wynik="FAIL 37/38")
        self.assertIn("odrzucono: brak uprawnień", tekst)
        self.assertIn("Testy oczekiwań nie przeszły (FAIL 37/38)", tekst)

    def test_model_i_testy_w_szarej_linijce_na_dole(self):
        tekst, bloki = self._msg([], "", model="claude-sonnet-5-5", testy_wynik="PASS 20/20")
        self.assertEqual(bloki[-1]["type"], "context")
        self.assertEqual(bloki[-1]["elements"][0]["text"], "model: claude-sonnet-5-5 · testy oczekiwań: PASS 20/20")
        self.assertNotIn("Testy oczekiwań nie przeszły", tekst)


class TestPrzeliczanieIstniejacychZgloszen(unittest.TestCase):

    def _licz(self, item, etykiety, klucz="lista", prosby=None, zrodlo="ops/z.md"):
        k = karta()
        k["otwarte_sprawy"] = {klucz: {"linear_id": "x", "identifier": "RIN-9"}}
        stan = {"RIN-9": {"labels": [{"id": str(i), "name": n} for i, n in enumerate(etykiety)], "type": "unstarted"}}
        return przelicz.licz("k", k, Z, prosby or {}, {klucz: (item, zrodlo)}, stan)[0]

    def test_stare_zgloszenie_dla_agenta_z_kosztem_przechodzi_do_czlowieka(self):
        w = self._licz(poz(typ="finanse", klucz_sprawy="lista"), ["Finanse", "Dla agenta"])
        self.assertEqual((w["stare"], w["nowe"]), ("agent", "czlowiek"))
        self.assertIn("Decyzja człowieka", w["dodaj"])
        self.assertIn("Dla agenta", w["usun"])
        self.assertTrue(w["powody"])

    def test_zgloszenie_bez_routingu_dostaje_agenta(self):
        w = self._licz(poz(), ["Błąd"])
        self.assertEqual((w["stare"], w["nowe"], w["dodaj"]), ("brak", "agent", ["Dla agenta"]))

    def test_bez_kryteriow_dostaje_do_weryfikacji_z_powodem(self):
        w = self._licz(poz(kryteria_akceptacji=[]), ["Błąd", "Dla agenta"])
        self.assertEqual(w["nowe"], "weryfikacja")
        self.assertEqual(w["powody"], ["brak kryteriów"])
        self.assertEqual((w["dodaj"], w["usun"]), (["Do weryfikacji"], ["Dla agenta"]))

    def test_oczekujaca_sprawa_nie_dostaje_routingu_ale_wznowiona_tak(self):
        item = poz(sekcja=2, typ="czeka_na_klienta")
        self.assertEqual(self._licz(item, ["Czeka na klienta"])["nowe"], "czeka")
        self.assertEqual(self._licz(item, ["Zadanie"])["nowe"], "agent", "bez etykiety Czeka na klienta = wznowiona")

    def test_ryzyko_nie_jest_routowane(self):
        w = self._licz(poz(sekcja=5, tytul="Oferta z cennikiem"), ["Ryzyko"])
        self.assertEqual(w["nowe"], "ryzyko")
        self.assertEqual((w["dodaj"], w["usun"]), ([], []))

    def test_idempotentne_ponowne_przeliczenie_nic_nie_zmienia(self):
        w = self._licz(poz(), ["Błąd", "Dla agenta"])
        self.assertEqual((w["dodaj"], w["usun"]), ([], []))

    def test_raport_wypisuje_liczbe_zmian_i_powody(self):
        wiersze = [self._licz(poz(typ="finanse"), ["Finanse", "Dla agenta"]), self._licz(poz(), ["Błąd", "Dla agenta"])]
        bufor = io.StringIO()
        with contextlib.redirect_stdout(bufor):
            zmienione = przelicz.raport(wiersze)
        self.assertEqual(len(zmienione), 1)
        self.assertIn("zmieniło przypisanie: 1", bufor.getvalue())
        self.assertIn("powód: kosztuje pieniądze", bufor.getvalue())


class TestRoutingPrzyWznowieniu(unittest.TestCase):

    def test_zapisz_przypisanie_zapamietuje_routing_po_wznowieniu_i_limit_przypomnien(self):
        entry = {}
        linear_sync.zapisz_przypisanie(
            entry, poz(sekcja=2, typ="czeka_na_klienta", tytul="Wysłać Kasi zaproszenie", klucz_sprawy="zap",
                       przypomnienie={"limit": "1 raz"}), Z, karta(), False)
        self.assertEqual(entry["przypisanie"]["komu"], "czeka")
        self.assertEqual(entry["po_wznowieniu"]["komu"], "czlowiek")
        self.assertTrue(entry["po_wznowieniu"]["wymaga_szkicu"])
        self.assertEqual(entry["przypomnienie"], {"limit": 1, "wykorzystane": 0, "nie_przypominac": False})


if __name__ == "__main__":
    unittest.main(verbosity=2)
