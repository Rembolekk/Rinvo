#!/usr/bin/env python3
"""test_strony.py – statyczne strony (generuj_strony.py), stan Lineara (stan_linear.py) i dziennik zdarzeń (zdarzenia.py).

Bez sieci i bez modelu: fikcyjne dane w katalogu tymczasowym, plus próba na prawdziwych danych repozytorium.
Uruchomienie: python3 testy/test_strony.py
"""

import json
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
MIGAWKA = ROOT / "testy/migawka_demo"          # dane demo sprzed resetu
sys.path.insert(0, str(ROOT))

import generuj_strony as gs
import stan_linear
import zasady
import zdarzenia

DZIS = date(2026, 10, 14)
Z = zasady.wczytaj_zasady()


def zg(tytul, stan="Todo", etykiety=(), termin=None, url="https://linear.app/ws/issue/RIN-1/x"):
    return {"tytul": tytul, "url": url, "stan": stan, "typ_stanu": "", "etykiety": sorted(etykiety), "termin": termin,
            "utworzono": "2026-10-01T00:00:00Z", "zmieniono": None, "zamknieto": None, "priorytet": 0}


class Repo:
    """Minimalne repozytorium w katalogu tymczasowym."""

    def __init__(self, stan=None, zdarz=None, prosby=None, karta_a=None, karta_b=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "ops").mkdir()
        (self.root / "ops/zasady.json").write_text((ROOT / "ops/zasady.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.zapisz("ops/.stan_linear.json", {"zapisano": "2026-10-14T10:00:00+00:00", "zgloszenia": stan or {}})
        self.zapisz("ops/.zdarzenia.json", zdarz or [])
        self.zapisz("ops/produkt/prosby.json", prosby or {})
        self.zapisz("ops/klienci/alfa/karta.json", karta_a if karta_a is not None else karta("alfa"))
        self.zapisz("ops/klienci/beta/karta.json", karta_b if karta_b is not None else karta("beta"))

    def zapisz(self, sciezka, dane):
        p = self.root / sciezka
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dane, ensure_ascii=False), encoding="utf-8")

    def wynik(self, klient, folder, dane, raport=True):
        self.zapisz(f"wyniki/{klient}/{folder}/wynik.json", dane)
        if raport:
            (self.root / f"wyniki/{klient}/{folder}/raport.html").write_text("<html></html>", encoding="utf-8")

    def dane(self):
        return gs.wczytaj_dane(self.root, DZIS)

    def strony(self):
        return gs.buduj(self.dane())


def karta(slug, **kw):
    k = {"klient": slug, "nazwa": slug.title(), "decydenci": [{"imie": "Dec Ydent", "rola": "decyduje"}],
         "kontakty": [{"imie": "Kon Takt", "email": "tajny.adres@example.com", "rola": "kontakt główny", "potwierdzony": True,
                       "nieobecnosci": [{"od": "2026-10-19", "do": "2026-10-23"}]}],
         "zakazy": [], "otwarte_sprawy": {}, "ryzyka": {}}
    k.update(kw)
    return k


def tekst(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", h, flags=re.S)))


class TestSwiatlo(unittest.TestCase):

    def _kolor(self, **kw):
        r = Repo(**kw)
        d = r.dane()
        return gs.swiatlo(d, d["klienci"]["alfa"])

    def test_zielone_gdy_nic_nie_pali(self):
        kolor, powody = self._kolor(stan={"RIN-1": zg("[alfa] Zwykłe zadanie", etykiety=["Dla agenta"])})
        self.assertEqual((kolor, powody), ("zielone", []))

    def test_zolte_gdy_cos_wymaga_czlowieka(self):
        kolor, powody = self._kolor(stan={"RIN-1": zg("[alfa] Decyzja", etykiety=["Decyzja człowieka"])})
        self.assertEqual(kolor, "zolte")
        self.assertIn("wymaga człowieka", powody[0])

    def test_czerwone_przy_powtarzajacym_sie_ryzyku(self):
        k = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "x"}, {"data": "2026-10-13", "zrodlo": "b.md", "cytat": "y"}]})
        kolor, powody = self._kolor(karta_a=k)
        self.assertEqual(kolor, "czerwone")
        self.assertIn("pojawiło się już 2 razy", powody[0])

    def test_dwa_cytaty_z_jednej_rozmowy_to_jedno_wystapienie(self):
        k = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-13", "zrodlo": "a.md", "cytat": "x"}, {"data": "2026-10-13", "zrodlo": "a.md", "cytat": "y"}]})
        self.assertEqual(self._kolor(karta_a=k)[0], "zielone")

    def test_czerwone_przy_sprawie_po_terminie_ale_nie_zamknietej(self):
        self.assertEqual(self._kolor(stan={"RIN-1": zg("[alfa] Spóźnione", termin="2026-10-10", etykiety=["Dla agenta"])})[0], "czerwone")
        self.assertEqual(self._kolor(stan={"RIN-1": zg("[alfa] Zrobione", stan="Done", termin="2026-10-10")})[0], "zielone")
        self.assertEqual(self._kolor(stan={"RIN-1": zg("[alfa] Jutro", termin="2026-10-15", etykiety=["Dla agenta"])})[0], "zielone")

    def test_czerwone_wygrywa_z_zoltym(self):
        stan = {"RIN-1": zg("[alfa] Decyzja", etykiety=["Decyzja człowieka"]), "RIN-2": zg("[alfa] Spóźnione", termin="2026-10-01")}
        self.assertEqual(self._kolor(stan=stan)[0], "czerwone")


