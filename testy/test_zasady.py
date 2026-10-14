#!/usr/bin/env python3
"""test_zasady.py – testy offline zasad AI-first (ops/zasady.json), opisu zgłoszenia dla agenta,
przeliczania istniejących zgłoszeń i codziennego podsumowania (w tym strefy czasowej i przypomnień).

Bez sieci i bez modelu. Uruchomienie:  python3 testy/test_zasady.py
"""

import contextlib
import copy
import io
import json
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

    def test_zadanie_przygotowawcze_do_ryzyka_idzie_do_agenta_mimo_slow_o_cenach(self):
        ryzyko = poz(sekcja=5, typ="ryzyko_handlowe", klucz_sprawy="ryzyko-vd",
                     tytul="VoiceDesk złożył ofertę z cennikiem")
        prep = zasady.zadanie_przygotowawcze(ryzyko, "k", Z)
        self.assertEqual(prep["klucz_sprawy"], "przygotowanie-ryzyko-vd")
        self.assertIn("Notatka z argumentami przed spotkaniem", prep["tytul"])
        self.assertTrue(zasady.kryteria_ok(prep))
        self.assertEqual(prep["repo"], "rinvo-ops")
        self.assertEqual(zasady.przypisz(prep, Z, karta())["komu"], "agent")

    def test_zadanie_przygotowawcze_z_analizy_ma_pierwszenstwo_przed_szablonem(self):
        ryzyko = poz(sekcja=5, zadanie_przygotowawcze={"cel": "Własny cel", "kryteria_akceptacji": ["A"]})
        prep = zasady.zadanie_przygotowawcze(ryzyko, "k", Z)
        self.assertEqual((prep["cel"], prep["kryteria_akceptacji"]), ("Własny cel", ["A"]))

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
    return {"id": f"id-{ident}", "identifier": ident, "url": f"https://l/{ident}", "title": f"[{klient}] {tytul}",
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


class TestWiadomoscPodsumowania(unittest.TestCase):

    def _dane(self):
        karty = {"k": karta_z_czekajacym({"limit": 1, "wykorzystane": 0, "nie_przypominac": False}),
                 "pusty": karta()}
        otwarte = [
            zgl("RIN-1", "Plik leadów", ["Czeka na klienta"], "2026-10-15"),
            zgl("RIN-2", "Wycena SMS <!channel>", ["Decyzja człowieka"]),
            zgl("RIN-3", "Naprawa", ["Dla agenta"]),
            zgl("RIN-4", "Druga naprawa", ["Dla agenta"]),
            zgl("RIN-5", "Czeka z terminem", ["Czeka na klienta"], "2026-10-20"),
            zgl("RIN-6", "VoiceDesk", ["Ryzyko", "Powtarzające się ryzyko"]),
            zgl("RIN-7", "Brak kryteriów", ["Do weryfikacji"]),
        ]
        nowe = [zgl("RIN-3", "Naprawa", ["Dla agenta"])]
        return podsumowanie.zbierz(otwarte, nowe, karty, Z, DZIS), karty

    def test_kategorie_per_klient(self):
        klienci, _ = self._dane()
        d = klienci["k"]
        self.assertEqual(len(d["nowe"]), 1)
        self.assertEqual(len(d["agent"]), 2)
        self.assertEqual(len(d["czlowiek"]), 1)
        self.assertEqual(len(d["czeka"]), 1)
        self.assertEqual(len(d["po_terminie"]), 1)
        self.assertEqual(len(d["ryzyka"]), 1)
        self.assertEqual(len(d["weryfikacja"]), 1)

    def test_wiadomosc_ma_wszystkie_linie_z_linkami_i_szkicem(self):
        klienci, _ = self._dane()
        msg = podsumowanie.buduj_wiadomosc(klienci, DZIS)
        self.assertIn("*[k]*", msg)
        self.assertIn("Zadania u agentów: 2", msg)
        for linia in ("Nowe od wczoraj: 1", "Decyzje czekające na człowieka: 1",
                      "Czeka na klienta: 1", "Czeka na klienta, po terminie: 1", "Powtarzające się ryzyka: 1",
                      "Szkice przypomnień do wysłania przez człowieka: 1"):
            self.assertIn(linia, msg)
        self.assertIn("<https://l/RIN-1|RIN-1>", msg, "linki do zgłoszeń")
        self.assertIn("do 15.10", msg)
        self.assertIn("> Cześć Kasia,", msg, "szkic przypomnienia na Slacku")

    def test_pusty_klient_ma_linie_z_zerami(self):
        klienci, _ = self._dane()
        msg = podsumowanie.buduj_wiadomosc(klienci, DZIS)
        czesc = msg.split("*[pusty]*")[1]
        self.assertIn("Zadania u agentów: 0", czesc)
        self.assertIn("Decyzje czekające na człowieka: 0", czesc)
        self.assertIn("Czeka na klienta, po terminie: 0", czesc)

    def test_slack_nie_przepuszcza_znacznikow_z_tytulow(self):
        klienci, _ = self._dane()
        msg = podsumowanie.buduj_wiadomosc(klienci, DZIS)
        self.assertNotIn("<!channel>", msg)
        self.assertIn("&lt;!channel&gt;", msg)

    def test_nagłówek_ma_dzien_tygodnia_i_date(self):
        klienci, _ = self._dane()
        self.assertIn("piątek 16.10.2026", podsumowanie.buduj_wiadomosc(klienci, DZIS))


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
