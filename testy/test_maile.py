#!/usr/bin/env python3
"""test_maile.py – testy offline źródła „maile” na przykładowych plikach .eml (testy/maile/).

Bez sieci, bez Gmaila i bez modelu. Uruchomienie:
  python3 testy/test_maile.py
"""

import copy
import io
import contextlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import maile
from linear_sync import process_aktualizacje, sprawdz_uprawnienia, ustal_zrodlo, wymagani_decydenci

EML = Path(__file__).parent / "maile"

KASIA = "mateuszrembecki1@gmail.com"


def karta_testowa():
    return {
        "klient": "auto-tama",
        "decydenci": [{"imie": "Kasia Malinowska", "rola": "BDC, kontakt główny"},
                      {"imie": "Paweł", "rola": "przełożony Kasi, decyduje o markach i budżecie"}],
        "kontakty": [
            {"imie": "Kasia Malinowska", "email": KASIA, "rola": "BDC", "zakres_decyzji": "zakazy",
             "potwierdzony": True},
            {"imie": "Paweł", "email": "pawel@autotama.pl", "rola": "przełożony", "zakres_decyzji": "marki",
             "potwierdzony": True},
            {"imie": "Nowy Nadawca", "email": "nowy@autotama.pl", "rola": "nowy", "zakres_decyzji": "brak",
             "potwierdzony": False, "status": "nowy, bez prawa decyzji"},
        ],
        # wp.pl wpisane przez pomyłkę jako domena klienta: kod ma je zignorować
        "domeny": ["autotama.pl", "wp.pl"],
        "decyzje_zastrzezone": [{
            "opis": "Opel: decyduje Kasia, nie Paweł", "zastrzezone_dla": "Kasia Malinowska",
            "zakazy": ["Z4"], "klucze_spraw": ["decyzja-opel-stara-baza"]}],
        "zakazy": [{"id": "Z4", "tytul": "Nie włączać Opla", "cytat": ["Opla nie ruszam"]},
                   {"id": "Z8", "tytul": "Nie pisać do Oli", "cytat": ["do Oli nie piszę"]}],
        "otwarte_sprawy": {
            "swieze-leady": {"linear_id": "x", "identifier": "RIN-49", "url": "u", "tytul": "Plik",
                             "zrodla": ["ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md"]},
            "decyzja-opel-stara-baza": {
                "linear_id": "y", "identifier": "RIN-75", "url": "u", "tytul": "Opel",
                "zrodla": ["ops/transkrypcje/auto-tama/2026-10-06-call-statusowy.md"]},
        },
    }


class FakeSkrzynka:
    """Skrzynka z plików .eml. Zapisuje, dla których maili pobrano PEŁNĄ treść."""

    def __init__(self, nazwy, zmien_id=None):
        self.pliki = {n: (EML / n).read_bytes() for n in nazwy}
        for n, nowe_id in (zmien_id or {}).items():
            self.pliki[n] = re.sub(rb"Message-ID: <[^>]+>", b"Message-ID: <" + nowe_id.encode() + b">",
                                   self.pliki[n])
        self.pobrane = []

    def uids(self):
        return sorted(self.pliki)

    def naglowki(self, uid):
        return self.pliki[uid].split(b"\n\n", 1)[0]

    def tresc(self, uid):
        self.pobrane.append(uid)
        return self.pliki[uid]


def nowy_rejestr(**extra):
    r = {"przetworzone": {}, "oczekujace": {}, "nieznani": {}}
    r.update(extra)
    return r


def uruchom(skrzynka, karty=None, rejestr=None, katalog=None, dzis="2026-10-14"):
    karty = karty if karty is not None else {"auto-tama": karta_testowa()}
    rejestr = rejestr if rejestr is not None else nowy_rejestr()
    slack = []
    wynik = maile.przetworz_skrzynke(skrzynka, karty, rejestr, slack.append, dzis, katalog)
    return wynik, karty, rejestr, slack


