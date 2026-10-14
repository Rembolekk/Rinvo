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
        self.licznik = getattr(self, "licznik", 0) + 1
        self.kom.setdefault(z["identifier"], []).append({"id": f"n{self.licznik}", "createdAt": f"2026-10-14T09:{self.licznik % 60:02d}:00Z", "body": tekst})

    def edytuj_komentarz(self, komentarz_id, tresc):
        for lista in self.kom.values():
            for k in lista:
                if k["id"] == komentarz_id:
                    k["body"] = tresc
        self.zdarzenia.append(("edycja", komentarz_id, tresc))

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

    def nadawca(self):
        return "marek@rinvo.test"

    def wyslij(self, email, imie, temat, tresc, ics=None, zalaczniki=()):
        if self.blad:
            raise RuntimeError(self.blad)
        self.wyslane.append({"email": email, "imie": imie, "temat": temat, "tresc": tresc, "ics": ics, "zalaczniki": list(zalaczniki)})
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


def json_szkic(tresc=DOBRA, temat="Temat", spotkanie=None):
    import json
    return json.dumps({"temat": temat, "tresc": tresc, "spotkanie": spotkanie}, ensure_ascii=False)


def claude_czesci(czesci, laczenie=None):
    """Atrapa: odpowiedź dla części wg słowa kluczowego w prompcie (materiał), dla łączenia zadana odpowiedź."""
    def odp(prompt):
        if "Połącz poniższe części" in prompt:
            return laczenie if laczenie is not None else "nie wiem"
        material = prompt.split("MATERIAŁ:")[1]
        for slowo, tekst in czesci.items():
            if slowo in material:
                return tekst
        raise AssertionError("brak odpowiedzi dla: " + material[:80])
    k = AtrapaClaude("")
    k.zapytaj = lambda prompt: (k.prompty.append(prompt), odp(prompt))[1]
    return k


def json_laczenia(tresc=DOBRA, temat="Dwie sprawy", n=2, pomin=None):
    import json
    nr = [i for i in range(1, n + 1) if i != pomin]
    return json.dumps({"temat": temat, "tresc": tresc, "uwzglednione": nr}, ensure_ascii=False)