class TestSprawy(unittest.TestCase):

    def test_podzial_na_agenta_czlowieka_i_czekajacych(self):
        stan = {"RIN-1": zg("[alfa] A", etykiety=["Dla agenta"]), "RIN-2": zg("[alfa] B", etykiety=["Decyzja człowieka"]),
                "RIN-3": zg("[alfa] C", etykiety=["Czeka na klienta"]), "RIN-4": zg("[alfa] D", stan="Backlog", etykiety=["Produkt", "Decyzja człowieka"]),
                "RIN-5": zg("[alfa] E", stan="Done", etykiety=["Dla agenta"]), "RIN-6": zg("[beta] F", etykiety=["Dla agenta"]),
                "RIN-7": zg("[alfa] G", stan="Backlog", etykiety=["Czeka na klienta"])}
        d = Repo(stan=stan).dane()
        s = gs.sprawy_klienta(d, "alfa")
        self.assertEqual([z["id"] for z in s["agent"]], ["RIN-1"])
        # ZMIANA ŚWIADOMA: „wymaga Ciebie” to te same sprawy, które pokazuje widok „Dla mnie dziś” w Linearze (etykiety Decyzja człowieka,
        # Do weryfikacji, Szkic gotowy, także w backlogu), więc RIN-4 (prośba produktowa z Decyzją człowieka) nie ginie w „backlogu”
        self.assertEqual([z["id"] for z in s["czlowiek"]], ["RIN-2"])
        self.assertEqual([z["id"] for z in s["produkt"]], ["RIN-4"], "decyzje o priorytetach produktu: przegląd raz w tygodniu, nie „dziś”")
        self.assertEqual([z["id"] for z in s["czeka"]], ["RIN-3", "RIN-7"], "czekanie na klienta liczy się także w backlogu")
        self.assertEqual(s["backlog"], [])
        self.assertEqual([z["id"] for z in s["zamkniete"]], ["RIN-5"])

    def test_liczby_na_stronie_glownej(self):
        stan = {"RIN-1": zg("[alfa] A", etykiety=["Dla agenta"]), "RIN-2": zg("[alfa] A2", etykiety=["Dla agenta"]),
                "RIN-3": zg("[alfa] B", etykiety=["Decyzja człowieka"]), "RIN-4": zg("[alfa] C", etykiety=["Czeka na klienta"])}
        h = Repo(stan=stan).strony()["index.html"]
        wiersz = re.search(r'<tr><td><span class="dot[^"]*"[^>]*></span><a href="klienci/alfa\.html">Alfa</a></td>(.*?)</tr>', h, re.S).group(1)
        liczby = re.findall(r'<td class="n[^"]*">(\d+)</td>', wiersz)
        self.assertEqual(liczby, ["1", "2", "1"], "Wymaga Ciebie, U agentów, Czeka na klienta")
        self.assertIn("Dziś potrzebujemy Cię w 1 sprawie", tekst(h))


class TestStrony(unittest.TestCase):

    def test_zestaw_stron_i_ukladu(self):
        s = Repo().strony()
        self.assertEqual(sorted(s), ["glos-klientow.html", "index.html", "klienci/alfa.html", "klienci/beta.html"])

    def test_kazda_strona_ma_dopisek_dane_fikcyjne_demo_i_viewport(self):
        for sciezka, h in Repo().strony().items():
            self.assertIn("dane fikcyjne, demo", h.lower(), sciezka)
            self.assertIn("Dane fikcyjne, demo", h, sciezka)
            self.assertIn('name="viewport" content="width=device-width,initial-scale=1"', h, sciezka)
            self.assertIn("prefers-color-scheme:dark", h)

    def test_linki_wzgledne_dzialaja_z_podkatalogu(self):
        s = Repo().strony()
        self.assertIn('href="../index.html"', s["klienci/alfa.html"])
        self.assertIn('href="../glos-klientow.html"', s["klienci/alfa.html"])
        self.assertIn('href="klienci/alfa.html"', s["index.html"])

    def test_adresy_email_nie_trafiaja_na_strony(self):
        for sciezka, h in Repo().strony().items():
            self.assertNotIn("tajny.adres@example.com", h, sciezka)
            self.assertNotIn("@example.com", h, sciezka)

    def test_html_jest_escapowany(self):
        k = karta("alfa", zakazy=[{"id": "Z1", "tytul": "<script>alert(1)</script>", "opis": "", "cytat": ['"><img src=x onerror=1>']}])
        h = Repo(karta_a=k).strony()["klienci/alfa.html"]
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertNotIn("<img src=x", h)
        self.assertIn("&lt;script&gt;", h)

    def test_generowanie_jest_deterministyczne(self):
        r = Repo()
        self.assertEqual(r.strony(), r.strony())

    def test_zapis_pomija_niezmienione(self):
        r = Repo()
        s = r.strony()
        self.assertEqual(gs.zapisz(s, r.root), 4)
        self.assertEqual(gs.zapisz(s, r.root), 0)
        self.assertTrue((r.root / "klienci/alfa.html").exists())