class TestNieznanyNadawca(unittest.TestCase):

    def test_nieznany_nadawca_pominiety_bez_pobierania_tresci(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(["od-nieznanego.eml", "od-ogolnej-domeny.eml"])
            wynik, _, _, slack = uruchom(sk, katalog=Path(tmp))
            self.assertEqual(wynik["nowe"], [])
            self.assertEqual(wynik["nieznani"], 2)
            self.assertEqual(sk.pobrane, [], "od nieznanego nadawcy nie wolno pobierać treści")
            self.assertEqual(list(Path(tmp).rglob("*.md")), [])

    def test_nieznani_nadawcy_jedna_linijka_na_przebieg_bez_adresow(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(["od-nieznanego.eml", "od-ogolnej-domeny.eml"])
            _, _, _, slack = uruchom(sk, katalog=Path(tmp))
            self.assertEqual(slack, ["pominięto 2 maili od nieznanych nadawców"])
            self.assertFalse(any("@" in m or "firma-xyz" in m or "wp.pl" in m for m in slack),
                             "w podsumowaniu nie ma adresów")

    def test_ten_sam_nieznany_mail_nie_jest_liczony_ponownie(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            uruchom(FakeSkrzynka(["od-nieznanego.eml"]), rejestr=rejestr, katalog=Path(tmp))
            _, _, _, slack2 = uruchom(FakeSkrzynka(["od-nieznanego.eml"]), rejestr=rejestr, katalog=Path(tmp))
            self.assertEqual(slack2, [], "ten sam mail w kolejnym przebiegu: bez Slacka")
            self.assertEqual(list(rejestr["nieznani"].values())[0]["liczba"], 1)

    def test_brak_nieznanych_to_brak_wiadomosci(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, slack = uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), katalog=Path(tmp))
            self.assertEqual(slack, [])

    def test_rejestr_nie_przechowuje_adresow_nieznanych_nadawcow(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, rejestr, _ = uruchom(FakeSkrzynka(["od-nieznanego.eml"]), katalog=Path(tmp))
            self.assertNotIn("firma-xyz", json.dumps(rejestr), "repo bywa publiczne: tylko hasze")

    def test_ogolna_domena_pocztowa_nigdy_nie_jest_domena_klienta(self):
        karty = {"auto-tama": karta_testowa()}   # w karcie przez pomyłkę jest domena wp.pl
        self.assertEqual(maile.klasyfikuj_nadawce("ola.handlowiec@wp.pl", karty)["typ"], "nieznany")
        self.assertEqual(maile.klasyfikuj_nadawce("ktos@gmail.com", karty)["typ"], "nieznany")
        self.assertEqual(maile.domeny_klienta(karty["auto-tama"]), {"autotama.pl"})
        # ale pełny adres z ogólnej domeny działa, jeśli jest w kontaktach
        self.assertEqual(maile.klasyfikuj_nadawce(KASIA, karty)["typ"], "kontakt")


class TestRejestrMessageId(unittest.TestCase):

    def test_ten_sam_message_id_nie_jest_przetwarzany_dwa_razy(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sk1 = FakeSkrzynka(["od-kasi-plik.eml"])
            w1, _, _, _ = uruchom(sk1, rejestr=rejestr, katalog=Path(tmp))
            sk2 = FakeSkrzynka(["od-kasi-plik.eml"])
            w2, _, _, _ = uruchom(sk2, rejestr=rejestr, katalog=Path(tmp))
            self.assertEqual(len(w1["nowe"]), 1)
            self.assertEqual(w2["nowe"], [])
            self.assertEqual(sk2.pobrane, [], "mail już zapisany nie jest pobierany ponownie")
            self.assertEqual(len(list(Path(tmp).rglob("*.md"))), 1)

    def test_po_sukcesie_mail_nigdy_nie_wraca(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            w, _, _, slack = uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), rejestr=rejestr, katalog=Path(tmp))
            _, sciezka, _ = w["nowe"][0]
            rpath = Path(tmp) / ".maile.json"
            maile.zapisz_rejestr(rejestr, rpath)
            self.assertTrue(maile.oznacz_przetworzony(sciezka, rpath))
            r = maile.wczytaj_rejestr(rpath)
            self.assertIn("<kasia-plik-001@mail.example>", r["przetworzone"])
            self.assertEqual(r["oczekujace"], {})
            sk = FakeSkrzynka(["od-kasi-plik.eml"])
            w2, _, _, _ = uruchom(sk, rejestr=r, katalog=Path(tmp))
            self.assertEqual(w2["nowe"], [])
            self.assertEqual(maile.do_przetworzenia(r, slack.append), [])


class TestRejestrPoSukcesie(unittest.TestCase):
    """Message-ID trafia do "przetworzone" dopiero po udanym przetworzeniu; nieudane próby są ponawiane."""

    def _zapisany(self, tmp, rejestr):
        w, _, _, slack = uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), rejestr=rejestr, katalog=Path(tmp))
        return w["nowe"][0][1], slack

    def test_nowy_mail_jest_oczekujacy_a_nie_przetworzony(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sciezka, _ = self._zapisany(tmp, rejestr)
            self.assertEqual(rejestr["przetworzone"], {}, "przed analizą nic nie jest przetworzone")
            wpis = rejestr["oczekujace"]["<kasia-plik-001@mail.example>"]
            self.assertEqual((wpis["proby"], wpis["status"]), (0, "oczekuje"))
            self.assertIn("- **Message-ID:** <kasia-plik-001@mail.example>", sciezka.read_text(encoding="utf-8"))

    def test_nieudana_analiza_jest_ponawiana_maksymalnie_3_razy_potem_porzucony_z_alertem(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sciezka, _ = self._zapisany(tmp, rejestr)
            slack = []
            for proba in (1, 2, 3):
                lista = maile.do_przetworzenia(rejestr, slack.append)
                self.assertEqual(lista, [Path(sciezka)], f"próba {proba}: mail ma być na liście")
                # przetworz.py nie dotarł do sukcesu: rejestr bez zmian
                self.assertEqual(rejestr["przetworzone"], {})
                # kolejny przebieg widzi ten sam mail w skrzynce: nie zapisuje go drugi raz
                uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), rejestr=rejestr, katalog=Path(tmp))
            self.assertEqual(slack, [], "przez 3 próby bez alertu porzucenia")
            self.assertEqual(rejestr["oczekujace"]["<kasia-plik-001@mail.example>"]["proby"], 3)
            self.assertEqual(maile.do_przetworzenia(rejestr, slack.append), [], "4. raz: już nie próbujemy")
            self.assertEqual(rejestr["oczekujace"]["<kasia-plik-001@mail.example>"]["status"], "porzucony")
            self.assertEqual(len(slack), 1)
            self.assertIn("porzucony po 3", slack[0])
            self.assertIn("Plik ze świeżymi leadami", slack[0])
            self.assertEqual(maile.do_przetworzenia(rejestr, slack.append), [])
            self.assertEqual(len(slack), 1, "alert tylko raz")
            self.assertEqual(len(list(Path(tmp).rglob("*.md"))), 1, "plik maila nie jest zapisywany ponownie")

    def test_sukces_w_trakcie_ponowien_konczy_ponawianie(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sciezka, _ = self._zapisany(tmp, rejestr)
            maile.do_przetworzenia(rejestr, lambda t: None)           # próba 1: porażka
            rpath = Path(tmp) / ".maile.json"
            maile.zapisz_rejestr(rejestr, rpath)
            maile.oznacz_przetworzony(sciezka, rpath)                 # próba 2 zakończona sukcesem
            r = maile.wczytaj_rejestr(rpath)
            self.assertEqual(maile.do_przetworzenia(r, lambda t: None), [])
            self.assertIn("<kasia-plik-001@mail.example>", r["przetworzone"])

    def test_porzucony_mail_przetworzony_recznie_przechodzi_do_przetworzonych(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sciezka, _ = self._zapisany(tmp, rejestr)
            for _ in range(4):
                maile.do_przetworzenia(rejestr, lambda t: None)
            self.assertEqual(rejestr["oczekujace"]["<kasia-plik-001@mail.example>"]["status"], "porzucony")
            rpath = Path(tmp) / ".maile.json"
            maile.zapisz_rejestr(rejestr, rpath)
            self.assertTrue(maile.oznacz_przetworzony(sciezka, rpath))
            r = maile.wczytaj_rejestr(rpath)
            self.assertEqual(r["oczekujace"], {})
            self.assertIn("<kasia-plik-001@mail.example>", r["przetworzone"])

    def test_alert_porzucenia_nie_przepuszcza_znacznikow_z_tematu(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            sciezka, _ = self._zapisany(tmp, rejestr)
            sciezka.write_text(sciezka.read_text(encoding="utf-8").replace(
                "- **Temat:** Re: Plik ze świeżymi leadami", "- **Temat:** <!channel> pilne"), encoding="utf-8")
            slack = []
            for _ in range(4):
                maile.do_przetworzenia(rejestr, slack.append)
            self.assertNotIn("<!channel>", slack[0])
            self.assertIn("&lt;!channel&gt;", slack[0])

    def test_oznacz_przetworzony_pomija_stare_pliki_bez_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            stary = Path(tmp) / "maile" / "auto-tama" / "2026-10-14-stary.md"
            stary.parent.mkdir(parents=True)
            stary.write_text("# Mail: x\n\n- **Od:** a@b.pl\n- **Data:** 2026-10-14 09:00\n- **Temat:** x\n",
                             encoding="utf-8")
            self.assertFalse(maile.oznacz_przetworzony(stary, Path(tmp) / ".maile.json"))

    def test_przetworz_py_oznacza_mail_po_sukcesie_a_nie_przed_analiza(self):
        kod = (Path(maile.__file__).parent / "przetworz.py").read_text(encoding="utf-8")
        # ZMIANA ŚWIADOMA (utwardzanie, pkt 17): dwa miejsca. Główne po analizie i drugie w ścieżce krótkiego potwierdzenia
        # klienta („dzięki”), która kończy się bez analizy. W obu oznaczenie dopiero PO zapisie rejestru transkrypcji.
        self.assertEqual(kod.count("oznacz_przetworzony("), 2)
        poz = [i for i in range(len(kod)) if kod.startswith("oznacz_przetworzony(", i)]
        zapisy = [i for i in range(len(kod)) if kod.startswith("save_registry(registry)", i)]
        for i in poz:
            self.assertTrue(any(z < i for z in zapisy), "oznaczenie dopiero po udanym zakończeniu (razem z rejestrem transkrypcji)")
            self.assertLess(max(z for z in zapisy if z < i), i)


class TestMaileAutomatyczne(unittest.TestCase):
    """Newslettery i powiadomienia: pomijane całkowicie i po cichu."""

    AUTO = ["auto-linkedin.eml", "auto-uber.eml", "auto-noreply.eml", "auto-bulk.eml",
            "auto-noreply-domeny-klienta.eml"]

    def test_automatyczne_pomijane_po_cichu_bez_sladu(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(self.AUTO)
            karty = {"auto-tama": karta_testowa()}
            przed = copy.deepcopy(karty)
            wynik, _, rejestr, slack = uruchom(sk, karty=karty, katalog=Path(tmp))
            self.assertEqual(wynik["automatyczne"], 5)
            self.assertEqual(slack, [], "ani jednej wiadomości na Slacku")
            self.assertEqual(sk.pobrane, [], "treść automatycznych maili nie jest pobierana")
            self.assertEqual(list(Path(tmp).rglob("*.md")), [])
            self.assertEqual(rejestr["nieznani"], {}, "nie liczą się nawet jako nieznani")
            self.assertEqual(rejestr["oczekujace"], {})
            self.assertEqual(karty, przed, "noreply@ z domeny klienta nie trafia do kontaktów")
            self.assertEqual(wynik["nieznani"], 0)

    def test_kazde_kryterium_osobno(self):
        import email as em
        from email.policy import default
        def msg(naglowki):
            return em.message_from_bytes(naglowki.encode() + b"\n\ntresc", policy=default)
        ca = maile.czy_automatyczny
        self.assertTrue(ca(msg("From: a@b.pl\nList-Unsubscribe: <https://x>"), "a@b.pl"))
        self.assertTrue(ca(msg("From: a@b.pl\nAuto-Submitted: auto-replied"), "a@b.pl"))
        for wartosc in ("bulk", "list", "junk", "Bulk"):
            self.assertTrue(ca(msg(f"From: a@b.pl\nPrecedence: {wartosc}"), "a@b.pl"), wartosc)
        for adres in ("noreply@x.pl", "no-reply@x.pl", "no_reply@x.pl", "messages-noreply@linkedin.com",
                      "do-not-reply@x.pl", "donotreply@x.pl", "notifications@x.pl", "notification-abc@x.pl",
                      "mailer-daemon@x.pl", "NoReply@X.PL"):
            self.assertTrue(ca(msg("From: " + adres), adres), adres)

    def test_zwykly_mail_nie_jest_automatyczny(self):
        import email as em
        from email.policy import default
        def msg(naglowki):
            return em.message_from_bytes(naglowki.encode() + b"\n\ntresc", policy=default)
        ca = maile.czy_automatyczny
        self.assertFalse(ca(msg("From: kasia@x.pl"), "kasia@x.pl"))
        self.assertFalse(ca(msg("From: kasia@x.pl\nAuto-Submitted: no"), "kasia@x.pl"))
        self.assertFalse(ca(msg("From: kasia@x.pl\nPrecedence: first-class"), "kasia@x.pl"))
        self.assertFalse(ca(msg("From: reply@x.pl"), "reply@x.pl"), "'reply' to nie 'noreply'")
        self.assertFalse(ca(msg("From: jan.notifier@x.pl"), "jan.notifier@x.pl"))

    def test_auto_submitted_no_od_znanego_kontaktu_jest_przetwarzany(self):
        with tempfile.TemporaryDirectory() as tmp:
            wynik, _, _, _ = uruchom(FakeSkrzynka(["od-kasi-auto-submitted-no.eml"]), katalog=Path(tmp))
            self.assertEqual(len(wynik["nowe"]), 1)

    def test_pobierane_naglowki_zawieraja_pola_potrzebne_do_wykrycia_automatow(self):
        for pole in ("LIST-UNSUBSCRIBE", "AUTO-SUBMITTED", "PRECEDENCE", "FROM", "MESSAGE-ID", "DATE"):
            self.assertIn(pole, maile.NAGLOWKI_IMAP.split())

    def test_mieszana_skrzynka_automaty_nieznani_i_znany(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(self.AUTO + ["od-nieznanego.eml", "od-kasi-plik.eml"])
            wynik, _, _, slack = uruchom(sk, katalog=Path(tmp))
            self.assertEqual(slack, ["pominięto 1 maili od nieznanych nadawców"])
            self.assertEqual(len(wynik["nowe"]), 1)
            self.assertEqual(sk.pobrane, ["od-kasi-plik.eml"])


class TestDataWlaczenia(unittest.TestCase):

    def test_pierwszy_przebieg_zapisuje_date_wlaczenia_w_rejestrze(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr()
            uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), rejestr=rejestr, katalog=Path(tmp), dzis="2026-10-14")
            self.assertEqual(rejestr["wlaczono"], "2026-10-14")

    def test_maile_sprzed_wlaczenia_ignorowane_calkowicie(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(["od-kasi-plik.eml", "od-nieznanego.eml"])   # oba z 14.10
            rejestr = nowy_rejestr()
            wynik, _, _, slack = uruchom(sk, rejestr=rejestr, katalog=Path(tmp), dzis="2026-10-20")
            self.assertEqual(rejestr["wlaczono"], "2026-10-20")
            self.assertEqual(wynik["nowe"], [])
            self.assertEqual(wynik["nieznani"], 0, "historia nie jest nawet liczona")
            self.assertEqual(slack, [])
            self.assertEqual(sk.pobrane, [])

    def test_istniejaca_data_wlaczenia_nie_jest_nadpisywana(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejestr = nowy_rejestr(wlaczono="2026-10-10")
            wynik, _, _, _ = uruchom(FakeSkrzynka(["od-kasi-plik.eml"]), rejestr=rejestr,
                                     katalog=Path(tmp), dzis="2026-10-20")
            self.assertEqual(rejestr["wlaczono"], "2026-10-10")
            self.assertEqual(len(wynik["nowe"]), 1, "mail z 14.10 jest po dacie włączenia 10.10")

    def test_okno_wyszukiwania_nie_siega_przed_date_wlaczenia(self):
        from datetime import date
        self.assertEqual(maile.okno_od(date(2026, 10, 20), 14, "2026-10-18"), date(2026, 10, 18))
        self.assertEqual(maile.okno_od(date(2026, 10, 20), 14, "2026-09-01"), date(2026, 10, 6))
        self.assertEqual(maile.okno_od(date(2026, 10, 20), 14, None), date(2026, 10, 6))


class TestTrescMaila(unittest.TestCase):

    def _zapisz(self, nazwa):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wynik, _, _, _ = uruchom(FakeSkrzynka([nazwa]), katalog=Path(tmp.name))
        _, sciezka, _ = wynik["nowe"][0]
        return sciezka, sciezka.read_text(encoding="utf-8")

    def test_cytowana_wiadomosc_i_stopka_obciete(self):
        sciezka, md = self._zapisz("od-kasi-plik.eml")
        self.assertIn("wysyłam plik ze świeżymi leadami", md)
        self.assertNotIn("Czekam do czwartku na plik", md, "cytowana wcześniejsza wiadomość")
        self.assertNotIn("napisał(a)", md)
        self.assertNotIn("Pozdrawiam", md, "formuła i podpis to stopka")

    def test_separator_stopki_cytaty_ze_znakiem_wiekszosci_i_stopka_mobilna(self):
        _, md = self._zapisz("od-kasi-stopka.eml")
        self.assertIn("potwierdzam szkolenie", md)
        self.assertIn("Nie przypominaj mi o pliku", md, "nowa treść po cytacie zostaje")
        self.assertNotIn("Czy wtorek 27.10 o 10:00 pasuje", md, "linia cytowana znakiem >")
        self.assertNotIn("BDC, Grupa Auto Tama", md, "stopka po separatorze '-- '")
        self.assertNotIn("600 000 000", md)
        self.assertNotIn("Wysłano z iPhone", md)

    def test_zalaczniki_na_liscie_i_nazwa_pliku_wedlug_wzoru(self):
        sciezka, md = self._zapisz("od-kasi-plik.eml")
        self.assertIn("- **Załączniki:** leady-pazdziernik.xlsx", md)
        self.assertRegex(sciezka.name, r"^2026-10-14-plik-ze-swiezymi-leadami\.md$")
        self.assertEqual(sciezka.parent.name, "auto-tama")
        for pole in ("- **Od:** Kasia Malinowska <" + KASIA + ">", "- **Do:**", "- **Data:** 2026-10-14 09:12",
                     "- **Temat:** Re: Plik ze świeżymi leadami"):
            self.assertIn(pole, md)

    def test_mail_html_bez_cytowanego_blockquote(self):
        _, md = self._zapisz("od-kasi-html.eml")
        self.assertIn("numer sprawy to 4821", md)
        self.assertNotIn("Prosiliśmy o numer sprawy od Oli", md)

    def test_brak_zalacznikow_zapisany_jako_brak(self):
        _, md = self._zapisz("od-kasi-stopka.eml")
        self.assertIn("- **Załączniki:** brak", md)

    def test_meta_maila_odczytywana_z_pliku(self):
        sciezka, _ = self._zapisz("od-kasi-plik.eml")
        meta = maile.wczytaj_meta_maila(sciezka)
        self.assertEqual(meta["od_adres"], KASIA)
        self.assertEqual(meta["data"], "2026-10-14")


class TestDomenaKlienta(unittest.TestCase):

    def test_domena_klienta_pelny_adres_kontakt_poddomena_i_podrobki(self):
        karty = {"auto-tama": karta_testowa()}
        k = maile.klasyfikuj_nadawce
        self.assertEqual(k("pawel@autotama.pl", karty)["typ"], "kontakt")
        self.assertEqual(k("nowa.osoba@autotama.pl", karty), {"typ": "domena", "klient": "auto-tama", "kontakt": None})
        self.assertEqual(k("ktos@mail.autotama.pl", karty)["typ"], "domena")
        self.assertEqual(k("ktos@evilautotama.pl", karty)["typ"], "nieznany")
        self.assertEqual(k("ktos@autotama.pl.evil.example", karty)["typ"], "nieznany")
        self.assertEqual(k("KASIA@Autotama.PL ", karty)["typ"], "domena")

    def test_nadawca_z_domeny_jest_czytany_i_dodany_jako_nowy_bez_prawa_decyzji(self):
        with tempfile.TemporaryDirectory() as tmp:
            sk = FakeSkrzynka(["od-domeny-klienta.eml"])
            wynik, karty, rejestr, slack = uruchom(sk, katalog=Path(tmp))
            self.assertEqual(len(wynik["nowe"]), 1, "mail z domeny klienta jest czytany")
            self.assertEqual(sk.pobrane, ["od-domeny-klienta.eml"])
            kontakt = maile.znajdz_kontakt(karty["auto-tama"], "pawel.nowak@autotama.pl")
            self.assertIsNotNone(kontakt, "nadawca trafia do kontaktów")
            self.assertIs(kontakt["potwierdzony"], False)
            self.assertEqual(kontakt["status"], "nowy, bez prawa decyzji")
            self.assertFalse(maile.kontakt_ma_prawo_decyzji(kontakt))
            self.assertEqual(wynik["zmienione_karty"], {"auto-tama"})
            self.assertTrue(any("pawel.nowak@autotama.pl" in m and "Potwierdź" in m for m in slack),
                            "informacja na Slacku do potwierdzenia przez człowieka")

    def test_drugi_mail_nowego_nadawcy_nie_dubluje_kontaktu_ani_slacka(self):
        with tempfile.TemporaryDirectory() as tmp:
            karty = {"auto-tama": karta_testowa()}
            rejestr = nowy_rejestr()
            uruchom(FakeSkrzynka(["od-domeny-klienta.eml"]), karty, rejestr, Path(tmp))
            sk2 = FakeSkrzynka(["od-domeny-klienta.eml"], zmien_id={"od-domeny-klienta.eml": "pawel-druga@x.example"})
            wynik, _, _, slack = uruchom(sk2, karty, rejestr, Path(tmp))
            self.assertEqual(len(wynik["nowe"]), 1)
            self.assertEqual(slack, [], "nadawca już jest w kontaktach")
            adresy = [k["email"] for k in karty["auto-tama"]["kontakty"]]
            self.assertEqual(adresy.count("pawel.nowak@autotama.pl"), 1)

    def test_niepotwierdzony_nadawca_nie_uchyla_zakazu_ani_nie_zmienia_decyzji(self):
        karta = karta_testowa()
        zrodlo = ustal_zrodlo("x/maile/auto-tama/2026-10-14-opel.md", {}, karta,
                              meta={"od_adres": "nowy@autotama.pl", "data": "2026-10-14"})
        self.assertFalse(zrodlo["prawo"])
        ok, powod = sprawdz_uprawnienia(karta, {"pewnosc": "wysoka"}, zrodlo, zakaz_id="Z8")
        self.assertFalse(ok)
        self.assertIn("niepotwierdzony", powod)
        ok, _ = sprawdz_uprawnienia(karta, {"pewnosc": "wysoka"}, zrodlo, klucz="decyzja-opel-stara-baza")
        self.assertFalse(ok)
        # ale zwykła informacja (sprawa bez zastrzeżenia) przechodzi
        ok, _ = sprawdz_uprawnienia(karta, {"pewnosc": "wysoka"}, zrodlo, klucz="swieze-leady")
        self.assertTrue(ok)


class TestUprawnieniaKodu(unittest.TestCase):
    """Kod, nie instrukcja, pilnuje, kto może uchylić zakaz albo zmienić zastrzeżoną decyzję."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _mail(self, od, data="2026-10-14"):
        from datetime import datetime
        meta = {"od_imie": "", "od_adres": od, "do": "automat", "data": datetime.fromisoformat(data + "T10:00:00"),
                "temat": "Test", "zalaczniki": [], "tresc": "treść"}
        return maile.zapisz_mail_md("auto-tama", meta, Path(self.tmp.name) / "maile").as_posix()

    def _upd(self, klucz, status="anulowana", pewnosc="wysoka"):
        return {"klucz_sprawy": klucz, "nowy_status": status, "cytat": "c", "uzasadnienie": "u", "pewnosc": pewnosc}

    def _uruchom(self, source, upd, karta=None, wynik_extra=None):
        karta = karta or karta_testowa()
        wynik = {"zrodlo": source, "spotkanie": {"data": "2026-10-14"}, "aktualizacje_spraw": [upd]}
        wynik.update(wynik_extra or {})
        bufor = io.StringIO()
        with contextlib.redirect_stdout(bufor):
            n = process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True,
                                     meeting_date=ustal_zrodlo(source, wynik, karta)["data"], source=source)
        return n, bufor.getvalue()

    def test_zakaz_uchylony_przez_niewlasciwa_osobe_odrzucony(self):
        # Paweł jest potwierdzonym kontaktem i decydentem, ale Opel (Z4) jest zastrzeżony dla Kasi
        n, out = self._uruchom(self._mail("pawel@autotama.pl"), self._upd("Z4"))
        self.assertEqual(n, 0)
        self.assertIn("Odrzucono aktualizację: Z4", out)
        self.assertIn("zastrzeżone dla: Kasia Malinowska", out)

    def test_zakaz_uchylony_przez_wlasciwa_osobe_przechodzi(self):
        n, out = self._uruchom(self._mail(KASIA), self._upd("Z4"))
        self.assertEqual(n, 1, out)
        self.assertNotIn("Odrzucono", out)

    def test_zakaz_bez_zastrzezenia_uchyla_dowolny_potwierdzony_decydent(self):
        n, _ = self._uruchom(self._mail("pawel@autotama.pl"), self._upd("Z8"))
        self.assertEqual(n, 1)

    def test_nadawca_spoza_kontaktow_nie_uchyla_zakazu(self):
        n, out = self._uruchom(self._mail("jan@firma-xyz.example"), self._upd("Z8"))
        self.assertEqual(n, 0)
        self.assertIn("nie jest kontaktem klienta", out)

    def test_polecenie_w_imieniu_innej_osoby_pewnosc_niska_odrzucone(self):
        n, out = self._uruchom(self._mail(KASIA), self._upd("Z4", pewnosc="niska"))
        self.assertEqual(n, 0)
        self.assertIn("pewność niska", out)

    def test_zastrzezona_decyzja_zmieniona_przez_niewlasciwa_osobe_odrzucona(self):
        zrodlo = "ops/transkrypcje/auto-tama/2026-10-14-call.md"   # rozmowa z Pawłem, bez Kasi
        wynik_extra = {"spotkanie": {"data": "2026-10-14", "uczestnicy": ["Marek Rewoliński", "Paweł"]}}
        n, out = self._uruchom(zrodlo, self._upd("decyzja-opel-stara-baza", "zrob_teraz"), wynik_extra=wynik_extra)
        self.assertEqual(n, 0)
        self.assertIn("Odrzucono aktualizację: decyzja-opel-stara-baza", out)

    def test_zastrzezona_decyzja_w_rozmowie_z_wlasciwa_osoba_przechodzi(self):
        zrodlo = "ops/transkrypcje/auto-tama/2026-10-14-call.md"
        wynik_extra = {"spotkanie": {"data": "2026-10-14", "uczestnicy": ["Kasia Malinowska", "Marek Rewoliński"]}}
        n, out = self._uruchom(zrodlo, self._upd("decyzja-opel-stara-baza", "zrob_teraz"), wynik_extra=wynik_extra)
        self.assertEqual(n, 1, out)

    def test_nadawca_pochodzi_z_pliku_maila_a_nie_z_wynik_json(self):
        # model nie może podszyć się pod Kasię wpisując ją w „uczestnicy”
        wynik_extra = {"spotkanie": {"data": "2026-10-14", "uczestnicy": ["Kasia Malinowska"]}}
        n, _ = self._uruchom(self._mail("jan@firma-xyz.example"), self._upd("Z4"), wynik_extra=wynik_extra)
        self.assertEqual(n, 0)

    def test_wymagani_decydenci(self):
        karta = karta_testowa()
        self.assertEqual(wymagani_decydenci(karta, zakaz_id="Z4"), ["Kasia Malinowska"])
        self.assertEqual(wymagani_decydenci(karta, zakaz_id="Z8"), ["Kasia Malinowska", "Paweł"])
        self.assertIsNone(wymagani_decydenci(karta, klucz="swieze-leady"))


class TestMailStarszyNizSprawa(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _mail(self, data):
        from datetime import datetime
        meta = {"od_imie": "", "od_adres": KASIA, "do": "a", "data": datetime.fromisoformat(data + "T10:00:00"),
                "temat": "Plik", "zalaczniki": [], "tresc": "treść"}
        return maile.zapisz_mail_md("auto-tama", meta, Path(self.tmp.name) / "maile").as_posix()

    def _n(self, data):
        source = self._mail(data)
        karta = karta_testowa()
        wynik = {"zrodlo": source, "spotkanie": {"data": data}, "aktualizacje_spraw": [
            {"klucz_sprawy": "swieze-leady", "nowy_status": "zrob_teraz", "cytat": "c",
             "uzasadnienie": "u", "pewnosc": "wysoka"}]}
        with contextlib.redirect_stdout(io.StringIO()):
            return process_aktualizacje(None, wynik, karta, {}, {}, dry_run=True,
                                        meeting_date=ustal_zrodlo(source, wynik, karta)["data"], source=source)

    def test_mail_starszy_niz_sprawa_nie_wznawia(self):
        self.assertEqual(self._n("2026-10-05"), 0, "sprawa pochodzi z rozmowy 2026-10-06")

    def test_mail_z_ta_sama_data_co_sprawa_nie_wznawia(self):
        self.assertEqual(self._n("2026-10-06"), 0)

    def test_mail_pozniejszy_wznawia(self):
        self.assertEqual(self._n("2026-10-14"), 1)

    def test_data_zrodla_maila_pochodzi_z_pliku_maila(self):
        source = self._mail("2026-10-14")
        wynik = {"spotkanie": {"data": "1999-01-01"}}      # model się pomylił
        self.assertEqual(ustal_zrodlo(source, wynik, karta_testowa())["data"], "2026-10-14")


class TestBezpieczenstwoKodu(unittest.TestCase):

    def test_maile_py_otwiera_skrzynke_tylko_do_odczytu(self):
        kod = Path(maile.__file__).read_text(encoding="utf-8")
        self.assertIn('select("INBOX", readonly=True)', kod)
        uzyte = set(re.findall(r"self\.m\.(\w+)\(", kod))
        self.assertEqual(uzyte, {"login", "select", "uid", "logout"}, f"niedozwolone operacje IMAP: {uzyte}")
        self.assertEqual(set(re.findall(r'\.uid\("(\w+)"', kod)), {"SEARCH", "FETCH"})
        for zakazane in ("smtplib", "EXPUNGE", ".expunge(", ".store(", ".copy(", "RFC822", "(BODY["):
            self.assertNotIn(zakazane, kod)
        self.assertIn("BODY.PEEK[]", kod)

    def test_slack_nie_przepuszcza_znacznikow_z_tematu_maila(self):
        import przetworz
        brudny = "<!channel> <@U123> <https://zly.example|kliknij> a&b\nnowa linia"
        bezpieczny = przetworz.slack_bezpiecznie(brudny)
        self.assertNotIn("<", bezpieczny)
        self.assertNotIn(">", bezpieczny)
        self.assertNotIn("\n", bezpieczny)

    def test_slack_pokazuje_ze_zrodlem_byl_mail_i_temat(self):
        import przetworz
        with tempfile.TemporaryDirectory() as tmp:
            wynik = Path(tmp) / "wynik.json"
            wynik.write_text(json.dumps({"spotkanie": {"data": "2026-10-14"}, "pozycje": [],
                                         "aktualizacje_spraw": [], "ostrzezenia_dat": []}), encoding="utf-8")
            msg = przetworz.build_slack_summary(
                "klient-testowy", wynik, "", meta_maila={"data": "2026-10-14", "temat": "Re: Plik <!channel>"})
        # ZMIENIONE ŚWIADOMIE (nowy wygląd Slacka): zdanie na górze mówi, że źródłem był mail, i podaje temat;
        # wcześniejsze linie ze stałymi zerami (np. „Odrzucone (brak uprawnień): 0”) zniknęły.
        self.assertTrue(msg.startswith(":email: *klient-testowy*: mail „Re: Plik &lt;!channel&gt;” przetworzony."))
        self.assertNotIn("<!channel>", msg)
        self.assertNotIn("Odrzucone (brak uprawnień)", msg)

    def test_klient_ze_sciezki_maila(self):
        import przetworz
        self.assertEqual(przetworz.extract_klient("ops/maile/auto-tama/2026-10-14-x.md"), "auto-tama")
        self.assertEqual(przetworz.extract_klient("ops/transkrypcje/klinika-usmiech/x.md"), "klinika-usmiech")

    def test_hasla_gmaila_czyszczone_z_niewidocznych_znakow(self):
        from sekrety import czysc, NAZWY_SEKRETOW
        self.assertEqual(czysc("abcd efgh  ijkl mnop\n"), "abcdefghijklmnop")
        self.assertIn("GMAIL_ADDRESS", NAZWY_SEKRETOW)
        self.assertIn("GMAIL_APP_PASSWORD", NAZWY_SEKRETOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
