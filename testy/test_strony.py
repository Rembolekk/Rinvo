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
        self.assertEqual([z["id"] for z in s["czlowiek"]], ["RIN-2"])
        self.assertEqual([z["id"] for z in s["czeka"]], ["RIN-3", "RIN-7"], "czekanie na klienta liczy się także w backlogu")
        self.assertEqual([z["id"] for z in s["backlog"]], ["RIN-4"])
        self.assertEqual([z["id"] for z in s["zamkniete"]], ["RIN-5"])

    def test_liczby_na_stronie_glownej(self):
        stan = {"RIN-1": zg("[alfa] A", etykiety=["Dla agenta"]), "RIN-2": zg("[alfa] A2", etykiety=["Dla agenta"]),
                "RIN-3": zg("[alfa] B", etykiety=["Decyzja człowieka"]), "RIN-4": zg("[alfa] C", etykiety=["Czeka na klienta"])}
        h = Repo(stan=stan).strony()["index.html"]
        karta_alfa = re.search(r'href="klienci/alfa\.html">.*?</a>', h, re.S).group(0)
        self.assertRegex(karta_alfa, r"<b>2</b>u agentów")
        self.assertRegex(karta_alfa, r"<b>1</b>u człowieka")
        self.assertRegex(karta_alfa, r"<b>1</b>czeka na klienta")


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
        self.assertRegex(t, r"Wymaga człowieka \(1\).*Decyzja o Oplu")
        self.assertRegex(t, r"U agentów \(1\).*Poprawka godzin")
        self.assertRegex(t, r"Czeka na klienta \(1\).*Plik od klienta")
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


class TestGlosKlientow(unittest.TestCase):

    def _dane(self):
        prosby = {
            "excel": {"tytul": "Eksport do Excela", "prosby": [{"klient": "alfa", "cytat": "Chcemy Excela.", "data": "2026-10-13"}, {"klient": "beta", "cytat": "Też Excel.", "data": "2026-10-14"}]},
            "kafelki": {"tytul": "Klikalne kafelki", "prosby": [{"klient": "alfa", "cytat": "Kafelek nie klika.", "data": "2026-10-06"}]},
            "raport": {"tytul": "Raport mailowy", "prosby": [{"klient": "alfa", "cytat": "Raport proszę.", "data": "2026-10-13"}, {"klient": "alfa", "cytat": "Raport jeszcze raz.", "data": "2026-10-20"}]},
        }
        stan = {"RIN-10": zg("[alfa] Eksport do Excela", stan="Backlog", etykiety=["Produkt"], url="https://linear.app/ws/issue/RIN-10/x"),
                "RIN-11": zg("[alfa] Klikalne kafelki", stan="Done"), "RIN-12": zg("[alfa] Raport mailowy", etykiety=["Dla agenta"])}
        ka = karta("alfa", otwarte_sprawy={"excel-s": {"identifier": "RIN-10"}, "raport-s": {"identifier": "RIN-12"}},
                   zamkniete_sprawy={"kafelki-s": {"identifier": "RIN-11"}})
        r = Repo(stan=stan, prosby=prosby, karta_a=ka)
        r.wynik("alfa", "x", {"pozycje": [{"klucz_funkcji": "excel", "klucz_sprawy": "excel-s"}, {"klucz_funkcji": "kafelki", "klucz_sprawy": "kafelki-s"},
                                           {"klucz_funkcji": "raport", "klucz_sprawy": "raport-s"}]})
        return r.dane()

    def test_sortowanie_wg_liczby_klientow_potem_prosb(self):
        lista = gs.prosby_posortowane(self._dane())
        self.assertEqual([x["klucz"] for x in lista], ["excel", "raport", "kafelki"])

    def test_statusy_backlog_u_agenta_zrobione(self):
        lista = {x["klucz"]: x for x in gs.prosby_posortowane(self._dane())}
        self.assertEqual(lista["excel"]["status"], "backlog")
        self.assertEqual(lista["raport"]["status"], "u agenta")
        self.assertEqual(lista["kafelki"]["status"], "zrobione")

    def test_daty_pierwszej_i_ostatniej_prosby_oraz_cytaty_na_stronie(self):
        d = self._dane()
        x = next(x for x in gs.prosby_posortowane(d) if x["klucz"] == "raport")
        self.assertEqual((x["pierwsza"], x["ostatnia"]), ("2026-10-13", "2026-10-20"))
        t = tekst(gs.strona_glos(d))
        self.assertIn("2 klientów", t)
        self.assertIn("pierwsza prośba 2026-10-13", t)
        self.assertIn("ostatnia 2026-10-20", t)
        self.assertIn("Też Excel.", t)
        self.assertIn('href="https://linear.app/ws/issue/RIN-10/x"', gs.strona_glos(d))

    def test_prosba_bez_zgloszenia_w_lineara_jest_w_backlogu(self):
        d = self._dane()
        d["prosby"]["nowa"] = {"tytul": "Nowa", "prosby": [{"klient": "alfa", "cytat": "x", "data": "2026-10-14"}]}
        self.assertEqual({x["klucz"]: x["status"] for x in gs.prosby_posortowane(d)}["nowa"], "backlog")


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
        d = gs.wczytaj_dane(ROOT, DZIS)
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
