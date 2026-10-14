#!/usr/bin/env python3
"""test_wysylka.py – szkice maili (szkice.py) i wysyłka (wyslij.py) bez sieci i bez prawdziwej skrzynki.

Poczta, Linear, Slack, karta i czas są atrapami: żaden test nie wysyła maila. Uruchomienie: python3 testy/test_wysylka.py
"""

import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import szkice
import wyslij as wy
import zasady

Z = zasady.wczytaj_zasady()
W = Z["wysylka"]
E = Z["etykiety"]
SROD = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)       # środa 10:00 w Polsce

KARTA = {
    "klient": "Auto-Tama",
    "kontakty": [{"imie": "Kasia Malinowska", "email": "kasia@autotama.pl", "rola": "BDC, kontakt główny", "potwierdzony": True},
                 {"imie": "Ola Wrona", "email": "ola@autotama.pl", "rola": "BDC", "potwierdzony": True},
                 {"imie": "Paweł", "email": "pawel@autotama.pl", "rola": "przełożony", "potwierdzony": False}],
    "zakazy": [
        {"id": "Z7", "tytul": "Nie wysyłać Kasi wzoru pliku leadów", "opis": "", "cytat": []},
        {"id": "Z8", "tytul": "Nie kontaktować się z Olą bezpośrednio – tylko przez Kasię", "opis": "", "cytat": []},
        {"id": "Z17", "tytul": "Nie przypominać Kasi o pliku ze świeżymi leadami", "opis": "", "cytat": []}],
}
OPIS = ("## Cel\n\nGodziny w sobotę do 15:00.\n\n## Kontekst\n\nKlient prosi o poprawkę.\n\n> Napisz mi, jak będzie poprawione.\n\n"
        "## Kryteria akceptacji\n\n- [ ] config: Toruń sobota do 15:00\n\n## Czego nie ruszać\n\n- Zakaz Z4: Nie włączać Opla\n\n## Źródło\n\n`x`")
DOBRA = "Dzień dobry, Kasia,\n\nw sobotę podajemy już godziny do 15:00 w obu salonach.\n\nPozdrawiam\nMarek Rewoliński"


def zg(numer, klient="auto-tama", labels=("Konfiguracja", "Dla agenta"), opis=OPIS, tytul="Godziny w sobotę", completed="2026-10-14T07:00:00Z", stan="Done", created="2026-10-14T06:00:00Z"):
    return {"createdAt": created, "id": f"id{numer}", "identifier": f"RIN-{numer}", "title": f"[{klient}] {tytul}", "description": opis,
            "url": f"https://linear.app/x/issue/RIN-{numer}/a", "state": stan, "labels": list(labels), "completedAt": completed}


def komentarz_szkicu(zgl=("RIN-41",), do="Kasia Malinowska", temat="Godziny w sobotę", tresc=DOBRA, utworzony="2026-10-14T07:30:00Z"):
    return {"id": "c", "createdAt": utworzony, "body": wy.format_komentarza_szkicu(do, temat, tresc, list(zgl))}


class AtrapaLinear:
    def __init__(self, zgloszenia=(), komentarze=None):
        self.zgloszenia = {z["identifier"]: z for z in zgloszenia}
        self.kom = komentarze or {}
        self.zdarzenia = []

    def z_etykieta(self, nazwa):
        return [copy.deepcopy(z) for z in self.zgloszenia.values() if nazwa in z["labels"]]

    def ukonczone(self, od):
        return [copy.deepcopy(z) for z in self.zgloszenia.values() if z["state"] == "Done"]

    def otwarte(self, stany):
        return [copy.deepcopy(z) for z in self.zgloszenia.values() if z["state"] in stany]

    def zgloszenie_po_numerze(self, n):
        return self.zgloszenia.get(f"RIN-{n}")

    def komentarze(self, z):
        return list(self.kom.get(z["identifier"], []))

    def komentarz(self, z, tekst):
        self.zdarzenia.append(("komentarz", z["identifier"], tekst))
        self.kom.setdefault(z["identifier"], []).append({"id": "n", "createdAt": "2026-10-14T09:00:00Z", "body": tekst})

    def dodaj_etykiete(self, z, nazwa):
        for t in (z, self.zgloszenia.get(z["identifier"], z)):
            if nazwa not in t["labels"]:
                t["labels"].append(nazwa)
        self.zdarzenia.append(("+", z["identifier"], nazwa))

    def usun_etykiete(self, z, nazwa):
        for t in (z, self.zgloszenia.get(z["identifier"], z)):
            if nazwa in t["labels"]:
                t["labels"].remove(nazwa)
        self.zdarzenia.append(("-", z["identifier"], nazwa))

    def typy(self, rodzaj):
        return [z[1:] for z in self.zdarzenia if z[0] == rodzaj]


class AtrapaPoczta:
    def __init__(self, blad=None):
        self.wyslane, self.blad = [], blad

    def wyslij(self, email, imie, temat, tresc):
        if self.blad:
            raise RuntimeError(self.blad)
        self.wyslane.append({"email": email, "imie": imie, "temat": temat, "tresc": tresc})
        return f"<{len(self.wyslane)}@test>"


class AtrapaSlack:
    def __init__(self):
        self.wiadomosci = []

    def wyslij(self, tekst, bloki=None):
        self.wiadomosci.append(tekst)