class TestStronaKlienta(unittest.TestCase):

    def _repo(self):
        stan = {"RIN-2": zg("[alfa] Decyzja o Oplu", etykiety=["Decyzja człowieka"], url="https://linear.app/ws/issue/RIN-2/opel"),
                "RIN-1": zg("[alfa] Poprawka godzin", etykiety=["Dla agenta"], url="https://linear.app/ws/issue/RIN-1/g"),
                "RIN-3": zg("[alfa] Plik od klienta", etykiety=["Czeka na klienta"], termin="2026-10-20")}
        zd = [{"data": "2026-10-14T10:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-1", "tytul": "Poprawka godzin", "url": "https://github.com/x/y/pull/7"},
              {"data": "2026-10-13T09:00:00+00:00", "typ": "notatka", "klient": "alfa", "zgloszenie": "RIN-9", "tytul": "Notatka przed spotkaniem", "url": "ops/materialy/alfa/notatka-2026-10-15.pdf"},
              {"data": "2026-10-12T09:00:00+00:00", "typ": "material", "klient": "alfa", "zgloszenie": "RIN-8", "tytul": "Ściąga", "url": "ops/materialy/alfa/rin-8.pdf"},
              {"data": "2026-10-12T09:00:00+00:00", "typ": "pr_scalony", "klient": "beta", "zgloszenie": "RIN-50", "tytul": "Cudza poprawka", "url": "https://github.com/x/y/pull/9"}]
        k = karta("alfa", zakazy=[{"id": "Z1", "tytul": "Nie włączać Opla", "opis": "Czeka na wyniki", "cytat": ["Opla nie puszczamy.", "Drugi cytat."]}],
                  historia_zakazow=[{"id": "Z2", "tytul": "Nie testować wstępu", "cytat": ["Nie puszczajcie."], "uchylony": "Możecie puścić od jutra.", "kiedy": "2026-10-14"}],
                  ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk jest tańszy."}, {"data": "2026-10-13", "zrodlo": "b.md", "cytat": "Oferta na piśmie."}]},
                  historia_wysylek=[{"data": "2026-10-14T14:36:51+02:00", "temat": "Spotkanie w czwartek", "do": "Kon Takt", "zaproszenie_ics": True, "zalaczniki": ["x.pdf"], "zgloszenia": ["RIN-51"]}])
        r = Repo(stan=stan, zdarz=zd, karta_a=k)
        r.wynik("alfa", "2026-10-06-call", {"zrodlo": "ops/transkrypcje/alfa/2026-10-06-call.md", "spotkanie": {"data": "2026-10-06", "tytul": "Call statusowy"},
                                              "pozycje": [{}, {}], "zmiany_zdania": [{"temat": "Godziny soboty", "przed": "do 14:00", "po": "do 15:00", "cytat": "Jednak do piętnastej."}]})
        r.wynik("alfa", "2026-10-14-mail", {"zrodlo": "ops/maile/alfa/2026-10-14-plik.md", "spotkanie": {"data": "2026-10-14", "tytul": "Plik z leadami"}, "pozycje": [{}]})
        return r

    def test_na_gorze_teraz_z_trzema_listami_i_linkami_do_lineara(self):
        h = self._repo().strony()["klienci/alfa.html"]
        t = tekst(h)
        self.assertLess(t.index("Teraz"), t.index("Oś czasu"))
        self.assertRegex(t, r"Wymaga Ciebie 1.*Decyzja o Oplu")
        self.assertRegex(t, r"U agentów 1.*Poprawka godzin")
        self.assertRegex(t, r"Czeka na klienta 1.*Plik od klienta")
        self.assertIn('href="https://linear.app/ws/issue/RIN-2/opel"', h)

    def test_os_czasu_od_najnowszych_ze_wszystkimi_rodzajami(self):
        h = self._repo().strony()["klienci/alfa.html"]
        czas = h[h.index("Oś czasu"):h.index("Zakazy aktywne")]
        daty = re.findall(r"<time>(\d{4}-\d{2}-\d{2})</time>", czas)
        self.assertEqual(daty, sorted(daty, reverse=True))
        for rodzaj in ("Rozmowa", "Mail", "Zmiana zdania", "Wysłany mail", "Poprawka agenta", "Notatka", "Materiał"):
            self.assertIn(f'<span class="kind">{rodzaj}</span>', czas, rodzaj)
        self.assertIn('href="../wyniki/alfa/2026-10-06-call/raport.html"', czas, "link do raportu")
        self.assertIn('href="https://github.com/x/y/pull/7"', czas, "link do PR")
        self.assertIn('href="../ops/materialy/alfa/notatka-2026-10-15.pdf"', czas, "link do notatki")
        self.assertIn("do 14:00", czas)
        self.assertIn("Jednak do piętnastej.", czas)
        self.assertNotIn("Cudza poprawka", czas, "zdarzenia innych klientów nie wchodzą")

    def test_zakazy_aktywne_i_historia_uchylonych_z_cytatem(self):
        t = tekst(self._repo().strony()["klienci/alfa.html"])
        self.assertIn("Zakazy aktywne (1)", t)
        self.assertIn("Opla nie puszczamy.", t)
        self.assertIn("Uchylone zakazy (1)", t)
        self.assertIn("Nie testować wstępu", t)
        self.assertIn("Nie puszczajcie.", t)
        self.assertIn("Możecie puścić od jutra.", t)

    def test_ryzyka_z_liczba_wystapien_i_datami(self):
        t = tekst(self._repo().strony()["klienci/alfa.html"])
        self.assertIn("Konkurencja", t)
        self.assertIn("2 wystąpienia", t)
        self.assertIn("2026-10-06, 2026-10-13", t)
        self.assertIn("VoiceDesk jest tańszy.", t)

    def test_kontakty_i_decydenci_bez_adresow(self):
        t = tekst(self._repo().strony()["klienci/alfa.html"])
        self.assertIn("Kon Takt", t)
        self.assertIn("kontakt potwierdzony", t)
        self.assertIn("nieobecność 2026-10-19 – 2026-10-23", t)
        self.assertIn("Dec Ydent", t)

    def test_klient_bez_danych_ma_czytelne_puste_sekcje(self):
        t = tekst(Repo(karta_b=karta("beta", kontakty=[])).strony()["klienci/beta.html"])
        for fraza in ("Nic nie czeka na człowieka.", "Brak wpisów.", "Brak aktywnych zakazów.", "Brak zapisanych ryzyk.", "Brak potwierdzonych kontaktów w karcie."):
            self.assertIn(fraza, t)


def prosba(klient, cytat, data, zrodlo):
    return {"klient": klient, "cytat": cytat, "data": data, "zrodlo": zrodlo}