class Srodowisko:
    def __init__(self, zgloszenia=(), komentarze=None, karta=None, teraz=SROD, poczta=None, claude=None):
        self.Z = Z
        self.linear = AtrapaLinear(zgloszenia, komentarze)
        self.poczta, self.slack, self.claude = poczta or AtrapaPoczta(), AtrapaSlack(), claude or AtrapaClaude(json_szkic())
        self.karta = copy.deepcopy(karta if karta is not None else KARTA)
        self.teraz = lambda: teraz
        self.sucho = False
        self.zapisy = 0
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.katalog_materialow = Path(self._tmp.name) / "materialy"
        self.katalog_danych = Path(self._tmp.name) / "dane"
        self.katalog_wynikow = Path(self._tmp.name) / "wyniki"

    def wczytaj_karte(self, klient):
        return self.karta

    def zapisz_karte(self, klient, karta):
        self.karta = karta
        self.zapisy += 1

    def inni_klienci(self, klient):
        return [("klinika-usmiech", "Klinika Uśmiech")]

    def fakty_zgloszen(self, grupa):
        return "\n".join(szkice.fakty_zgloszenia(z) for z in grupa)


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

    def test_wyslij_na_zgloszeniu_podrzednym_wysyla_mail_calej_grupy(self):
        """Człowiek nie musi wiedzieć, gdzie leży treść: etykieta na dowolnym zgłoszeniu grupy wysyła jej mail."""
        z1, z2 = zg(41, labels=("Konfiguracja", "Szkic gotowy")), zg(40, labels=("Konfiguracja", "Szkic gotowy", "Wyślij"))
        s = Srodowisko([z1, z2], {"RIN-41": [komentarz_szkicu(zgl=("RIN-41", "RIN-40"))],
                                  "RIN-40": [{"id": "z", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-41")}]})
        w = wy.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["wyslane"])
        self.assertEqual(len(s.poczta.wyslane), 1)
        for n in ("RIN-41", "RIN-40"):
            self.assertIn("Wysłano", s.linear.zgloszenia[n]["labels"])
            self.assertNotIn("Wyślij", s.linear.zgloszenia[n]["labels"])

    def test_wyslij_na_obu_zgloszeniach_grupy_to_jeden_mail_a_nie_blokada(self):
        z1, z2 = zg(41, labels=("Konfiguracja", "Szkic gotowy", "Wyślij")), zg(40, labels=("Konfiguracja", "Szkic gotowy", "Wyślij"))
        s = Srodowisko([z1, z2], {"RIN-41": [komentarz_szkicu(zgl=("RIN-41", "RIN-40"))],
                                  "RIN-40": [{"id": "z", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-41")}]})
        w = wy.uruchom(s)
        self.assertEqual(len(s.poczta.wyslane), 1)
        self.assertNotIn("Do weryfikacji", s.linear.zgloszenia["RIN-40"]["labels"])
        self.assertEqual([x["status"] for x in w], ["wyslane"])

    def test_wskazanie_na_nieistniejace_zgloszenie_glowne_blokuje(self):
        z = zg(40, labels=("Wyślij",))
        s = Srodowisko([z], {"RIN-40": [{"id": "z", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-99")}]})
        self.assertEqual(wy.uruchom(s)[0]["status"], "wstrzymane")
        self.assertEqual(s.poczta.wyslane, [])

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
        s = Srodowisko([zg(41)], claude=AtrapaClaude(json_szkic(temat="Godziny w sobotę")))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "szkic")
        self.assertIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertEqual(s.poczta.wyslane, [])
        self.assertEqual(s.slack.wiadomosci, [])
        p = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-41"]))
        self.assertEqual((p["do"], p["temat"]), ("Kasia Malinowska", "Godziny w sobotę"))

    def test_kilka_szkicow_klienta_z_jednego_dnia_to_jeden_mail_ze_wszystkimi_czesciami(self):
        z1, z2 = zg(41), zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia")
        s = Srodowisko([z2, z1], claude=claude_czesci(
            {"Sprawa: Godziny w sobotę": json_szkic("Dzień dobry, Kasia, sobota do 15:00.\nMarek Rewoliński"),
             "Sprawa: Godziny dzwonienia": json_szkic("Dzień dobry, Kasia, dzwonimy 9–19.\nMarek Rewoliński")},
            json_laczenia("Dzień dobry, Kasia,\n\n- sobota do 15:00\n- dzwonimy 9–19\n\nMarek Rewoliński")))
        w = szkice.uruchom(s)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["zgloszenia"], ["RIN-41", "RIN-40"], "najstarsze jako główne")
        self.assertEqual(len(s.claude.prompty), 3, "dwie części i jedno łączenie")
        glowny = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-41"]))
        self.assertEqual(glowny["zgloszenia"], ["RIN-41", "RIN-40"])
        self.assertIn("sobota do 15:00", glowny["tresc"])
        self.assertIn("dzwonimy 9–19", glowny["tresc"])
        self.assertEqual(wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-40"])), {"zbiorczy": "RIN-41"})

    def test_laczenie_ktore_gubi_czesc_konczy_sie_osobnymi_szkicami(self):
        z1, z2 = zg(41), zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia")
        s = Srodowisko([z1, z2], claude=claude_czesci(
            {"Sprawa: Godziny w sobotę": json_szkic("Dzień dobry, Kasia, sobota.\nMarek Rewoliński", "A"),
             "Sprawa: Godziny dzwonienia": json_szkic("Dzień dobry, Kasia, dzwonienie.\nMarek Rewoliński", "B")},
            json_laczenia("Dzień dobry, Kasia, tylko sobota.\nMarek Rewoliński", pomin=2)))
        w = szkice.uruchom(s)
        self.assertEqual([x["zgloszenia"] for x in w], [["RIN-41"], ["RIN-40"]], "nic nie ginie: każda część osobno")
        self.assertIn("dzwonienie", wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-40"]))["tresc"])

    def test_prompt_laczenia_zada_wszystkich_czesci(self):
        z1, z2 = zg(41), zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia")
        s = Srodowisko([z1, z2], claude=claude_czesci({"Sprawa: Godziny": json_szkic("Dzień dobry, Kasia, ok.\nMarek Rewoliński")},
                                                       json_laczenia("Dzień dobry, Kasia, ok.\nMarek Rewoliński")))
        szkice.uruchom(s)
        p = s.claude.prompty[-1]
        self.assertIn("WSZYSTKIE części", p)
        self.assertIn("CZĘŚĆ 1", p)
        self.assertIn("CZĘŚĆ 2", p)
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
        dobry = json_szkic()
        s = Srodowisko([zg(41)], claude=AtrapaClaude(zly, dobry))
        self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic")
        self.assertEqual(len(s.claude.prompty), 2)
        self.assertIn("ODRZUCONY", s.claude.prompty[1])
        self.assertNotIn("zamknęliśmy RIN-41", s.claude.prompty[1], "model nie dostaje treści odrzuconego szkicu")

    def test_dwa_zle_szkice_to_do_weryfikacji_bez_szkicu(self):
        zly = json_szkic("Dzień dobry, Kasia, zamknęliśmy RIN-41.")
        s = Srodowisko([zg(41)], claude=AtrapaClaude(zly))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "do_weryfikacji")
        self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
    def test_nieczytelna_odpowiedz_modelu_to_do_weryfikacji(self):
        s = Srodowisko([zg(41)], claude=AtrapaClaude("nie wiem"))
        self.assertEqual(szkice.uruchom(s)[0]["status"], "do_weryfikacji")
    def test_brak_potwierdzonego_kontaktu_to_do_weryfikacji(self):
        s = Srodowisko([zg(41)], karta={"klient": "x", "kontakty": [], "zakazy": []})
        self.assertEqual(szkice.uruchom(s)[0]["status"], "brak_kontaktu")
        self.assertEqual(s.claude.prompty, [], "bez kontaktu model nie jest pytany")

    def test_klinika_rin_65_bez_kontaktu_w_karcie_do_weryfikacji_z_powodem(self):
        z = zg(65, klient="klinika-usmiech", opis=OPIS_RIN65, tytul="Błędne godziny otwarcia Sopot w piątek", labels=("Konfiguracja", "Repo"))
        s = Srodowisko([z], karta={"klient": "Klinika Uśmiech", "zakazy": [], "kontakty": [], "otwarte_sprawy": {}})
        w = szkice.uruchom(s)[0]
        self.assertEqual((w["status"], w["powod"]), ("brak_kontaktu", "brak kontaktu w karcie"))
        self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-65"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-65"]["labels"])
        komentarz = next(k[2] for k in s.linear.zdarzenia if k[0] == "komentarz")
        self.assertIn("brak kontaktu w karcie", komentarz)
        self.assertEqual(s.claude.prompty, [], "model nie jest pytany")

    def test_odbiorca_to_kontakt_glowny_z_karty(self):
        self.assertEqual(szkice.wybierz_odbiorce(KARTA)["imie"], "Kasia Malinowska")

    def test_szkic_nie_powstaje_ponownie_gdy_juz_jest_i_nic_nowego(self):
        z = zg(41, labels=("Konfiguracja", "Szkic gotowy"))
        s = Srodowisko([z])
        self.assertEqual(szkice.uruchom(s), [])
        self.assertEqual(s.claude.prompty, [])

    def test_nowe_zgloszenie_dolacza_do_niewyslanego_szkicu_tego_dnia(self):
        z1 = zg(41, labels=("Konfiguracja", "Szkic gotowy"))
        z2 = zg(40, completed="2026-10-14T09:00:00Z", tytul="Godziny dzwonienia")
        s = Srodowisko([z1, z2], claude=claude_czesci({"Sprawa: Godziny": json_szkic("Dzień dobry, Kasia, ok.\nMarek Rewoliński")},
                                                       json_laczenia("Dzień dobry, Kasia, ok.\nMarek Rewoliński")))
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

    def test_stary_szkic_z_opisu_zgloszenia_nie_trafia_do_promptu(self):
        """Stały „Szkic dla klienta” z opisu zawierał „przesyłam ściągę”; model go przepisywał. Teraz go nie dostaje."""
        z = self._zaproszenie(opis=OPIS_ZAPROSZENIE + "\n\n## Szkic dla klienta (do wysłania przez człowieka)\n\n> Cześć Kasia, przesyłam ściągę.")
        s = Srodowisko([z])
        szkice.uruchom(s)
        self.assertNotIn("przesyłam ściągę", s.claude.prompty[0])
        self.assertNotIn("Wcześniejszy szkic", s.claude.prompty[0])
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


# ── placeholdery, łączenie gotowych z resztą, zaproszenie .ics ───────────────

OPIS_DECYZJA = (OPIS + "\n\n## Dlaczego człowiek\n\n- kosztuje pieniądze albo dotyczy cen i umów (słowo: „wycen”)\n"
                "- trafia do klienta (mail, przypomnienie, oferta): agent przygotowuje gotowy szkic")
OPIS_TYLKO_DO_KLIENTA = OPIS + "\n\n## Dlaczego człowiek\n\n- trafia do klienta (mail, przypomnienie, oferta): agent przygotowuje gotowy szkic"


class TestPlaceholdery(unittest.TestCase):

    FRAGMENTY = ["Cena wynosi [...] zł.", "Cena wynosi […] zł.", "Cena: uzupełnić po rozmowie.", "TODO: cena", "Cena XXX zł", "Cena ???",
                 "Wstaw tutaj cenę.", "Cena [do uzupełnienia] zł.", "Dzień dobry <imię>,"]

    def test_wysylka_nigdy_nie_wypuszcza_szkicu_z_miejscem_do_uzupelnienia(self):
        for fragment in self.FRAGMENTY:
            tresc = f"Dzień dobry, Kasia,\n\n{fragment}\n\nMarek Rewoliński"
            s, w = wyslij_jedno(tresc=tresc)
            self.assertEqual(w[0]["status"], "wstrzymane", fragment)
            self.assertIn("szkic wymaga uzupełnienia:", w[0]["powod"], fragment)
            self.assertEqual(s.poczta.wyslane, [], fragment)
            self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"], fragment)
            self.assertNotIn("Wyślij", s.linear.zgloszenia["RIN-41"]["labels"], fragment)

    def test_powod_zawiera_fragment_z_miejscem(self):
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasia,\n\nCena wynosi [...] zł.\n\nMarek Rewoliński")
        self.assertIn("[...]", w[0]["powod"])

    def test_zwykly_tekst_nie_jest_placeholderem(self):
        self.assertIsNone(wy.znajdz_placeholder("Temat", DOBRA, W))
        self.assertIsNone(wy.znajdz_placeholder("Godziny", "Dzień dobry, Kasia, w sobotę 9:00–15:00? Tak, do 15:00.", W))

    def test_szkic_z_placeholderem_trafia_do_weryfikacji_z_powodem_i_roboczym_tekstem(self):
        s = Srodowisko([zg(41)], claude=AtrapaClaude(json_szkic("Dzień dobry, Kasia,\n\nwycena: [...] zł.\n\nMarek Rewoliński")))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "do_weryfikacji")
        self.assertIn("szkic wymaga uzupełnienia: ", w["powod"])
        self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-41"]["labels"])
        self.assertIsNone(wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-41"])), "to nie jest szkic do wysłania")
        self.assertEqual(len(s.claude.prompty), 1, "placeholder nie jest powodem ponawiania")

    def test_gotowy_szkic_nie_jest_laczony_z_takim_ktory_wymaga_uzupelnienia(self):
        """RIN-46 miał same SMS-y i brakowało zaproszenia: gotowe idą razem, niegotowe osobno."""
        z1 = zg(51, tytul="Zaproszenie na spotkanie", completed="2026-10-14T06:00:00Z", stan="Todo")
        z2 = zg(52, tytul="Gotowa sprawa A", completed="2026-10-14T06:10:00Z")
        z3 = zg(53, tytul="Gotowa sprawa B", completed="2026-10-14T06:20:00Z")
        for z in (z1, z2, z3):
            z["createdAt"] = z["completedAt"]
        s = Srodowisko([z1, z2, z3], claude=claude_czesci(
            {"Sprawa: Zaproszenie": json_szkic("Dzień dobry, Kasia, wycena [...] zł.\nMarek Rewoliński"),
             "Sprawa: Gotowa sprawa A": json_szkic("Dzień dobry, Kasia, A gotowe.\nMarek Rewoliński"),
             "Sprawa: Gotowa sprawa B": json_szkic("Dzień dobry, Kasia, B gotowe.\nMarek Rewoliński")},
            json_laczenia("Dzień dobry, Kasia, A gotowe, B gotowe.\nMarek Rewoliński")))
        w = szkice.uruchom(s)
        self.assertEqual(sorted((x["status"], tuple(x["zgloszenia"])) for x in w),
                         [("do_weryfikacji", ("RIN-51",)), ("szkic", ("RIN-52", "RIN-53"))])
        merge_prompt = next(p for p in s.claude.prompty if "Połącz poniższe części" in p)
        self.assertNotIn("[...]", merge_prompt, "część do uzupełnienia nie trafia do łączenia")

    def test_zgloszenie_wymagajace_decyzji_czlowieka_idzie_osobno(self):
        z1 = zg(41, labels=("Konfiguracja", "Decyzja człowieka"), opis=OPIS_DECYZJA)
        z2 = zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia", opis=OPIS.replace("Godziny w sobotę do 15:00.", "Dzwonienie 9–19."))
        s = Srodowisko([z1, z2], claude=claude_czesci({"Sprawa: Godziny w sobotę": json_szkic("Dzień dobry, Kasia, A.\nMarek Rewoliński", "A"),
                                                       "Sprawa: Godziny dzwonienia": json_szkic("Dzień dobry, Kasia, B.\nMarek Rewoliński", "B")}))
        w = szkice.uruchom(s)
        self.assertEqual(sorted(tuple(x["zgloszenia"]) for x in w), [("RIN-40",), ("RIN-41",)], "bez łączenia")
        self.assertFalse(any("Połącz poniższe części" in p for p in s.claude.prompty))

    def test_samo_do_klienta_nie_jest_decyzja_i_laczy_sie(self):
        z1 = zg(41, labels=("Konfiguracja", "Decyzja człowieka"), opis=OPIS_TYLKO_DO_KLIENTA)
        z2 = zg(40, completed="2026-10-14T08:30:00Z", tytul="Godziny dzwonienia", opis=OPIS.replace("Godziny w sobotę do 15:00.", "Dzwonienie 9–19."))
        s = Srodowisko([z1, z2], claude=claude_czesci({"Sprawa: Godziny": json_szkic("Dzień dobry, Kasia, ok.\nMarek Rewoliński")},
                                                       json_laczenia("Dzień dobry, Kasia, ok.\nMarek Rewoliński")))
        w = szkice.uruchom(s)
        self.assertEqual([tuple(x["zgloszenia"]) for x in w], [("RIN-41", "RIN-40")])

    def test_wymaga_decyzji_etykieta_zakazu_zawsze(self):
        self.assertTrue(szkice.wymaga_decyzji(zg(1, labels=("Zablokowane przez zakaz",)), Z))
        self.assertFalse(szkice.wymaga_decyzji(zg(1, labels=("Konfiguracja",)), Z))


class TestZaproszenieICS(unittest.TestCase):

    TYTUL = "Potwierdzenie spotkania Marek–Paweł (15.10, 10:00, Toruń)"
    SPOTKANIE = {"data": "2026-10-15", "godzina": "10:00", "czas_min": 60, "miejsce": "Toruń", "tytul": "Spotkanie Marek–Paweł–Kasia"}
    TRESC = "Dzień dobry, Kasia,\n\nzapraszam na czwartek 15.10 o 10:00. Zaproszenie kalendarzowe jest w załączniku.\n\nMarek Rewoliński"

    def _z(self, **kw):
        return zg(51, **{"tytul": self.TYTUL, "opis": OPIS_ZAPROSZENIE, "stan": "Todo", "labels": ("Decyzja człowieka",), **kw})

    def test_szkic_z_poprawnym_spotkaniem_ma_dane_w_komentarzu(self):
        s = Srodowisko([self._z()], claude=AtrapaClaude(json_szkic(self.TRESC, "Zaproszenie", self.SPOTKANIE)))
        w = szkice.uruchom(s)[0]
        self.assertEqual((w["status"], w["zaproszenie"]), ("szkic", True))
        p = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-51"]))
        self.assertEqual(p["spotkanie"]["data"], "2026-10-15")
        self.assertEqual(p["spotkanie"]["godzina"], "10:00")

    def test_wysylka_dolacza_ics_z_poprawna_godzina_utc(self):
        z = self._z(labels=("Wyślij", "Szkic gotowy"))
        k = {"id": "c", "createdAt": "2026-10-14T07:30:00Z",
             "body": wy.format_komentarza_szkicu("Kasia Malinowska", "Zaproszenie", self.TRESC, ["RIN-51"], self.SPOTKANIE)}
        s = Srodowisko([z], {"RIN-51": [k]})
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wyslane")
        ics = s.poczta.wyslane[0]["ics"]
        self.assertIn("METHOD:REQUEST", ics)
        self.assertIn("DTSTART:20261015T080000Z", ics, "10:00 czasu polskiego (CEST) to 08:00 UTC")
        self.assertIn("DTEND:20261015T090000Z", ics)
        self.assertIn("ATTENDEE;CN=Kasia Malinowska;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:kasia@autotama.pl", ics)
        self.assertIn("SUMMARY:Spotkanie Marek–Paweł–Kasia", ics)
        self.assertTrue(s.karta["historia_wysylek"][0]["zaproszenie_ics"])

    def test_spotkanie_z_wymyslona_data_jest_odrzucone(self):
        sp = {**self.SPOTKANIE, "data": "2026-10-16"}                  # w zgłoszeniu jest 15.10
        s = Srodowisko([self._z()], claude=AtrapaClaude(json_szkic(self.TRESC, "Zaproszenie", sp)))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "do_weryfikacji")
        self.assertIn("nie wynika z danych zgłoszenia", w["powod"])

    def test_spotkanie_z_przeszlosci_albo_zlym_formatem_jest_odrzucone(self):
        dzis = datetime(2026, 10, 14).date()
        self.assertIsNone(wy.waliduj_spotkanie({**self.SPOTKANIE, "data": "2026-10-13"}, "13.10 10:00", dzis, W)[0])
        self.assertIsNone(wy.waliduj_spotkanie({**self.SPOTKANIE, "godzina": "25:00"}, "15.10 25:00", dzis, W)[0])
        self.assertIsNone(wy.waliduj_spotkanie({"data": "jutro", "godzina": "10:00"}, "15.10 10:00", dzis, W)[0])
        self.assertIsNotNone(wy.waliduj_spotkanie(self.SPOTKANIE, "15.10, 10:00", dzis, W)[0])

    def test_tresc_mowiaca_o_zaproszeniu_bez_ics_jest_odrzucana_przy_pisaniu(self):
        z = self._z(tytul="Potwierdzenie spotkania", opis=OPIS_ZAPROSZENIE.replace("czwartek 15.10 o 10:00", "czwartek"))
        zly = json_szkic("Dzień dobry, Kasia,\n\nwysyłam zaproszenie na czwartek.\n\nMarek Rewoliński")
        s = Srodowisko([z], claude=AtrapaClaude(zly))
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "do_weryfikacji")
        self.assertIn("obiecuje załącznik albo zaproszenie", w["powod"])
        self.assertEqual(len(s.claude.prompty), 2, "jedna ponowna próba z listą naruszeń")

    def test_ponowna_proba_bez_obietnicy_zaproszenia_przechodzi(self):
        z = self._z(tytul="Potwierdzenie spotkania", opis=OPIS_ZAPROSZENIE.replace("czwartek 15.10 o 10:00", "czwartek"))
        zly = json_szkic("Dzień dobry, Kasia,\n\nwysyłam zaproszenie na czwartek.\n\nMarek Rewoliński")
        dobry = json_szkic("Dzień dobry, Kasia,\n\ntermin spotkania w czwartek jest potwierdzony.\n\nMarek Rewoliński")
        s = Srodowisko([z], claude=AtrapaClaude(zly, dobry))
        w = szkice.uruchom(s)[0]
        self.assertEqual((w["status"], w["zaproszenie"]), ("szkic", False))

    def test_wysylka_blokuje_obietnice_zalacznika_bez_ics(self):
        for tresc in ("Dzień dobry, Kasia, wysyłam zaproszenie.\nMarek Rewoliński", "Dzień dobry, Kasia, w załączniku termin.\nMarek Rewoliński",
                      "Dzień dobry, Kasia, w załączeniu zaproszenie.\nMarek Rewoliński"):
            s, w = wyslij_jedno(tresc=tresc)
            self.assertEqual(w[0]["status"], "wstrzymane", tresc)
            self.assertIn("obiecuje załącznik", w[0]["powod"])
            self.assertEqual(s.poczta.wyslane, [])

    def test_przesylam_ściągę_bez_zalacznika_jest_blokowane(self):
        """Szkic z RIN-47 mówił „przesyłam ją”, choć żadnego załącznika nie ma."""
        s, w = wyslij_jedno(tresc="Dzień dobry, Kasiu,\n\nprzesyłam ściągę statusów.\n\nMarek Rewoliński")
        self.assertEqual(w[0]["status"], "wstrzymane")
        s2, w2 = wyslij_jedno(tresc="Dzień dobry, Kasiu,\n\nściągę wyślę przed urlopem.\n\nMarek Rewoliński")
        self.assertEqual(w2[0]["status"], "wyslane", "czas przyszły z terminem jest w porządku")

    def test_ics_ma_tylko_potwierdzonego_odbiorce_z_karty(self):
        ics = wy.zbuduj_ics({**self.SPOTKANIE}, "marek@rinvo.test", "kasia@autotama.pl", "Kasia Malinowska", SROD, W)
        self.assertEqual(ics.count("ATTENDEE"), 1)
        self.assertNotIn("pawel@", ics)

    def test_parsowanie_szkicu_ze_spotkaniem_okragle(self):
        k = {"id": "c", "createdAt": "2026-10-14T07:30:00Z", "body": wy.format_komentarza_szkicu("Kasia Malinowska", "T", DOBRA, ["RIN-51"], self.SPOTKANIE)}
        self.assertEqual(wy.parsuj_szkic([k])["spotkanie"], self.SPOTKANIE)
        self.assertIsNone(wy.parsuj_szkic([komentarz_szkicu()])["spotkanie"])


# ── materiały, potwierdzenie przez klienta, wycofywanie szkiców ──────────────

import json as _json
import materialy as mat

OPIS_SCIAGA = ("## Cel\n\nDać Kasi ściągę statusów dla handlowców.\n\n## Kontekst\n\nŚciąga ze statusów.\n\n> Ściągę wyślę ci przed urlopem.\n\n"
               "## Kryteria akceptacji\n\n- [ ] Ściąga mieści się na jednej stronie\n\n## Czego nie ruszać\n\n- Zakaz Z4: x\n\n## Źródło\n\n`x`")
MATERIAL_OK = _json.dumps({"tytul": "Ściąga statusów", "tresc": "# Ściąga statusów\n\n## Zainteresowany\n\n- osoba po pełnej rozmowie, która chce rozmawiać z doradcą\n",
                           "luki": []}, ensure_ascii=False)
MATERIAL_LUKI = _json.dumps({"tytul": "Ściąga statusów", "tresc": "# Ściąga statusów\n\n## Zainteresowany\n\n- po pełnej rozmowie\n\n## Niezweryfikowany\n\n- [do potwierdzenia: co znaczy ten status]\n",
                             "luki": ["znaczenie statusu „niezweryfikowany”"]}, ensure_ascii=False)
KARTA_SCIAGA = {**KARTA, "otwarte_sprawy": {"sciga-statusow": {"identifier": "RIN-47", "zrodla": []}},
                "zamkniete_sprawy": {"adres-wloclawek": {"identifier": "RIN-39", "zrodla": [], "status_koncowy": "zamknieta"}}}


def claude_material_i_mail(material, mail=None):
    """Atrapa: prompt materiału dostaje JSON materiału, prompt maila JSON maila."""
    mail = mail or json_szkic("Dzień dobry, Kasiu,\n\nściąga statusów jest w załączniku.\n\nMarek Rewoliński")
    k = AtrapaClaude("")
    k.zapytaj = lambda prompt: (k.prompty.append(prompt), material if "Przygotuj dla klienta materiał" in prompt else mail)[1]
    return k


class TestMaterialy(unittest.TestCase):

    def _z(self, **kw):
        return zg(47, **{"tytul": "Wysłać Kasi ściągę statusów przed urlopem", "opis": OPIS_SCIAGA, "stan": "Todo", "labels": ("Zadanie", "Decyzja człowieka"), **kw})

    def _s(self, material=MATERIAL_OK, **kw):
        return Srodowisko([self._z(**kw.pop("z", {}))], karta=KARTA_SCIAGA, claude=claude_material_i_mail(material, kw.pop("mail", None)), **kw)

    def test_rodzaj_materialu(self):
        self.assertEqual(mat.rodzaj_materialu(self._z(), Z), "sciaga")
        self.assertEqual(mat.rodzaj_materialu(zg(1, tytul="Zestawienie wyników testu"), Z), "zestawienie")
        self.assertEqual(mat.rodzaj_materialu(zg(1, tytul="Notatka ze spotkania dla klienta"), Z), "notatka")
        self.assertIsNone(mat.rodzaj_materialu(zg(1, tytul="Notatka przed spotkaniem z Pawłem"), Z), "notatki wewnętrzne to nie materiał dla klienta")
        self.assertIsNone(mat.rodzaj_materialu(zg(1, tytul="Godziny w sobotę"), Z))

    def test_material_powstaje_przed_szkicem_i_jest_zalaczony(self):
        s = self._s()
        w = szkice.uruchom(s)[0]
        self.assertEqual((w["status"], len(w["zalaczniki"])), ("szkic", 1))
        md, pdf, meta = mat.sciezki_materialu("auto-tama", self._z(), s.katalog_materialow)
        self.assertTrue(md.exists() and pdf.exists())
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"), "to prawdziwy PDF")
        self.assertIn("Zainteresowany", md.read_text(encoding="utf-8"))
        self.assertIn("rin-47-", str(pdf))
        # model dostał najpierw prośbę o materiał, dopiero potem o mail, i widzi treść załącznika
        self.assertIn("Przygotuj dla klienta materiał", s.claude.prompty[0])
        self.assertIn("ZAŁĄCZNIK", s.claude.prompty[1])
        self.assertIn("Zainteresowany", s.claude.prompty[1])
        p = wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-47"]))
        self.assertEqual(p["zalaczniki"], [str(pdf)])

    def test_material_z_lukami_nie_dostaje_szkicu_tylko_do_weryfikacji_z_lista_brakow(self):
        s = self._s(MATERIAL_LUKI)
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "do_weryfikacji")
        self.assertIn("materiał wymaga uzupełnienia", w["powod"])
        self.assertIn("niezweryfikowany", w["powod"])
        self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-47"]["labels"])
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-47"]["labels"])
        self.assertEqual(len(s.claude.prompty), 1, "mail w ogóle nie jest pisany")

    def test_material_pytany_o_fakty_nie_zgaduje(self):
        s = self._s()
        szkice.uruchom(s)
        p = s.claude.prompty[0]
        self.assertIn("WYŁĄCZNIE faktów", p)
        self.assertIn("[do potwierdzenia", p)
        self.assertIn("Ściągę wyślę ci przed urlopem", p, "fakty ze zgłoszenia")

    def test_istniejacy_material_z_tymi_samymi_faktami_nie_wola_modelu_ponownie(self):
        s = self._s()
        szkice.uruchom(s)
        liczba = len(s.claude.prompty)
        z = s.linear.zgloszenia["RIN-47"]
        z["labels"] = [l for l in z["labels"] if l != "Szkic gotowy"]
        szkice.uruchom(s)
        nowe = s.claude.prompty[liczba:]
        self.assertFalse(any("Przygotuj dla klienta materiał" in p for p in nowe))

    def test_zalozenie_demo_trafia_do_faktow_i_jest_oznaczone_w_materiale(self):
        karta = {**KARTA_SCIAGA, "zalozenia_demo": [{"dotyczy": "sciaga-statusow", "temat": "Status „niezweryfikowany”",
                                                    "tresc": "agent nie dodzwonił się albo rozmowa nie potwierdziła danych kontaktowych"},
                                                   {"dotyczy": "inna-sprawa", "temat": "Obce", "tresc": "nie dla tej sprawy"}]}
        karta["otwarte_sprawy"] = {"sciaga-statusow": {"identifier": "RIN-47", "zrodla": []}}
        s = Srodowisko([self._z()], karta=karta, claude=claude_material_i_mail(MATERIAL_OK))
        self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic")
        p = s.claude.prompty[0]
        self.assertIn("ZAŁOŻENIA DEMO", p)
        self.assertIn("agent nie dodzwonił się albo rozmowa nie potwierdziła danych kontaktowych", p)
        self.assertNotIn("nie dla tej sprawy", p)
        md, _, _ = mat.sciezki_materialu("auto-tama", self._z(), s.katalog_materialow)
        tekst = md.read_text(encoding="utf-8")
        self.assertIn("## Założenia demo", tekst)
        self.assertIn("(założenie demo)", tekst)
        self.assertNotIn("nie dla tej sprawy", tekst)

    def test_zmiana_zalozen_odswieza_material(self):
        karta = {**KARTA_SCIAGA, "otwarte_sprawy": {"sciaga-statusow": {"identifier": "RIN-47", "zrodla": []}}}
        s = Srodowisko([self._z()], karta=karta, claude=claude_material_i_mail(MATERIAL_OK))
        szkice.uruchom(s)
        z = s.linear.zgloszenia["RIN-47"]
        z["labels"] = [l for l in z["labels"] if l != "Szkic gotowy"]
        s.karta = {**karta, "zalozenia_demo": [{"dotyczy": "sciaga-statusow", "temat": "Nowy", "tresc": "nowa definicja"}]}
        szkice.uruchom(s)
        self.assertEqual(sum("Przygotuj dla klienta materiał" in p for p in s.claude.prompty), 2, "inne fakty = nowy materiał")

    def test_karta_auto_tama_ma_zalozenie_niezweryfikowany_oznaczone_jako_demo(self):
        k = _json.loads((Path(__file__).parent.parent / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        z = next(x for x in k["zalozenia_demo"] if "niezweryfikowany" in x["temat"])
        self.assertEqual(z["tresc"], "agent nie dodzwonił się albo rozmowa nie potwierdziła danych kontaktowych")
        self.assertEqual(z["dotyczy"], "sciga-statusow")

    def test_stary_szkic_ze_sciaga_bez_materialu_jest_wycofany_i_pisany_od_nowa(self):
        """RIN-47: szkic powstał, zanim istniał materiał, i obiecywał ściągę, której nie było."""
        z = self._z(labels=("Zadanie", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-47": [komentarz_szkicu(zgl=("RIN-47",), tresc="Dzień dobry, Kasiu, przesyłam ściągę.\nMarek Rewoliński")]},
                       karta=KARTA_SCIAGA, claude=claude_material_i_mail(MATERIAL_OK))
        w = szkice.uruchom(s)[0]
        self.assertEqual((w["status"], len(w["zalaczniki"])), ("szkic", 1))
        kom = sorted(s.linear.komentarze(s.linear.zgloszenia["RIN-47"]), key=lambda k: k["createdAt"])
        self.assertTrue(kom[0]["body"].startswith("_Szkic wycofany"))
        self.assertNotIn("przesyłam ściągę", wy.parsuj_szkic(kom)["tresc"])

    def test_reczna_poprawka_materialu_usuwa_luki_i_odswieza_pdf(self):
        s = self._s(MATERIAL_LUKI)
        self.assertEqual(szkice.uruchom(s)[0]["status"], "do_weryfikacji")
        md, pdf, meta = mat.sciezki_materialu("auto-tama", self._z(), s.katalog_materialow)
        md.write_text("# Ściąga statusów\n\n## Niezweryfikowany\n\n- status dla kontaktów bez potwierdzenia numeru\n", encoding="utf-8")
        m = _json.loads(meta.read_text(encoding="utf-8"))
        m["reczny"] = True
        meta.write_text(_json.dumps(m), encoding="utf-8")
        z = s.linear.zgloszenia["RIN-47"]
        z["labels"] = [l for l in z["labels"] if l != "Do weryfikacji"]
        w = szkice.uruchom(s)[0]
        self.assertEqual(w["status"], "szkic", "poprawiony ręcznie materiał jest gotowy")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))

    def test_prompt_materialu_kaze_trzymac_sie_tematu_i_nie_mieszac_faktow(self):
        s = self._s()
        szkice.uruchom(s)
        p = s.claude.prompty[0]
        self.assertIn("Trzymaj się tematu zgłoszenia", p)
        self.assertIn("NIE dodawaj sekcji", p)
        self.assertIn("Opisuj TYLKO elementy, o które prosi klient", p)

    def test_zestawienie_czeka_na_dane_bez_materialu_i_bez_szkicu(self):
        z = zg(73, tytul="W piątek wysłać Kasi zestawienie wyników testu wstępu", stan="Todo", labels=("Zadanie", "Decyzja człowieka"),
               opis=OPIS.replace("Godziny w sobotę do 15:00.", "Zestawienie wyników testu wstępu."))
        karta = {**KARTA, "otwarte_sprawy": {"zestawienie-wynikow-wstepu": {"identifier": "RIN-73", "zrodla": []}}}
        s = Srodowisko([z], karta=karta)
        w = szkice.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["czeka_na_dane"])
        self.assertIn("ops/dane/auto-tama/zestawienie-wynikow-wstepu", w[0]["powod"])
        self.assertEqual(s.claude.prompty, [], "model nie jest pytany")
        self.assertEqual(s.linear.zdarzenia, [], "żadnych zmian w Linearze")
        self.assertFalse(s.katalog_materialow.exists())

    def test_zestawienie_z_danymi_jest_tworzone(self):
        z = zg(73, tytul="Zestawienie wyników testu wstępu", stan="Todo", labels=("Zadanie",), opis=OPIS)
        karta = {**KARTA, "otwarte_sprawy": {"zestawienie-wynikow-wstepu": {"identifier": "RIN-73", "zrodla": []}}}
        s = Srodowisko([z], karta=karta, claude=claude_material_i_mail(MATERIAL_OK))
        (s.katalog_danych / "auto-tama").mkdir(parents=True)
        (s.katalog_danych / "auto-tama" / "zestawienie-wynikow-wstepu.csv").write_text("wersja,pelne\nA,10\n", encoding="utf-8")
        self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic")

    def test_zestawienie_ktore_mialo_szkic_traci_go_gdy_brak_danych(self):
        z = zg(73, tytul="Zestawienie wyników testu wstępu", stan="Todo", labels=("Zadanie", "Szkic gotowy"), opis=OPIS)
        karta = {**KARTA, "otwarte_sprawy": {"zestawienie-wynikow-wstepu": {"identifier": "RIN-73", "zrodla": []}}}
        s = Srodowisko([z], {"RIN-73": [komentarz_szkicu(zgl=("RIN-73",)), {"id": "p", "createdAt": "2026-10-14T07:00:00Z", "body": wy.format_komentarza_zbiorczego("RIN-46")}]}, karta=karta)
        szkice.uruchom(s)
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-73"]["labels"])
        self.assertIsNone(wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-73"])), "stare szkice wycofane")
        self.assertTrue(all(k["body"].startswith("_Szkic wycofany") for k in s.linear.komentarze(s.linear.zgloszenia["RIN-73"])))


class TestPotwierdzoneUKlienta(unittest.TestCase):

    def _wyniki(self, tmp, nowy_status="zamknieta", pewnosc="wysoka"):
        d = Path(tmp) / "auto-tama" / "2026-10-13-call"
        d.mkdir(parents=True)
        (d / "wynik.json").write_text(_json.dumps({"aktualizacje_spraw": [{"klucz_sprawy": "adres-wloclawek", "nowy_status": nowy_status,
                                                                           "cytat": "Adres we Włocławku działa, puściłam sobie test.", "pewnosc": pewnosc}]}), encoding="utf-8")

    def test_sprawa_potwierdzona_przez_klienta_nie_dostaje_szkicu(self):
        z = zg(39, tytul="Nieaktualny adres salonu Włocławek", labels=("Konfiguracja",), opis=OPIS.replace("Napisz mi", "Napisz mi"))
        s = Srodowisko([z], karta=KARTA_SCIAGA)
        self._wyniki(s.katalog_wynikow)
        w = szkice.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["pominiete"])
        self.assertIn("klient sam potwierdził", w[0]["powod"])
        self.assertIn("Adres we Włocławku działa", w[0]["powod"])
        self.assertEqual(s.claude.prompty, [])

    def test_potwierdzenie_dziala_gdy_prosba_o_informacje_jest_tylko_w_starszych_cytatach(self):
        """Regresja: odfiltrowanie nie widziało cytatów ze starszych wyników, więc RIN-39 dostawał szkic mimo potwierdzenia."""
        z = zg(39, tytul="Nieaktualny adres salonu Włocławek", labels=("Konfiguracja",), opis=OPIS.replace("> Napisz mi, jak będzie poprawione.", "> Dzięki."))
        s = Srodowisko([z], karta=KARTA_SCIAGA, claude=AtrapaClaude(json_szkic()))
        s.cytaty_zrodlowe = lambda zgl: ["Napisz tylko, jak będzie zrobione."]
        self._wyniki(s.katalog_wynikow)
        w = szkice.uruchom(s)
        self.assertEqual([x["status"] for x in w], ["pominiete"])
        self.assertEqual(s.claude.prompty, [])

    def test_rin_39_traci_istniejacy_szkic(self):
        z = zg(39, tytul="Nieaktualny adres salonu Włocławek", labels=("Konfiguracja", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-39": [komentarz_szkicu(zgl=("RIN-39", "RIN-73"))]}, karta=KARTA_SCIAGA)
        self._wyniki(s.katalog_wynikow)
        szkice.uruchom(s)
        self.assertNotIn("Szkic gotowy", s.linear.zgloszenia["RIN-39"]["labels"])
        self.assertIsNone(wy.parsuj_szkic(s.linear.komentarze(s.linear.zgloszenia["RIN-39"])))

    def test_niepewne_potwierdzenie_albo_inny_status_nie_blokuje(self):
        for status, pewnosc in (("zrob_teraz", "wysoka"), ("zamknieta", "niska")):
            z = zg(39, tytul="Nieaktualny adres", labels=("Konfiguracja",))
            s = Srodowisko([z], karta=KARTA_SCIAGA, claude=AtrapaClaude(json_szkic()))
            self._wyniki(s.katalog_wynikow, status, pewnosc)
            self.assertEqual(szkice.uruchom(s)[0]["status"], "szkic", (status, pewnosc))

    def test_potwierdzone_przez_klienta_na_prawdziwych_wynikach_rin_39(self):
        import os
        root = Path(__file__).parent.parent
        k = _json.loads((root / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        cwd = os.getcwd()
        os.chdir(root)
        try:
            self.assertIn("Adres we Włocławku działa", mat.potwierdzone_przez_klienta("auto-tama", k, "RIN-39") or "")
            self.assertIsNone(mat.potwierdzone_przez_klienta("auto-tama", k, "RIN-47"))
        finally:
            os.chdir(cwd)


class TestWycofywanieSzkicow(unittest.TestCase):

    def test_nowy_szkic_zastepuje_stare_komentarze(self):
        z = zg(41, labels=("Konfiguracja",))
        s = Srodowisko([z], {"RIN-41": [komentarz_szkicu(tresc="Dzień dobry, stara wersja z przesyłam ściągę\nMarek Rewoliński")]},
                       claude=AtrapaClaude(json_szkic("Dzień dobry, Kasiu, nowa wersja.\nMarek Rewoliński")))
        szkice.uruchom(s)
        kom = sorted(s.linear.komentarze(s.linear.zgloszenia["RIN-41"]), key=lambda k: k["createdAt"])
        self.assertTrue(kom[0]["body"].startswith("_Szkic wycofany: zastąpiony nowszą wersją"))
        self.assertNotIn("przesyłam", kom[0]["body"], "stara treść znika z Lineara")
        self.assertIn("nowa wersja", wy.parsuj_szkic(kom)["tresc"])

    def test_stary_szkic_z_obietnica_ktorej_nie_da_sie_spelnic_nie_zostaje_do_wyslania(self):
        z = zg(47, labels=("Konfiguracja", "Wyślij", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-47": [komentarz_szkicu(zgl=("RIN-47",), tresc="Dzień dobry, Kasiu, przesyłam ściągę statusów.\nMarek Rewoliński")]})
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane", "wykrywacz obietnic blokuje taki szkic")
        self.assertEqual(s.poczta.wyslane, [])


class TestZalacznikiWysylki(unittest.TestCase):

    def _s(self, tresc, sciezki, tworz=True, md="# Ściąga\n\n- punkt\n"):
        z = zg(47, labels=("Konfiguracja", "Wyślij", "Szkic gotowy"))
        s = Srodowisko([z], {"RIN-47": [{"id": "c", "createdAt": "2026-10-14T07:30:00Z",
                                        "body": wy.format_komentarza_szkicu("Kasia Malinowska", "Ściąga", tresc, ["RIN-47"], None, sciezki)}]})
        if tworz:
            kat = s.katalog_materialow / "auto-tama"
            kat.mkdir(parents=True)
            (kat / "sciaga.pdf").write_bytes(b"%PDF-1.4 test")
            (kat / "sciaga.md").write_text(md, encoding="utf-8")
        return s

    def test_zalacznik_jest_wysylany_a_tresc_moze_o_nim_mowic(self):
        s = self._s("Dzień dobry, Kasiu, ściąga jest w załączniku.\nMarek Rewoliński", [])
        s.linear.kom["RIN-47"][0]["body"] = wy.format_komentarza_szkicu("Kasia Malinowska", "Ściąga", "Dzień dobry, Kasiu, ściąga jest w załączniku.\nMarek Rewoliński",
                                                                       ["RIN-47"], None, [str(s.katalog_materialow / "auto-tama" / "sciaga.pdf")])
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wyslane")
        self.assertEqual(s.poczta.wyslane[0]["zalaczniki"], [("sciaga.pdf", b"%PDF-1.4 test")])
        self.assertEqual(s.karta["historia_wysylek"][0]["zalaczniki"], ["sciaga.pdf"])

    def test_zalacznik_spoza_katalogu_materialow_klienta_blokuje(self):
        for sciezka in ("/etc/passwd.pdf", "ops/materialy/inny-klient/x.pdf", "ops/materialy/auto-tama/../../../.env.pdf", "sciaga.txt"):
            s = self._s("Dzień dobry, Kasiu, ściąga w załączniku.\nMarek Rewoliński", [sciezka], tworz=False)
            w = wy.uruchom(s)
            self.assertEqual(w[0]["status"], "wstrzymane", sciezka)
            self.assertEqual(s.poczta.wyslane, [])

    def test_brakujacy_plik_blokuje(self):
        s = self._s("Dzień dobry, Kasiu, ściąga w załączniku.\nMarek Rewoliński", [], tworz=False)
        s.linear.kom["RIN-47"][0]["body"] = wy.format_komentarza_szkicu("Kasia Malinowska", "T", "Dzień dobry, Kasiu, ściąga w załączniku.\nMarek Rewoliński", ["RIN-47"], None,
                                                                       [str(s.katalog_materialow / "auto-tama" / "brak.pdf")])
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("nie istnieje", w[0]["powod"])

    def test_material_z_luka_towarzyszacy_zalacznikowi_blokuje_wysylke(self):
        s = self._s("Dzień dobry, Kasiu, ściąga w załączniku.\nMarek Rewoliński", [], md="# Ściąga\n\n- [do potwierdzenia: status]\n")
        s.linear.kom["RIN-47"][0]["body"] = wy.format_komentarza_szkicu("Kasia Malinowska", "T", "Dzień dobry, Kasiu, ściąga w załączniku.\nMarek Rewoliński", ["RIN-47"], None,
                                                                       [str(s.katalog_materialow / "auto-tama" / "sciaga.pdf")])
        w = wy.uruchom(s)
        self.assertEqual(w[0]["status"], "wstrzymane")
        self.assertIn("wymaga uzupełnienia", w[0]["powod"])
        self.assertEqual(s.poczta.wyslane, [])

    def test_obietnica_zalacznika_bez_pliku_nadal_blokuje(self):
        s = self._s("Dzień dobry, Kasiu, przesyłam ściągę.\nMarek Rewoliński", [], tworz=False)
        self.assertEqual(wy.uruchom(s)[0]["status"], "wstrzymane")


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

    def test_workflow_agenta_zapisuje_materialy_i_ma_pdf(self):
        t = (Path(__file__).parent.parent / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertIn("fpdf2", t)
        self.assertIn("fonts-dejavu-core", t)
        self.assertIn("git add -A -- ops/materialy", t)
        self.assertIn("contents: write", t)

    def test_agent_nie_dostaje_hasla_do_poczty(self):
        t = (Path(__file__).parent.parent / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertNotIn("GMAIL_APP_PASSWORD", t)


if __name__ == "__main__":
    unittest.main(verbosity=1)