class AtrapaClaude:
    def __init__(self, *odpowiedzi):
        self.odpowiedzi, self.prompty = list(odpowiedzi), []

    def zapytaj(self, prompt):
        self.prompty.append(prompt)
        return self.odpowiedzi.pop(0) if len(self.odpowiedzi) > 1 else self.odpowiedzi[0]


class Srodowisko:
    def __init__(self, zgloszenia=(), komentarze=None, karta=None, teraz=SROD, poczta=None, claude=None):
        self.Z = Z
        self.linear = AtrapaLinear(zgloszenia, komentarze)
        self.poczta, self.slack, self.claude = poczta or AtrapaPoczta(), AtrapaSlack(), claude or AtrapaClaude('{"temat": "T", "tresc": "x"}')
        self.karta = copy.deepcopy(karta if karta is not None else KARTA)
        self.teraz = lambda: teraz
        self.sucho = False
        self.zapisy = 0

    def wczytaj_karte(self, klient):
        return self.karta

    def zapisz_karte(self, klient, karta):
        self.karta = karta
        self.zapisy += 1

    def inni_klienci(self, klient):
        return [("klinika-usmiech", "Klinika Uśmiech")]


def wyslij_jedno(tresc=DOBRA, temat="Godziny w sobotę", labels=("Konfiguracja", "Wyślij", "Szkic gotowy"), karta=None, teraz=SROD, poczta=None, do="Kasia Malinowska"):
    z = zg(41, labels=labels)
    s = Srodowisko([z], {"RIN-41": [komentarz_szkicu(do=do, temat=temat, tresc=tresc)]}, karta, teraz, poczta)
    return s, wy.uruchom(s)


# ── szkic w komentarzu ────────────────────────────────────────────────────────