class TestGlosKlientow(unittest.TestCase):
    """Głos klientów: tylko sygnały (max 5), od najsilniejszego; reszta w „Pozostałe”."""

    def _repo(self, prosby, karta_a=None, karta_b=None, stan=None):
        r = Repo(stan=stan, prosby=prosby, karta_a=karta_a, karta_b=karta_b)
        return r.dane()

    def test_ratuje_klienta_gdy_prosba_dotyczy_tego_co_oferuje_konkurencja(self):
        ka = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk łączy się z systemem, więc leady same wpadają."}]})
        d = self._repo({"crm": {"tytul": "Integracja z CRM", "prosby": [prosba("alfa", "Chcemy integracji z naszym systemem.", "2026-10-06", "a.md")]}}, ka)
        sygn, reszta = gs.sygnaly(d)
        self.assertEqual([g["klucz"] for g in sygn], ["crm"])
        self.assertIn("uratuje", sygn[0]["typy"])
        self.assertIn("może uratować klienta", sygn[0]["powod"])
        self.assertIn("integracja z systemem klienta", sygn[0]["powod"])
        self.assertEqual(reszta, [])

    def test_bez_ryzyka_utraty_albo_bez_wspolnego_tematu_to_nie_ratunek(self):
        ka_bez = karta("alfa")
        d = self._repo({"crm": {"tytul": "Integracja z CRM", "prosby": [prosba("alfa", "Integracja z systemem.", "2026-10-06", "a.md")]}}, ka_bez)
        self.assertEqual(gs.sygnaly(d)[0], [], "klient bez ryzyka utraty")
        ka = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk łączy się z systemem."}]})
        d2 = self._repo({"x": {"tytul": "Kolor przycisku", "prosby": [prosba("alfa", "Zmieńcie kolor.", "2026-10-06", "a.md")]}}, ka)
        self.assertEqual(gs.sygnaly(d2)[0], [], "prośba o coś innego niż konkurencja")

    def test_rozlaczaja_nie_pasuje_do_laczenia_z_systemem(self):
        """Regresja: „rozłączają” zawiera „łącz”, a prośba o testy A/B nie dotyczy integracji."""
        ka = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk łączy się z systemem."}]})
        d = self._repo({"ab": {"tytul": "Testy A/B", "prosby": [prosba("alfa", "Ludzie rzadziej się rozłączają i częściej dochodzą do końca.", "2026-10-06", "a.md")]}}, ka)
        self.assertEqual(gs.sygnaly(d)[0], [])

    def test_prosi_co_najmniej_dwoch_klientow(self):
        d = self._repo({"xls": {"tytul": "Eksport do Excela", "prosby": [prosba("alfa", "Excel proszę.", "2026-10-13", "a.md"), prosba("beta", "Też Excel.", "2026-10-14", "b.md")]}})
        sygn, _ = gs.sygnaly(d)
        self.assertEqual(sygn[0]["typy"], ["wielu"])
        self.assertIn("prosi 2 klientów", sygn[0]["powod"])

    def test_ten_sam_klient_w_dwoch_roznych_zrodlach(self):
        d = self._repo({"rap": {"tytul": "Raport", "prosby": [prosba("alfa", "Raport.", "2026-10-06", "a.md"), prosba("alfa", "Raport jeszcze raz.", "2026-10-13", "b.md")]}})
        self.assertEqual(gs.sygnaly(d)[0][0]["typy"], ["powtarza"])
        d2 = self._repo({"rap": {"tytul": "Raport", "prosby": [prosba("alfa", "Raport.", "2026-10-06", "a.md"), prosba("alfa", "Raport drugi cytat.", "2026-10-06", "a.md")]}})
        self.assertEqual(gs.sygnaly(d2)[0], [], "dwa cytaty z jednej rozmowy to jedna prośba")

    def test_pojedyncze_prosby_zwiniete_w_pozostale(self):
        d = self._repo({"jedna": {"tytul": "Jedna prośba", "prosby": [prosba("alfa", "Cytat.", "2026-10-06", "a.md")]}})
        sygn, reszta = gs.sygnaly(d)
        self.assertEqual((sygn, [x["klucz"] for x in reszta]), ([], ["jedna"]))
        h = gs.strona_glos(d)
        self.assertIn("Pozostałe pojedyncze prośby (1)", h)
        self.assertIn("<details", h)
        self.assertIn("Brak sygnałów wartych decyzji", h)
        self.assertIn("Jedna prośba", tekst(h).split("Pozostałe pojedyncze prośby")[1][:60], "jedna linijka z tytułami")

    def test_maksymalnie_piec_sygnalow_najsilniejsze_pierwsze_reszta_do_pozostalych(self):
        prosby = {}
        for i in range(7):                                    # 7 sygnałów typu „wielu” o rosnącej liczbie próśb
            prosby[f"f{i}"] = {"tytul": f"Funkcja {i}", "prosby": [prosba("alfa", "c", "2026-10-06", "a.md"), prosba("beta", "c", "2026-10-07", "b.md")]
                               + [prosba("alfa", "c", "2026-10-08", f"x{i}{j}.md") for j in range(i)]}
        ka = karta("alfa", ryzyka={"konkurencja": [{"data": "2026-10-06", "zrodlo": "a.md", "cytat": "VoiceDesk łączy się z systemem."}]})
        prosby["crm"] = {"tytul": "Integracja", "prosby": [prosba("alfa", "Integracja z systemem.", "2026-10-06", "a.md")]}
        d = self._repo(prosby, ka)
        sygn, reszta = gs.sygnaly(d)
        self.assertEqual(len(sygn), 5)
        self.assertEqual(sygn[0]["klucz"], "crm", "ratunek jest najsilniejszy")
        self.assertEqual([g["klucz"] for g in sygn[1:]], ["f6", "f5", "f4", "f3"], "dalej wg liczby próśb")
        self.assertEqual({x["klucz"] for x in reszta}, {"f0", "f1", "f2"})

    def test_sygnal_ma_powod_klientow_cytat_i_status(self):
        stan = {"RIN-10": zg("[alfa] Eksport", stan="Done")}
        ka = karta("alfa", otwarte_sprawy={"s": {"identifier": "RIN-10"}})
        r = Repo(stan=stan, prosby={"xls": {"tytul": "Eksport do Excela", "prosby": [prosba("alfa", "Excel proszę.", "2026-10-13", "a.md"), prosba("beta", "Też Excel.", "2026-10-14", "b.md")]}}, karta_a=ka)
        r.wynik("alfa", "x", {"pozycje": [{"klucz_funkcji": "xls", "klucz_sprawy": "s"}]})
        h = gs.strona_glos(r.dane())
        t = tekst(h)
        self.assertIn("1 sygnał wart decyzji", t)
        self.assertRegex(t, r"Eksport do Excela\s+prosi 2 klientów\s+2\s+")
        self.assertIn("Cytat klienta", t)
        self.assertIn("Też Excel.", t)
        self.assertIn("<details>", h, "cytat zwinięty pod wierszem")
        self.assertIn("Propozycja", t)

    def test_nowe_sygnaly_pierwsze_uruchomienie_to_tylko_baza(self):
        d = self._repo({"xls": {"tytul": "Excel", "prosby": [prosba("alfa", "c", "2026-10-13", "a.md"), prosba("beta", "c", "2026-10-14", "b.md")]}})
        wyslane = []
        r = Repo(prosby=d["prosby"])
        dane = r.dane()
        self.assertEqual(gs.powiadom_o_sygnalach(dane, lambda t, l: wyslane.append(l) or True, r.root), [])
        self.assertEqual(wyslane, [], "pierwsze uruchomienie nie ogłasza")
        stan = json.loads((r.root / "ops/.sygnaly.json").read_text(encoding="utf-8"))
        self.assertEqual(stan["widziane"], ["xls|wielu"])

    def test_nowy_sygnal_jedna_linijka_raz_nie_codziennie(self):
        prosby = {"xls": {"tytul": "Excel", "prosby": [prosba("alfa", "c", "2026-10-13", "a.md"), prosba("beta", "c", "2026-10-14", "b.md")]}}
        r = Repo(prosby=prosby)
        r.zapisz("ops/.sygnaly.json", {"widziane": [], "zainicjowano": "2026-10-01"})
        wyslane = []
        wysylacz = lambda tekst_, linie: wyslane.append(linie) or True       # noqa: E731
        w1 = gs.powiadom_o_sygnalach(r.dane(), wysylacz, r.root)
        self.assertEqual(len(w1), 1)
        self.assertIn("Nowy sygnał w głosie klientów", w1[0])
        self.assertIn("Excel", w1[0])
        self.assertIn("rembolekk.github.io/Rinvo/glos-klientow.html", w1[0])
        w2 = gs.powiadom_o_sygnalach(r.dane(), wysylacz, r.root)             # następny przebieg: ten sam sygnał
        self.assertEqual((w2, len(wyslane)), ([], 1), "jednorazowo, nie codziennie")

    def test_nieudana_wysylka_nie_oznacza_sygnalu_jako_widzianego(self):
        prosby = {"xls": {"tytul": "Excel", "prosby": [prosba("alfa", "c", "2026-10-13", "a.md"), prosba("beta", "c", "2026-10-14", "b.md")]}}
        r = Repo(prosby=prosby)
        r.zapisz("ops/.sygnaly.json", {"widziane": [], "zainicjowano": "2026-10-01"})
        self.assertEqual(gs.powiadom_o_sygnalach(r.dane(), lambda t, l: False, r.root), [])
        self.assertEqual(json.loads((r.root / "ops/.sygnaly.json").read_text(encoding="utf-8"))["widziane"], [])
        self.assertEqual(len(gs.powiadom_o_sygnalach(r.dane(), lambda t, l: True, r.root)), 1, "kolejna próba się powiedzie")

    def test_nowy_typ_sygnalu_dla_znanej_prosby_tez_jest_nowy(self):
        prosby = {"xls": {"tytul": "Excel", "prosby": [prosba("alfa", "c", "2026-10-13", "a.md"), prosba("beta", "c", "2026-10-14", "b.md")]}}
        r = Repo(prosby=prosby)
        r.zapisz("ops/.sygnaly.json", {"widziane": ["xls|powtarza"], "zainicjowano": "2026-10-01"})
        self.assertEqual(len(gs.powiadom_o_sygnalach(r.dane(), lambda t, l: True, r.root)), 1)

    def test_bez_webhooka_stan_sie_nie_przesuwa(self):
        prosby = {"xls": {"tytul": "Excel", "prosby": [prosba("alfa", "c", "2026-10-13", "a.md"), prosba("beta", "c", "2026-10-14", "b.md")]}}
        r = Repo(prosby=prosby)
        r.zapisz("ops/.sygnaly.json", {"widziane": [], "zainicjowano": "2026-10-01"})
        gs.powiadom_o_sygnalach(r.dane(), None, r.root)
        self.assertEqual(json.loads((r.root / "ops/.sygnaly.json").read_text(encoding="utf-8"))["widziane"], [])


class TestOsCzasuPR(unittest.TestCase):

    def test_jedna_pozycja_na_pr_ze_statusem_koncowym(self):
        url = "https://github.com/x/y/pull/1"
        zd = [{"data": "2026-10-14T10:00:00+00:00", "typ": "pr_otwarty", "klient": "alfa", "zgloszenie": "RIN-1", "tytul": "Poprawka", "url": url},
              {"data": "2026-10-14T11:00:00+00:00", "typ": "pr_oddany", "klient": "alfa", "zgloszenie": "RIN-1", "tytul": "Poprawka", "url": url},
              {"data": "2026-10-14T12:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-1", "tytul": "Poprawka", "url": url},
              {"data": "2026-10-13T10:00:00+00:00", "typ": "pr_otwarty", "klient": "alfa", "zgloszenie": "RIN-2", "tytul": "Druga", "url": "https://github.com/x/y/pull/2"},
              {"data": "2026-10-13T10:00:00+00:00", "typ": "pr_otwarty", "klient": "alfa", "zgloszenie": "RIN-3", "tytul": "Trzecia", "url": "https://github.com/x/y/pull/3"},
              {"data": "2026-10-13T11:00:00+00:00", "typ": "pr_oddany", "klient": "alfa", "zgloszenie": "RIN-3", "tytul": "Trzecia", "url": "https://github.com/x/y/pull/3"}]
        d = Repo(zdarz=zd).dane()
        wpisy = [w for w in gs.os_czasu(d, d["klienci"]["alfa"]) if w[1] == "Poprawka agenta"]
        self.assertEqual(len(wpisy), 3, "trzy PR-y = trzy pozycje, a nie sześć etapów")
        po_url = {re.search(r"pull/(\d)", w[2]).group(1): w for w in wpisy}
        self.assertIn("scalona", po_url["1"][3])
        self.assertEqual(po_url["1"][0], "2026-10-14T12:00:00+00:00", "data scalenia")
        self.assertIn("otwarta", po_url["2"][3])
        self.assertIn("oddana człowiekowi", po_url["3"][3])