class TestSzkicKomentarz(unittest.TestCase):

    def test_format_i_parsowanie_okragle(self):
        k = komentarz_szkicu(zgl=("RIN-41", "RIN-40"))
        p = wy.parsuj_szkic([k])
        self.assertEqual((p["do"], p["temat"], p["zgloszenia"]), ("Kasia Malinowska", "Godziny w sobotę", ["RIN-41", "RIN-40"]))
        self.assertEqual(p["tresc"], DOBRA)

    def test_wysylany_jest_najnowszy_szkic(self):
        stary = komentarz_szkicu(tresc="Dzień dobry, stara wersja", utworzony="2026-10-14T07:00:00Z")
        nowy = komentarz_szkicu(tresc="Dzień dobry, nowa wersja", utworzony="2026-10-14T08:00:00Z")
        self.assertIn("nowa", wy.parsuj_szkic([nowy, stary])["tresc"])

    def test_komentarz_zbiorczy_wskazuje_glowne_zgloszenie(self):
        k = {"id": "z", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-41")}
        self.assertEqual(wy.parsuj_szkic([k]), {"zbiorczy": "RIN-41"})

    def test_brak_szkicu(self):
        self.assertIsNone(wy.parsuj_szkic([{"id": "x", "createdAt": "2026-10-14T07:00:00Z", "body": "zwykły komentarz"}]))


# ── poprawna wysyłka ──────────────────────────────────────────────────────────

class TestWysylkaPoprawna(unittest.TestCase):

    def test_wysyla_do_kontaktu_z_karty_i_sprzata_etykiety(self):
        s, w = wyslij_jedno()
        self.assertEqual(w[0]["status"], "wyslane")
        self.assertEqual(len(s.poczta.wyslane), 1)
        self.assertEqual(s.poczta.wyslane[0]["email"], "kasia@autotama.pl")
        etyk = s.linear.zgloszenia["RIN-41"]["labels"]
        self.assertIn("Wysłano", etyk)
        self.assertNotIn("Wyślij", etyk)
        self.assertNotIn("Szkic gotowy", etyk)
        self.assertTrue(any(k[2].startswith("Wysłano 2026-10-14 10:00") for k in s.linear.zdarzenia if k[0] == "komentarz"))

    def test_historia_wysylek_z_message_id_w_karcie(self):
        s, _ = wyslij_jedno()
        h = s.karta["historia_wysylek"]
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["message_id"], h[0]["do"], h[0]["zgloszenia"]), ("<1@test>", "Kasia Malinowska", ["RIN-41"]))
        self.assertTrue(h[0]["data"].startswith("2026-10-14T10:00"))

    def test_slack_wyslano_do_osoby_z_tematem(self):
        s, _ = wyslij_jedno()
        self.assertEqual(s.slack.wiadomosci, [":email: Wysłano do Kasia Malinowska: Godziny w sobotę"])

    def test_mail_zbiorczy_oznacza_wszystkie_zgloszenia_grupy(self):
        z1, z2 = zg(41), zg(40, labels=("Konfiguracja", "Szkic gotowy"))
        z1["labels"] += ["Wyślij", "Szkic gotowy"]
        s = Srodowisko([z1, z2], {"RIN-41": [komentarz_szkicu(zgl=("RIN-41", "RIN-40"))]})
        wy.uruchom(s)
        self.assertEqual(len(s.poczta.wyslane), 1, "jeden mail zbiorczy")
        for n in ("RIN-41", "RIN-40"):
            self.assertIn("Wysłano", s.linear.zgloszenia[n]["labels"])
            self.assertNotIn("Szkic gotowy", s.linear.zgloszenia[n]["labels"])

    def test_nic_nie_wychodzi_bez_etykiety_wyslij(self):
        z = zg(41, labels=("Konfiguracja", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-41": [komentarz_szkicu()]})
        self.assertEqual(wy.uruchom(s), [])
        self.assertEqual(s.poczta.wyslane, [])

    def test_sucho_nic_nie_wysyla_i_nie_zmienia(self):
        z = zg(41, labels=("Konfiguracja", "Wyślij"))
        s = Srodowisko([z], {"RIN-41": [komentarz_szkicu()]})
        s.sucho = True
        self.assertEqual(wy.uruchom(s)[0]["status"], "wyslalby")
        self.assertEqual((s.poczta.wyslane, s.linear.zdarzenia, s.slack.wiadomosci, s.zapisy), ([], [], [], 0))


# ── bezpiecznik 1: duplikaty ──────────────────────────────────────────────────

class TestDuplikaty(unittest.TestCase):

    def test_drugi_raz_ten_sam_szkic_nie_wychodzi_historia(self):
        s, _ = wyslij_jedno()
        s.linear.zgloszenia["RIN-41"]["labels"] = ["Konfiguracja", "Wyślij"]    # ktoś znów dodał „Wyślij”, etykieta Wysłano zniknęła
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("już wysłano", w[0]["powod"])
        self.assertEqual(len(s.poczta.wyslane), 1)

    def test_etykieta_wyslano_wystarczy_do_zablokowania(self):
        s, w = wyslij_jedno(labels=("Konfiguracja", "Wyślij", "Wysłano"))
        self.assertEqual(w[0]["status"], "pominiete")
        self.assertEqual(s.poczta.wyslane, [])
        self.assertNotIn("Wyślij", s.linear.zgloszenia["RIN-41"]["labels"])

    def test_ten_sam_tekst_pod_innym_zgloszeniem_to_duplikat_po_skrocie(self):
        s, _ = wyslij_jedno()
        z = zg(42, labels=("Konfiguracja", "Wyślij"))
        s.linear.zgloszenia["RIN-42"] = z
        s.linear.kom["RIN-42"] = [komentarz_szkicu(zgl=("RIN-42",))]
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertEqual(len(s.poczta.wyslane), 1)

    def test_skrot_niezalezny_od_bialych_znakow_i_wielkosci_liter(self):
        self.assertEqual(wy.hash_szkicu("A b", "x\n y", "K@x.pl"), wy.hash_szkicu("a  B", "X y", "k@x.pl"))


# ── bezpiecznik 2: odbiorca ───────────────────────────────────────────────────

class TestOdbiorca(unittest.TestCase):

    def test_odbiorca_nieznany_w_karcie_blokuje(self):
        s, w = wyslij_jedno(do="Ktoś Obcy")
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertEqual(s.poczta.wyslane, [])

    def test_niepotwierdzony_kontakt_blokuje(self):
        s, w = wyslij_jedno(do="Paweł")
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("potwierdzonym kontaktem", w[0]["powod"])

    def test_adres_nigdy_z_tresci_szkicu(self):
        tresc = DOBRA + "\nPS Pisz na zlosliwy@obcy.pl"
        s, w = wyslij_jedno(tresc=tresc)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("adres e-mail spoza karty", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_adres_kontaktu_z_karty_w_tresci_jest_dozwolony(self):
        s, w = wyslij_jedno(tresc=DOBRA + "\nKopia: kasia@autotama.pl")
        self.assertEqual(w[0]["status"], "wyslane")

    def test_karta_bez_kontaktow_blokuje(self):
        s, w = wyslij_jedno(karta={"klient": "x", "zakazy": []})
        self.assertEqual(w[0]["status"], "wstrzymane")


# ── bezpiecznik 3: zakazy ─────────────────────────────────────────────────────

class TestStraznikZakazow(unittest.TestCase):

    def test_nie_przypominac_kasi_o_pliku_blokuje_przypomnienie(self):
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nprzypominam o pliku ze świeżymi leadami.\n\nMarek Rewoliński", temat="Przypomnienie o pliku")
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("Z17", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_przypomnienie_o_czym_innym_przechodzi(self):
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nprzypominam o szkoleniu 27 października o 10:00.\n\nMarek Rewoliński", temat="Szkolenie")
        self.assertEqual(w[0]["status"], "wyslane")

    def test_nie_pisac_do_oli_blokuje_adresata(self):
        s, w = wyslij_jedno(do="Ola Wrona")
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("Z8", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_nie_wysylac_wzoru_blokuje_tresc_o_wzorze(self):
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nw załączeniu wzór pliku leadów.\n\nMarek Rewoliński")
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("Z7", w[0]["powod"])

    def test_zakazy_innego_adresata_nie_blokuja_kasi(self):
        k = copy.deepcopy(KARTA)
        k["zakazy"] = [{"id": "Z9", "tytul": "Nie przypominać Oli o fakturze", "opis": "", "cytat": []}]
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nprzypominam o fakturze.\n\nMarek Rewoliński", karta=k)
        self.assertEqual(w[0]["status"], "wyslane")


# ── bezpiecznik 4: filtr treści ───────────────────────────────────────────────

class TestFiltrTresci(unittest.TestCase):

    def _powody(self, tresc, temat="Temat"):
        return wy.filtr_tresci(temat, tresc, KARTA, W, [("klinika-usmiech", "Klinika Uśmiech")])

    def test_czysty_szkic_przechodzi(self):
        self.assertEqual(self._powody(DOBRA), [])

    def test_identyfikator_zgloszenia(self):
        self.assertTrue(self._powody("Poprawione w RIN-41."))
        self.assertTrue(self._powody("ok", temat="Sprawa rin-41"))

    def test_nazwa_narzedzia_linear(self):
        self.assertTrue(self._powody("Zgłoszenie w Linear zamknięte."))

    def test_slowo_zakaz(self):
        self.assertTrue(self._powody("Mamy zakaz ruszania Opla."))

    def test_inny_klient_po_slugu_nazwie_i_wariancie(self):
        for tekst in ("Robimy to samo dla klinika-usmiech.", "Podobnie jak w Klinika Uśmiech.", "Tak jak klinika usmiech."):
            self.assertTrue(self._powody(tekst), tekst)

    def test_klucze_i_pliki_techniczne(self):
        self.assertTrue(self._powody("Zmiana w godziny-salonu-sobota."))
        self.assertTrue(self._powody("Zmieniono config/auto-tama.yaml."))

    def test_obcy_adres_email(self):
        self.assertTrue(self._powody("Napisz na ktos@obcy.pl"))

    def test_zablokowany_szkic_trafia_do_weryfikacji_z_powodem_i_slackiem(self):
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nzamknęliśmy RIN-41.\n\nMarek Rewoliński")
        self.assertEqual(w[0]["status"], "wstrzymane")
        etyk = s.linear.zgloszenia["RIN-41"]["labels"]
        self.assertIn("Do weryfikacji", etyk)
        self.assertNotIn("Wyślij", etyk, "bez zdjęcia etykiety blokada powtarzałaby się co 15 minut")
        self.assertTrue(any("Wysyłka wstrzymana" in k[2] and "RIN-" in k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"))
        self.assertTrue(s.slack.wiadomosci[0].startswith(":no_entry: Wysyłka wstrzymana:"))
        self.assertEqual(s.poczta.wyslane, [])


# ── bezpiecznik 5: limit dzienny ──────────────────────────────────────────────

class TestLimitDzienny(unittest.TestCase):

    def _karta_z_wysylkami(self, n, dzien="2026-10-14"):
        k = copy.deepcopy(KARTA)
        k["historia_wysylek"] = [{"data": f"{dzien}T0{i + 1}:00:00+02:00", "message_id": f"<{i}>", "do": "Kasia Malinowska",
                                  "temat": f"inny {i}", "zgloszenia": [f"RIN-9{i}"], "hash": f"h{i}"} for i in range(n)]
        return k

    def test_limit_z_zasad_to_dwa(self):
        self.assertEqual(W["max_dziennie_na_klienta"], 2)

    def test_trzeci_mail_dnia_czeka(self):
        s, w = wyslij_jedno(karta=self._karta_z_wysylkami(2))
        self.assertEqual(w[0]["status"], "czeka")
        self.assertIn("limit 2", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])
        self.assertIn("Wyślij", s.linear.zgloszenia["RIN-41"]["labels"], "etykieta zostaje: mail wyjdzie jutro")

    def test_drugi_mail_dnia_przechodzi(self):
        s, w = wyslij_jedno(karta=self._karta_z_wysylkami(1))
        self.assertEqual(w[0]["status"], "wyslane")

    def test_wczorajsze_wysylki_sie_nie_licza(self):
        s, w = wyslij_jedno(karta=self._karta_z_wysylkami(2, "2026-10-13"))
        self.assertEqual(w[0]["status"], "wyslane")


# ── bezpiecznik 6: okno czasowe ───────────────────────────────────────────────

class TestOknoCzasowe(unittest.TestCase):

    def _status(self, utc):
        s, w = wyslij_jedno(teraz=utc)
        return w[0]["status"], s

    def test_dzien_roboczy_w_godzinach_przechodzi(self):
        self.assertEqual(self._status(datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc))[0], "wyslane")      # 8:00 czas letni

    def test_przed_8_i_od_18_czeka(self):
        for godz in (datetime(2026, 10, 14, 5, 59, tzinfo=timezone.utc), datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)):
            st, s = self._status(godz)
            self.assertEqual(st, "czeka", godz)
            self.assertEqual(s.poczta.wyslane, [])

    def test_weekend_czeka(self):
        for dzien in (17, 18):
            self.assertEqual(self._status(datetime(2026, 10, dzien, 9, 0, tzinfo=timezone.utc))[0], "czeka")

    def test_swieto_czeka(self):
        self.assertEqual(self._status(datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc))[0], "czeka")

    def test_czas_polski_a_nie_utc_zima(self):
        # 2026-12-02 (środa): 7:30 UTC = 8:30 w Polsce → wolno; 6:30 UTC = 7:30 w Polsce → czeka
        self.assertEqual(self._status(datetime(2026, 12, 2, 7, 30, tzinfo=timezone.utc))[0], "wyslane")
        self.assertEqual(self._status(datetime(2026, 12, 2, 6, 30, tzinfo=timezone.utc))[0], "czeka")

    def test_oczekiwanie_nie_zmienia_etykiet_i_slack_tylko_raz(self):
        noc = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)
        s, _ = wyslij_jedno(teraz=noc)
        self.assertEqual(s.linear.typy("+"), [])
        self.assertEqual(len(s.slack.wiadomosci), 1)
        wy.uruchom(s)
        self.assertEqual(len(s.slack.wiadomosci), 1, "ten sam powód: bez powtórnego Slacka")


# ── bezpiecznik 7: urlop kontaktu ─────────────────────────────────────────────

class TestUrlop(unittest.TestCase):

    def _karta_z_urlopem(self):
        k = copy.deepcopy(KARTA)
        k["kontakty"][0]["nieobecnosci"] = [{"od": "2026-10-19", "do": "2026-10-23"}]
        return k

    def test_mail_czeka_do_powrotu_a_slack_dostaje_informacje(self):
        pon = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
        s, w = wyslij_jedno(karta=self._karta_z_urlopem(), teraz=pon)
        self.assertEqual(w[0]["status"], "czeka")
        self.assertIn("nieobecna do 2026-10-23", w[0]["powod"])
        self.assertIn("od 2026-10-24", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])
        self.assertTrue(s.slack.wiadomosci[0].startswith(":hourglass_flowing_sand: Wysyłka wstrzymana: Kasia Malinowska jest nieobecna"))

    def test_po_powrocie_wychodzi(self):
        pon = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
        s, w = wyslij_jedno(karta=self._karta_z_urlopem(), teraz=pon)
        self.assertEqual(w[0]["status"], "wyslane")

    def test_dzien_przed_urlopem_wychodzi(self):
        s, w = wyslij_jedno(karta=self._karta_z_urlopem(), teraz=datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(w[0]["status"], "wyslane")

    def test_karta_auto_tama_ma_urlop_kasi_ze_zrodlem(self):
        import json
        k = json.loads((Path(__file__).parent.parent / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        kasia = next(c for c in k["kontakty"] if c["imie"] == "Kasia Malinowska")
        self.assertEqual(kasia["nieobecnosci"][0]["od"], "2026-10-19")
        self.assertEqual(kasia["nieobecnosci"][0]["do"], "2026-10-23")


# ── błędy poczty ──────────────────────────────────────────────────────────────

class TestBladPoczty(unittest.TestCase):

    def test_blad_smtp_nie_oznacza_jako_wyslane_i_ponawia_pozniej(self):
        s, w = wyslij_jedno(poczta=AtrapaPoczta("SMTPAuthenticationError"))
        self.assertEqual(w[0]["status"], "czeka")
        self.assertNotIn("historia_wysylek", s.karta)
        self.assertIn("Wyślij", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertNotIn("Wysłano", s.linear.zgloszenia["RIN-41"]["labels"])

    def test_brak_szkicu_blokuje(self):
        s = Srodowisko([zg(41, labels=("Wyślij",))])
        self.assertEqual(wy.uruchom(s)[0]["status"], "wstrzymane")

    def test_wyslij_na_zgloszeniu_podrzednym_zbiorczego_blokuje(self):
        z = zg(40, labels=("Wyślij",))
        s = Srodowisko([z], {"RIN-40": [{"id": "z", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-41")}]})
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("RIN-41", w[0]["powod"])


# ── szkice ────────────────────────────────────────────────────────────────────

class TestSzkice(unittest.TestCase):

    def test_kwalifikacja_prosba_klienta_i_typ_do_klienta(self):
        self.assertEqual(szkice.powod_szkicu(zg(1), Z), "prosba")
        bez = OPIS.replace("> Napisz mi, jak będzie poprawione.", "> Dzięki.")
        self.assertIsNone(szkice.powod_szkicu(zg(2, opis=bez), Z))
        self.assertEqual(szkice.powod_szkicu(zg(3, opis=bez, labels=("Czeka na klienta",)), Z), "do_klienta")
        self.assertEqual(szkice.powod_szkicu(zg(4, opis=bez, tytul="Przypomnienie o pliku leadów"), Z), "wiadomosc")
        self.assertEqual(szkice.powod_szkicu(zg(5, opis=bez, tytul="Zestawienie wyników tygodnia"), Z), "wiadomosc")

    def test_notatki_wewnetrzne_bez_szkicu(self):
        self.assertIsNone(szkice.powod_szkicu(zg(1, tytul="Notatka przed spotkaniem z Pawłem", labels=("Czeka na klienta",)), Z))

    def test_szkic_komentarz_i_etykieta_bez_wysylki(self):
        s = Srodowisko([zg(41)], claude=AtrapaClaude('{"temat": "Godziny w sobotę", "tresc": ' + __import__("json").dumps(DOBRA) + '}'))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "szkic")
        self.assertIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertEqual(s.poczta.wyslane, [])
        self.assertEqual(s.slack.wiadomosci, [])
        p = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-41"]))
        self.assertEqual((p["do"], p["temat"]), ("Kasia Malinowska", "Godziny w sobotę"))

    def test_kilka_szkicow_klienta_z_jednego_dnia_to_jeden_mail(self):
        z1, z2 = zg(41), zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia")
        s = Srodowisko([z2, z1], claude=AtrapaClaude('{"temat": "Dwie poprawki", "tresc": ' + __import__("json").dumps(DOBRA) + '}'))
        w = szkice.uruchom(s)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["zgloszenia"], ["RIN-41", "RIN-40"], "najstarsze jako główne")
        self.assertEqual(len(s.claude.prompty), 1, "jedno wywołanie modelu na grupę")
        self.assertIn("Godziny dzwonienia", s.claude.prompty[0])
        glowny = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-41"]))
        self.assertEqual(glowny["zgloszenia"], ["RIN-41", "RIN-40"])
        self.assertEqual(wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-40"])), {"zbiorczy": "RIN-41"})

    def test_rozne_dni_albo_klienci_to_osobne_maile(self):
        z1 = zg(41)
        z2 = zg(40, completed="2026-10-13T08:30:00Z")
        z3 = zg(65, klient="klinika-usmiech")
        grupy = szkice.grupuj([z1, z2, z3], Z)
        self.assertEqual(len(grupy), 3)

    def test_prompt_nie_zawiera_zakazow_ani_czego_nie_ruszac(self):
        s = Srodowisko([zg(41)])
        szkice.uruchom(s)
        p = s.claude.prompty[0]
        self.assertNotIn("Czego nie ruszać", p)
        self.assertNotIn("Zakaz Z4", p)
        self.assertNotIn("Nie włączać Opla", p)
        self.assertNotIn("RIN-41", p.split("MATERIAŁ:")[1])
        self.assertIn("Napisz mi, jak będzie poprawione", p)

    def test_szkic_z_identyfikatorem_jest_odrzucany_i_dostaje_druga_probe(self):
        zly = '{"temat": "T", "tresc": "Dzień dobry, Kasia, zamknęliśmy RIN-41."}'
        dobry = '{"temat": "T", "tresc": ' + __import__("json").dumps(DOBRA) + '}'
        s = Srodowisko([zg(41)], claude=AtrapaClaude(zly, dobry))
        self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic")
        self.assertEqual(len(s.claude.prompty), 2)
        self.assertIn("ODRZUCONY", s.claude.prompty[1])
        self.assertNotIn("zamknęliśmy RIN-41", s.claude.prompty[1], "model nie dostaje treści odrzuconego szkicu")

    def test_dwa_zle_szkice_to_do_weryfikacji_bez_szkicu(self):
        zly = '{"temat": "T", "tresc": "Dzień dobry, Kasia, zamknęliśmy RIN-41."}'
        s = Srodowisko([zg(41)], claude=AtrapaClaude(zly))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "odrzucony")
        self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])

    def test_nieczytelna_odpowiedz_modelu_to_odrzucenie(self):
        s = Srodowisko([zg(41)], claude=AtrapaClaude("nie wiem"))
        self.assertEqual(szkice.uruchom(s)[0]["status"], "odrzucony")

    def test_brak_potwierdzonego_kontaktu_to_do_weryfikacji(self):
        s = Srodowisko([zg(41)], karta={"klient": "x", "kontakty": [], "zakazy": []})
        self.assertEqual(szkice.uruchom(s)[0]["status"], "brak_kontaktu")
        self.assertEqual(s.claude.prompty, [], "bez kontaktu model nie jest pytany")

    def test_odbiorca_to_kontakt_glowny_z_karty(self):
        self.assertEqual(szkice.wybierz_odbiorce(KARTA)["imie"], "Kasia Malinowska")

    def test_szkic_nie_powstaje_ponownie_gdy_juz_jest_i_nic_nowego(self):
        z = zg(41, labels=("Konfiguracja", "Szkic gotowy"))
        s = Srodowisko([z])
        self.assertEqual(szkice.uruchom(s), [])
        self.assertEqual(s.claude.prompty, [])

    def test_nowe_zgloszenie_dolacza_do_niewyslanego_szkicu_tego_dnia(self):
        z1 = zg(41, labels=("Konfiguracja", "Szkic gotowy"))
        z2 = zg(40, completed="2026-10-14T09:00:00Z")
        s = Srodowisko([z1, z2], claude=AtrapaClaude('{"temat": "T", "tresc": ' + __import__("json").dumps(DOBRA) + '}'))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["zgloszenia"], ["RIN-41", "RIN-40"])

    def test_zgloszenie_wyslane_nie_wraca_do_szkicow(self):
        z = zg(41, labels=("Konfiguracja", "Wysłano"))
        self.assertEqual(szkice.uruchom(Srodowisko([z])), [])

    def test_sucho_nic_nie_zmienia(self):
        s = Srodowisko([zg(41)])
        s.sucho = True
        self.assertEqual(szkice.uruchom(s)[0]["status"], "powstalby")
        self.assertEqual((s.linear.zdarzenia, s.claude.prompty), ([], []))


# ── prośba o informację w starszych cytatach i zgłoszenia „do klienta” w Todo ──

OPIS_RIN65 = ("## Cel\n\nBaza wiedzy podaje prawidłową godzinę zamknięcia salonu Sopot w piątek.\n\n## Kontekst\n\n"
              "Od października salon Sopot jest czynny w piątek do 16:00. Marek poprawi dzisiaj i napisze do Ani po korekcie.\n\n"
              "**Właściciel:** Marek Rewoliński\n\n**Cytaty ze źródła:**\n\n> Agent działa nieźle, ale podaje złe godziny dla Sopotu.\n"
              "> To nasz błąd w bazie wiedzy. Poprawię dzisiaj.\n> Nie, nie trzeba. Napisz tylko, jak będzie zrobione.\n\n"
              "## Kryteria akceptacji\n\n- [ ] Sopot w piątek do 16:00\n\n## Czego nie ruszać\n\n- Zakaz Z2: x\n\n## Źródło\n\n`x`")
OPIS_BEZ_PROSBY = OPIS_RIN65.replace("> Nie, nie trzeba. Napisz tylko, jak będzie zrobione.", "> Dzięki.")
OPIS_ZAPROSZENIE = ("## Cel\n\nWysłać Kasi i Pawłowi zaproszenie na spotkanie w czwartek 15.10 o 10:00.\n\n## Kontekst\n\n"
                    "Spotkanie potwierdzone na czwartek o 10:00.\n\n> Możesz wysłać zaproszenie.\n\n## Kryteria akceptacji\n\n"
                    "- [ ] Zaproszenie dotyczy czwartku 15.10, godz. 10:00\n\n## Czego nie ruszać\n\n- Zakaz Z4: Nie włączać Opla\n\n## Źródło\n\n`x`")
KARTA_KLINIKA = {"klient": "Klinika Uśmiech", "zakazy": [],
                 "kontakty": [{"imie": "Ania Zielińska", "email": "ania@klinika.pl", "rola": "kontakt główny", "potwierdzony": True}],
                 "otwarte_sprawy": {"godziny-sopot-piatek": {"identifier": "RIN-65", "zrodla": ["ops/transkrypcje/klinika-usmiech/2026-10-13-call-statusowy.md"]}}}


class TestProsbaOInformacje(unittest.TestCase):

    def test_cytat_napisz_tylko_jak_bedzie_zrobione_to_prosba(self):
        z = zg(65, klient="klinika-usmiech", opis=OPIS_RIN65, tytul="Błędne godziny otwarcia Sopot w piątek", labels=("Konfiguracja", "Repo"))
        self.assertEqual(szkice.powod_szkicu(z, Z), "prosba")

    def test_napisze_marka_to_nie_prosba_klienta(self):
        """„Marek … napisze do Ani” to obietnica Marka, nie prośba klienta."""
        z = zg(65, klient="klinika-usmiech", opis=OPIS_BEZ_PROSBY, tytul="Błędne godziny Sopot")
        self.assertIsNone(szkice.powod_szkicu(z, Z))

    def test_nie_pisz_nie_jest_prosba(self):
        self.assertFalse(szkice.prosba_o_informacje(["Nie napisz nic, dziękuję"], Z))
        self.assertTrue(szkice.prosba_o_informacje(["Daj znać, jak będzie."], Z))
        self.assertTrue(szkice.prosba_o_informacje(["Proszę, odpisz mi."], Z))

    def test_starszy_wynik_bez_nowych_pol_cytat_tylko_w_wyniku_json(self):
        """Opis zgłoszenia nie ma prośby, ale cytat w starszym wynik.json ma."""
        z = zg(65, klient="klinika-usmiech", opis=OPIS_BEZ_PROSBY, tytul="Błędne godziny Sopot")
        self.assertIsNone(szkice.powod_szkicu(z, Z))
        self.assertEqual(szkice.powod_szkicu(z, Z, ["Nie, nie trzeba. Napisz tylko, jak będzie zrobione."]), "prosba")

    def test_cytaty_z_prawdziwego_wyniku_kliniki_dla_rin_65(self):
        root = Path(__file__).parent.parent
        import os
        cwd = os.getcwd()
        os.chdir(root)
        try:
            karta = {"otwarte_sprawy": {"godziny-sopot-piatek": {"identifier": "RIN-65",
                     "zrodla": ["ops/transkrypcje/klinika-usmiech/2026-10-13-call-statusowy.md"]}}}
            c = szkice.cytaty_z_wynikow("klinika-usmiech", karta, "RIN-65")
        finally:
            os.chdir(cwd)
        self.assertTrue(any("Napisz tylko, jak będzie zrobione" in x for x in c), c)
        self.assertTrue(szkice.prosba_o_informacje(c, Z))

    def test_rin_65_done_dostaje_szkic_do_kontaktu_kliniki(self):
        z = zg(65, klient="klinika-usmiech", opis=OPIS_RIN65, tytul="Błędne godziny otwarcia Sopot w piątek", labels=("Konfiguracja",))
        s = Srodowisko([z], karta=KARTA_KLINIKA, claude=AtrapaClaude('{"temat": "Godziny Sopotu", "tresc": "Dzień dobry, Ania,\\n\\ngodziny w piątek w Sopocie są już poprawione (do 16:00).\\n\\nPozdrawiam\\nMarek Rewoliński"}'))
        w = szkice.uruchom(s)
        self.assertEqual(w[0]["status"], "szkic")
        self.assertEqual(w[0]["do"], "Ania Zielińska")
        self.assertIn("Szkic gotowy", s.linear.zgloszenia["RIN-65"]["labels"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_klucz_z_cytatami_ze_zrodel_jest_uzyty_przez_uruchom(self):
        z = zg(65, klient="klinika-usmiech", opis=OPIS_BEZ_PROSBY, tytul="Błędne godziny Sopot", labels=("Konfiguracja",))
        s = Srodowisko([z], karta=KARTA_KLINIKA, claude=AtrapaClaude('{"temat": "T", "tresc": "Dzień dobry, Ania, poprawione.\\nMarek Rewoliński"}'))
        self.assertEqual(szkice.uruchom(s), [])
        s.cytaty_zrodlowe = lambda zgl: ["Napisz tylko, jak będzie zrobione."]
        self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic")


class TestWiadomoscDoKlientaWTodo(unittest.TestCase):

    ZAPROSZENIE = dict(opis=OPIS_ZAPROSZENIE, tytul="Potwierdzenie spotkania Marek–Paweł (15.10, 10:00, Toruń)", labels=("Decyzja człowieka",), stan="Todo")

    def _zaproszenie(self, **kw):
        return zg(51, **{**self.ZAPROSZENIE, **kw})

    def test_cel_to_wiadomosc_rozpoznany_regula_klient_z_zasad(self):
        for tytul in ("Wysłać zaproszenie dla Pawła", "Przypomnienie o pliku", "Zestawienie wyników", "Wycena rozszerzenia", "Ściąga dla handlowców", "Potwierdzenie spotkania"):
            z = zg(1, tytul=tytul, stan="Todo", opis="## Cel\n\nx\n\n## Kontekst\n\ny")
            self.assertEqual(szkice.powod_szkicu(z, Z), "wiadomosc" if tytul != "Potwierdzenie spotkania" else None, tytul)

    def test_ryzyko_z_oferta_konkurenta_to_nie_wiadomosc_do_klienta(self):
        z = zg(71, tytul="Dr Nowak rozważa zmianę dostawcy – oferta konkurenta", stan="Todo", labels=("Ryzyko",), opis="## Cel\n\nx")
        self.assertIsNone(szkice.powod_szkicu(z, Z))

    def test_opis_z_regula_klient_wystarczy_gdy_tytul_nie(self):
        z = zg(1, tytul="Potwierdzenie spotkania", stan="Todo",
               opis="## Cel\n\nx\n\n## Dlaczego człowiek\n\n- trafia do klienta (mail, przypomnienie, oferta): agent przygotowuje gotowy szkic")
        self.assertEqual(szkice.powod_szkicu(z, Z), "wiadomosc")

    def test_zaproszenie_w_todo_dostaje_szkic_od_razu_bez_done(self):
        z = self._zaproszenie()
        s = Srodowisko([z], claude=AtrapaClaude('{"temat": "Zaproszenie na czwartek", "tresc": "Dzień dobry, Kasia,\\n\\nzapraszam na czwartek 15.10 o 10:00.\\n\\nPozdrawiam\\nMarek Rewoliński"}'))
        w = szkice.uruchom(s)
        self.assertEqual(w[0]["status"], "szkic")
        self.assertEqual(s.linear.zgloszenia["RIN-51"]["state"], "Todo", "stan zgłoszenia bez zmian")
        self.assertIn("Szkic gotowy", s.linear.zgloszenia["RIN-51"]["labels"])
        p = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-51"]))
        self.assertEqual(p["do"], "Kasia Malinowska")
        self.assertEqual(s.poczta.wyslane, [])

    def test_in_progress_tez_ale_backlog_nie(self):
        self.assertEqual(len(szkice.uruchom(Srodowisko([self._zaproszenie(stan="In Progress")]))), 1)
        self.assertEqual(szkice.uruchom(Srodowisko([self._zaproszenie(stan="Backlog")])), [])

    def test_zwykla_poprawka_w_todo_nie_dostaje_szkicu_przed_done(self):
        z = zg(41, stan="Todo")          # prośba klienta o informację, ale praca jeszcze trwa
        self.assertEqual(szkice.uruchom(Srodowisko([z])), [])

    def test_istniejacy_szkic_z_opisu_jest_materialem_a_nie_tresciami_do_wyslania(self):
        z = self._zaproszenie(opis=OPIS_ZAPROSZENIE + "\n\n## Szkic dla klienta (do wysłania przez człowieka)\n\n> Cześć Kasia, zapraszam.")
        s = Srodowisko([z])
        szkice.uruchom(s)
        self.assertIn("Wcześniejszy szkic do poprawy", s.claude.prompty[0])
        self.assertNotIn("Zakaz Z4", s.claude.prompty[0])

    def test_otwarte_zaproszenie_nie_dostaje_drugiego_szkicu(self):
        s = Srodowisko([self._zaproszenie(labels=("Decyzja człowieka", "Szkic gotowy"))])
        self.assertEqual(szkice.uruchom(s), [])

    def test_zaproszenie_do_zablokowanego_adresata_przejdzie_dopiero_przy_wysylce(self):
        """Szkic powstaje, ale strażnik w wyslij.py nadal pilnuje zakazów przy wysyłce."""
        z = self._zaproszenie(labels=("Wyślij", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-51": [komentarz_szkicu(zgl=("RIN-51",), do="Ola Wrona", tresc="Dzień dobry, Ola, zapraszam.\nMarek Rewoliński")]})
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertEqual(s.poczta.wyslane, [])


# ── workflow ──────────────────────────────────────────────────────────────────

class TestWorkflow(unittest.TestCase):

    def test_wysylka_w_workflow_sprawdzania_maili_z_sekretami_poczty(self):
        t = (Path(__file__).parent.parent / ".github/workflows/sprawdz-maile.yml").read_text(encoding="utf-8")
        self.assertIn("python3 wyslij.py", t)
        self.assertIn("secrets.GMAIL_APP_PASSWORD", t)
        self.assertIn('cron: "*/15 * * * *"', t)
        self.assertIn("MAILE_WLACZONE", t)

    def test_szkice_w_workflow_agenta(self):
        t = (Path(__file__).parent.parent / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertIn("python3 szkice.py", t)

    def test_agent_nie_dostaje_hasla_do_poczty(self):
        t = (Path(__file__).parent.parent / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertNotIn("GMAIL_APP_PASSWORD", t)


if __name__ == "__main__":
    unittest.main(verbosity=1)