class TestZakazyCzasowe(unittest.TestCase):

    def test_okres_z_tytulu_i_cytatu_liczy_daty_py(self):
        import zakazy_czas as zc
        z = {"id": "Z11", "tytul": "Nie modyfikować maila w tygodniu 6–12.10", "cytat": []}
        o = zc.okres(z, date(2026, 10, 6))
        self.assertEqual((o["od"], o["do"]), (date(2026, 10, 6), date(2026, 10, 12)))
        o = zc.okres({"tytul": "Nic nowego podczas urlopu (2–6.11)", "cytat": []}, date(2026, 10, 13))
        self.assertEqual((o["od"], o["do"]), (date(2026, 11, 2), date(2026, 11, 6)))
        o = zc.okres({"tytul": "W tym tygodniu nic nowego", "cytat": []}, date(2026, 10, 13))      # wtorek: tydzień do piątku
        self.assertEqual(o["do"], date(2026, 10, 16))
        o = zc.okres({"tytul": "Nie zmieniać", "cytat": ["A od 19 do 23 października mam urlop."]}, date(2026, 10, 6))
        self.assertEqual((o["od"], o["do"]), (date(2026, 10, 19), date(2026, 10, 23)))

    def test_zakaz_bez_okresu_obowiazuje_zawsze(self):
        import zakazy_czas as zc
        for tytul in ("Limit prób pozostaje 5", "Nie puszczać Opla przed czwartkową rozmową we trzech", "Nie wysyłać wzoru pliku"):
            self.assertIsNone(zc.okres({"tytul": tytul, "cytat": ["Zostaw pięć."]}, date(2026, 10, 6)), tytul)

    def test_wygasa_po_ostatnim_dniu_okresu(self):
        import zakazy_czas as zc
        k = karta("alfa", zakazy=[{"id": "Z11", "tytul": "Nie ruszać w tygodniu 6–12.10", "cytat": []}, {"id": "Z1", "tytul": "Stały", "cytat": []}])
        self.assertEqual([z["id"] for z in zc.stan_zakazow(k, date(2026, 10, 12))[0]], ["Z11", "Z1"], "ostatni dzień okresu jeszcze obowiązuje")
        aktywne, wygasle = zc.stan_zakazow(k, date(2026, 10, 13))
        self.assertEqual(([z["id"] for z in aktywne], [z["id"] for z in wygasle]), (["Z1"], ["Z11"]))
        self.assertEqual(wygasle[0]["wygasl"], "2026-10-12")

    def test_przeniesienie_do_karty_zapisuje_okres_i_wygasle(self):
        import zakazy_czas as zc
        k = karta("alfa", zakazy=[{"id": "Z11", "tytul": "Nie ruszać w tygodniu 6–12.10", "cytat": []}, {"id": "Z5", "tytul": "Urlop 19–23.10", "cytat": []}])
        self.assertEqual(zc.przenies_wygasle(k, date(2026, 10, 14)), ["Z11"])
        self.assertEqual([z["id"] for z in k["zakazy"]], ["Z5"])
        self.assertEqual(k["zakazy_wygasle"][0]["wygasl"], "2026-10-12")
        self.assertEqual(k["zakazy"][0]["okres"]["do"], "2026-10-23", "okres aktywnego zakazu zapisany")
        self.assertEqual(zc.przenies_wygasle(k, date(2026, 10, 14)), [], "idempotentnie")

    def test_data_zrodla_z_nazwy_pliku_rozmowy_z_cytatem(self):
        import zakazy_czas as zc
        r = Repo()
        (r.root / "ops/transkrypcje/alfa").mkdir(parents=True)
        (r.root / "ops/transkrypcje/alfa/2026-10-13-call.md").write_text("**Kasia:** W tym tygodniu nic nowego poza testem wstępu.", encoding="utf-8")
        self.assertEqual(zc.data_zrodla_cytatu("alfa", ["W tym tygodniu nic nowego poza testem wstępu."], r.root), date(2026, 10, 13))
        z = {"id": "Z18", "tytul": "W tym tygodniu nic nowego", "cytat": ["W tym tygodniu nic nowego poza testem wstępu."]}
        self.assertEqual(zc.okres_zakazu(z, "alfa", r.root)["do"], date(2026, 10, 16))

    def test_strona_klienta_ma_sekcje_wygaslych_i_aktywne_bez_nich(self):
        k = karta("alfa", zakazy=[{"id": "Z11", "tytul": "Nie ruszać w tygodniu 6–12.10", "cytat": ["Ale nie w tym tygodniu."]},
                                   {"id": "Z1", "tytul": "Stały zakaz", "cytat": ["Tak zostaje."]}])
        t = tekst(Repo(karta_a=k).strony()["klienci/alfa.html"])
        self.assertIn("Zakazy aktywne (1)", t)
        self.assertIn("Wygasłe zakazy (1)", t)
        self.assertRegex(t, r"Wygasłe zakazy \(1\).*Z11.*wygasł 2026-10-12.*Okres: 2026-10-06 – 2026-10-12")
        self.assertLess(t.index("Stały zakaz"), t.index("Wygasłe zakazy"))

    def test_karta_z_zapisanymi_wygaslymi_pokazuje_je_na_stronie(self):
        k = karta("alfa", zakazy=[], zakazy_wygasle=[{"id": "Z9", "tytul": "Stary", "cytat": ["x"], "wygasl": "2026-10-01", "okres": {"od": "2026-09-25", "do": "2026-10-01", "skad": "25.09–01.10"}}])
        self.assertIn("Wygasłe zakazy (1)", tekst(Repo(karta_a=k).strony()["klienci/alfa.html"]))

    def test_prawdziwa_karta_auto_tama_z11_wygasl_z5_i_z18_jeszcze_nie(self):
        import zakazy_czas as zc
        k = json.loads((MIGAWKA / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        # karta w repo ma już Z11 w wygasłych; sprawdzamy stan na 14.10 i po 16.10
        ids = lambda lista: {z["id"] for z in lista}      # noqa: E731
        a, w = zc.stan_zakazow(k, date(2026, 10, 14), "auto-tama", MIGAWKA)
        self.assertIn("Z11", ids(w))
        self.assertTrue({"Z5", "Z18", "Z1"} <= ids(a))
        a, w = zc.stan_zakazow(k, date(2026, 10, 17), "auto-tama", ROOT)
        self.assertIn("Z18", ids(w))
        self.assertIn("Z5", ids(a))


class TestDatyZrodlaRyzyk(unittest.TestCase):

    def test_ryzyko_i_prosba_dostaja_date_zrodla_a_nie_przetwarzania(self):
        import linear_sync as ls
        karta_ = {}
        item = {"temat_ryzyka": "konkurencja", "cytat": ["VoiceDesk jest tańszy."]}
        ls.update_risk_counter(karta_, item, "ops/transkrypcje/alfa/2026-10-06-call.md", "2026-10-13")
        ls.update_risk_counter(karta_, item | {"cytat": ["Oferta na piśmie."]}, "ops/transkrypcje/alfa/2026-10-13-call.md", "2026-10-14")
        self.assertEqual([x["data"] for x in karta_["ryzyka"]["konkurencja"]], ["2026-10-06", "2026-10-13"])
        prosby = {}
        ls.update_prosby(prosby, {"klucz_funkcji": "xls", "tytul": "Excel", "cytat": ["Excel."]}, "alfa", "ops/transkrypcje/alfa/2026-10-06-call.md", "2026-10-13")
        self.assertEqual(prosby["xls"]["prosby"][0]["data"], "2026-10-06")

    def test_zrodlo_bez_daty_w_nazwie_uzywa_dnia_przetwarzania(self):
        import linear_sync as ls
        karta_ = {}
        ls.update_risk_counter(karta_, {"temat_ryzyka": "inne", "cytat": ["x"]}, "src.md", "2026-10-13")
        self.assertEqual(karta_["ryzyka"]["inne"][0]["data"], "2026-10-13")

    def test_dane_w_repozytorium_maja_daty_zrodel_voicedesk_0610_i_1310(self):
        k = json.loads((MIGAWKA / "ops/klienci/auto-tama/karta.json").read_text(encoding="utf-8"))
        wpisy = k["ryzyka"]["konkurencja"]
        self.assertEqual(sorted({w["data"] for w in wpisy}), ["2026-10-06", "2026-10-13"])
        for temat, w in k["ryzyka"].items():
            for x in w:
                self.assertIn(x["data"], x["zrodlo"], f"{temat}: data wpisu = data źródła")
        for klucz, p in json.loads((MIGAWKA / "ops/produkt/prosby.json").read_text(encoding="utf-8")).items():
            for x in p["prosby"]:
                self.assertIn(x["data"], x["zrodlo"], klucz)

    def test_na_stronie_ryzyko_ma_daty_zrodel(self):
        t = tekst(gs.strona_klienta(gs.wczytaj_dane(MIGAWKA, DZIS), gs.wczytaj_dane(MIGAWKA, DZIS)["klienci"]["auto-tama"]))
        self.assertIn("2026-10-06, 2026-10-13", t)
        self.assertNotIn("2026-10-13, 2026-10-14", t)


class TestAgenciTydzien(unittest.TestCase):
    """ZMIANA ŚWIADOMA: czas liczymy od WPŁYNIĘCIA rozmowy albo maila do systemu (pole „wplynelo” w ops/.przetworzone.json, czyli czas commita),
    a nie od daty rozmowy z nazwy pliku."""

    def _repo(self):
        stan = {"RIN-1": {**zg("[alfa] Szybka", stan="Done"), "zamknieto": "2026-10-14T10:00:00Z"},
                "RIN-2": {**zg("[alfa] Wolna", stan="Done"), "zamknieto": "2026-10-13T10:00:00Z"},
                "RIN-3": {**zg("[alfa] Stara", stan="Done"), "zamknieto": "2026-09-01T10:00:00Z"},
                "RIN-4": zg("[alfa] Otwarta")}
        zd = [{"data": "2026-10-14T10:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-1", "tytul": "Szybka", "url": "https://github.com/x/y/pull/1"},
              {"data": "2026-10-14T10:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-2", "tytul": "Wolna", "url": "https://github.com/x/y/pull/2"},
              {"data": "2026-09-02T10:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-3", "tytul": "Stara", "url": "https://github.com/x/y/pull/3"}]
        ka = karta("alfa", otwarte_sprawy={"a": {"identifier": "RIN-1", "zrodla": ["ops/transkrypcje/alfa/2026-10-13-call.md"]},
                                            "b": {"identifier": "RIN-2", "zrodla": ["ops/transkrypcje/alfa/2026-10-06-call.md", "ops/transkrypcje/alfa/2026-10-13-call.md"]},
                                            "c": {"identifier": "RIN-3", "zrodla": ["ops/transkrypcje/alfa/2026-08-30-call.md"]}})
        r = Repo(stan=stan, zdarz=zd, karta_a=ka)
        # wpłynęły w innych momentach niż sugerują daty w nazwach plików
        r.zapisz("ops/.przetworzone.json", {
            "h1": {"klient": "alfa", "transkrypcja": "ops/transkrypcje/alfa/2026-10-13-call.md", "wplynelo": "2026-10-14T09:00:00+02:00"},
            "h2": {"klient": "alfa", "transkrypcja": "ops/transkrypcje/alfa/2026-10-06-call.md", "wplynelo": "2026-10-13T08:00:00+00:00"},
            "h3": {"klient": "alfa", "transkrypcja": "ops/transkrypcje/alfa/2026-08-30-call.md", "wplynelo": "2026-09-01T08:00:00+00:00"}})
        return r

    def test_zamkniete_scalone_srednia_i_najkrotszy_czas(self):
        st = gs.statystyki_agentow(self._repo().dane())
        self.assertEqual(st["zamkniete"], 2, "tylko ostatnie 7 dni")
        self.assertEqual(st["scalone"], 2)
        czasy = {p["zgloszenie"]: p["czas"] for p in st["pomiary"]}
        # RIN-1: wpłynęło 14.10 09:00 PL (07:00 UTC) → scalone 10:00 UTC = 3 h; RIN-2: najwcześniejsze wpłynięcie 13.10 08:00 UTC → 26 h
        self.assertEqual(gs.formatuj_czas(czasy["RIN-1"]), "3 h 0 min")
        self.assertEqual(gs.formatuj_czas(czasy["RIN-2"]), "1 d 2 h")

    def test_czas_nie_zalezy_od_daty_rozmowy_z_nazwy_pliku(self):
        r = self._repo()
        r.zapisz("ops/.przetworzone.json", {"h1": {"klient": "alfa", "transkrypcja": "ops/transkrypcje/alfa/2026-10-13-call.md", "wplynelo": "2026-10-14T09:30:00+00:00"}})
        czasy = {p["zgloszenie"]: p["czas"] for p in gs.statystyki_agentow(r.dane())["pomiary"]}
        self.assertEqual(gs.formatuj_czas(czasy["RIN-1"]), "30 min", "od wpłynięcia, nie od 13.10")

    def test_zrodlo_bez_zapisanego_wplyniecia_nie_jest_mierzone_po_dacie_z_nazwy(self):
        r = self._repo()
        r.zapisz("ops/.przetworzone.json", {})
        self.assertEqual(gs.statystyki_agentow(r.dane())["scalone"], 0)

    def test_zdanie_o_agentach_na_stronie_glownej(self):
        r = self._repo()
        h = gs.strona_index(r.dane())
        t = tekst(h)
        self.assertIn("Agenci w tym tygodniu: 2 sprawy zamknięte, poprawka średnio w 14 h 30 min od wpłynięcia rozmowy", t, "średnia z 3 h i 26 h")
        self.assertEqual(t.lower().count("od wpłynięcia rozmowy"), 2, "w zdaniu o agentach i w nagłówku zwiniętej listy; bez zdublowanego podpisu pod zdaniem")
        self.assertNotIn("do wdrożonej poprawki", t)
        self.assertIn('href="https://github.com/x/y/pull/1"', h, "szczegóły w zwiniętej liście poprawek")

    def test_brak_scalonych_poprawek_to_czytelne_zdanie(self):
        t = tekst(gs.strona_index(Repo().dane()))
        self.assertIn("Agenci w tym tygodniu: 0 spraw zamkniętych, jeszcze bez scalonej poprawki", t)

    def test_poprawka_bez_znanego_zrodla_nie_psuje_statystyk(self):
        r = self._repo()
        r.zapisz("ops/.zdarzenia.json", [{"data": "2026-10-14T10:00:00+00:00", "typ": "pr_scalony", "klient": "alfa", "zgloszenie": "RIN-99", "tytul": "?", "url": "u"}])
        self.assertEqual(gs.statystyki_agentow(r.dane())["scalone"], 0)

    def test_przetworz_zapisuje_wplyniecie_w_rejestrze(self):
        kod = (ROOT / "przetworz.py").read_text(encoding="utf-8")
        self.assertEqual(kod.count("wplyniecia.czas_wplyniecia(transkrypcja)"), 2)


class TestStanIDziennik(unittest.TestCase):

    def test_pobierz_stan_z_paginacja_i_zapis_odczyt(self):
        strony = [{"issues": {"nodes": [{"identifier": "RIN-1", "title": "[a] X", "url": "u1", "priority": 0, "createdAt": "c", "updatedAt": "u", "completedAt": None,
                                          "dueDate": "2026-10-20", "state": {"name": "Todo", "type": "unstarted"}, "labels": {"nodes": [{"name": "Dla agenta"}]}}],
                              "pageInfo": {"hasNextPage": True, "endCursor": "k1"}}},
                  {"issues": {"nodes": [{"identifier": "RIN-2", "title": "[a] Y", "url": "u2", "priority": 1, "createdAt": "c", "updatedAt": "u", "completedAt": "z",
                                          "dueDate": None, "state": {"name": "Done", "type": "completed"}, "labels": {"nodes": []}}],
                              "pageInfo": {"hasNextPage": False, "endCursor": None}}}]
        wywolania = []
        gql = lambda k, q, v=None: (wywolania.append(v), strony[len(wywolania) - 1])[1]       # noqa: E731
        wynik = stan_linear.pobierz("k", gql)
        self.assertEqual(sorted(wynik), ["RIN-1", "RIN-2"])
        self.assertEqual([w["after"] for w in wywolania], [None, "k1"])
        self.assertEqual((wynik["RIN-1"]["stan"], wynik["RIN-1"]["etykiety"], wynik["RIN-1"]["termin"]), ("Todo", ["Dla agenta"], "2026-10-20"))
        with tempfile.TemporaryDirectory() as t:
            plik = Path(t) / "stan.json"
            stan_linear.zapisz(wynik, plik, datetime(2026, 10, 14, 12, tzinfo=timezone.utc))
            self.assertEqual(stan_linear.wczytaj(plik)["zgloszenia"]["RIN-2"]["zamknieto"], "z")
            self.assertEqual(stan_linear.wczytaj(plik)["zapisano"], "2026-10-14T12:00:00+00:00")

    def test_brak_pliku_stanu_to_pusty_stan_a_nie_blad(self):
        self.assertEqual(stan_linear.wczytaj(Path("/nie/ma/takiego.json")), {"zapisano": None, "zgloszenia": {}})

    def test_po_przebiegu_nie_przerywa_przy_bledzie(self):
        import linear_sync
        oryginal = linear_sync.load_api_key
        linear_sync.load_api_key = lambda: (_ for _ in ()).throw(SystemExit("brak klucza"))
        try:
            stan_linear.po_przebiegu()          # nie rzuca
        finally:
            linear_sync.load_api_key = oryginal

    def test_dziennik_dopisuje_bez_duplikatow(self):
        with tempfile.TemporaryDirectory() as t:
            d = zdarzenia.Dziennik(Path(t) / "z.json")
            self.assertTrue(d.dodaj("pr_otwarty", "alfa", "RIN-1", "Poprawka", "https://github.com/x/y/pull/1"))
            self.assertFalse(d.dodaj("pr_otwarty", "alfa", "RIN-1", "Poprawka", "https://github.com/x/y/pull/1"))
            self.assertTrue(d.dodaj("pr_scalony", "alfa", "RIN-1", "Poprawka", "https://github.com/x/y/pull/1"))
            self.assertEqual(len(zdarzenia.wczytaj(Path(t) / "z.json")), 2)

    def test_zapisz_zdarzenie_bez_dziennika_nic_nie_robi(self):
        class S:
            pass
        zdarzenia.zapisz_zdarzenie(S(), "pr_otwarty", "alfa", "RIN-1", "x")            # brak s.zdarzenia: bez błędu


class TestPrawdziweDane(unittest.TestCase):

    def test_generowanie_z_danych_repozytorium(self):
        d = gs.wczytaj_dane(MIGAWKA, DZIS)
        s = gs.buduj(d)
        self.assertIn("klienci/auto-tama.html", s)
        self.assertIn("klienci/klinika-usmiech.html", s)
        for sciezka, h in s.items():
            self.assertIn("Dane fikcyjne, demo", h, sciezka)
            self.assertNotIn("@gmail.com", h, sciezka)
        self.assertIn("Grupa Auto Tama", s["index.html"])
        self.assertIn("Klinika Uśmiech", s["index.html"])
        self.assertIn("VoiceDesk", s["klienci/auto-tama.html"])

    def test_workflowy_odswiezaja_strony_i_commituja_je_z_wynikami(self):
        for nazwa in ("przetworz-rozmowy", "sprawdz-maile", "agent", "podsumowanie"):
            t = (ROOT / f".github/workflows/{nazwa}.yml").read_text(encoding="utf-8")
            self.assertIn("python3 generuj_strony.py", t, nazwa)
            self.assertIn("glos-klientow.html", t, nazwa)
            self.assertIn("ops/.stan_linear.json", t, nazwa)


if __name__ == "__main__":
    unittest.main(verbosity=1)
