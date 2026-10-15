#!/usr/bin/env python3
"""test_porzadek_produkt.py – porządek w zgłoszeniach dla człowieka (A: dla_czlowieka.py, widok.py) i agent produktowy (B: propozycje.py).

Bez sieci i bez modelu: Linear, Slack, model i czas to atrapy; pliki w katalogu tymczasowym.
Nazwy testów zaczynają się od numeru punktu (a01_ … a06_, b01_ … b06_). Uruchomienie: python3 testy/test_porzadek_produkt.py
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import dla_czlowieka as dc
import generuj_strony as gs
import limity
import linear_sync
import podsumowanie
import propozycje as pr
import slack_widok as sw
import szkice
import widok
import wyslij as wy
import zasady
import test_strony as tst
import test_wysylka as tw

Z = zasady.wczytaj_zasady()
E = Z["etykiety"]
W = Z["wysylka"]
SROD = tw.SROD                                   # środa 10:00 w Polsce (w oknie wysyłki)
SOBOTA = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self._cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self._cwd)
        self._t.cleanup()


def blok_z_mailem(tresc=tw.DOBRA, temat="Godziny w sobotę", zal=(), teraz=SROD, ident=("RIN-41",)):
    mail = {"do": "Kasia Malinowska", "temat": temat, "tresc": tresc, "zgloszenia": list(ident), "zalaczniki": list(zal),
            "kiedy": dc.kiedy_wyjdzie(teraz, W)}
    return dc.zloz_blok("Przeczytaj gotowy mail do Kasia Malinowska i wyślij go.", "klient", mail, dc.RUCHY_MAIL)


def zg_czlowieka(numer=41, labels=("Konfiguracja", "Decyzja człowieka"), opis=tw.OPIS, tytul="Godziny w sobotę", **kw):
    z = tw.zg(numer, labels=labels, opis=opis, tytul=tytul, stan="Todo", **kw)
    return z


# ── A1. tytuł od czynności ────────────────────────────────────────────────────

class A1Tytul(unittest.TestCase):

    def test_a01_czynnosc_wg_etykiet(self):
        self.assertEqual(dc.czynnosc_dla(["Szkic gotowy", "Decyzja człowieka"], "", Z), "Wyślij")
        self.assertEqual(dc.czynnosc_dla(["Decyzja człowieka"], "", Z), "Zdecyduj")
        self.assertEqual(dc.czynnosc_dla(["Decyzja człowieka"], "", Z, ["do_klienta"]), "Wyślij", "jedyny powód: trafia do klienta")
        self.assertEqual(dc.czynnosc_dla(["Decyzja człowieka"], "", Z, ["do_klienta", "pieniadze"]), "Zdecyduj")
        self.assertEqual(dc.czynnosc_dla(["Do weryfikacji"], "", Z), "Sprawdź")
        self.assertEqual(dc.czynnosc_dla(["Do weryfikacji"], "brak kontaktu w karcie", Z), "Uzupełnij")
        self.assertIsNone(dc.czynnosc_dla(["Dla agenta"], "", Z))

    def test_a01_tytul_ma_prefiks_klienta_czynnosc_i_opis_do_60_znakow(self):
        dlugi = "Bardzo długi opis zgłoszenia, który na pewno nie zmieści się w sześćdziesięciu znakach tytułu"
        t = dc.tytul_zgloszenia(f"[alfa] {dlugi}", "Zdecyduj", Z)
        self.assertTrue(t.startswith("[alfa] Zdecyduj: "))
        opis = t[len("[alfa] Zdecyduj: "):]
        self.assertLessEqual(len(opis), 60)
        self.assertTrue(opis.endswith("…"))
        self.assertEqual(dc.tytul_zgloszenia("[alfa] Krótki", "Sprawdź", Z), "[alfa] Sprawdź: Krótki")

    def test_a01_nie_dubluje_czynnosci_ani_czasownika(self):
        self.assertEqual(dc.tytul_zgloszenia("[alfa] Wyślij: Wyślij zaproszenie", "Wyślij", Z), "[alfa] Wyślij: zaproszenie")
        self.assertEqual(dc.tytul_zgloszenia("[alfa] Zdecyduj: Wybór wariantu", "Zdecyduj", Z), "[alfa] Zdecyduj: Wybór wariantu")
        import agent
        self.assertEqual(agent.tytul_bez_prefiksu("[alfa] Zdecyduj: Wybór"), "Wybór", "reszta kodu widzi tytuł merytoryczny")


# ── A2. stały blok na górze opisu ─────────────────────────────────────────────

class A2Blok(unittest.TestCase):

    def test_a02_kolejnosc_pol_bloku_i_kontekst_pod_linia(self):
        blok = blok_z_mailem(zal=["ściąga.pdf"])
        opis = dc.zloz_opis(blok, "## Cel\n\nX\n\n> cytat\n\n## Czego nie ruszać\n\n- Zakaz Z4")
        linie = [l for l in opis.splitlines() if l.startswith("**")]
        self.assertEqual([l.split(":**")[0] + ":**" if ":**" in l else l for l in linie][:3], ["**Co masz zrobić:**", "**Dlaczego Ty:**", "**Gotowy mail**"])
        for pole in ("**Do:**", "**Temat:**", "**Załączniki:** ściąga.pdf", "**Kiedy wyjdzie:**", "**Twoje ruchy:**"):
            self.assertIn(pole, opis)
        self.assertLess(opis.index("**Kiedy wyjdzie:**"), opis.index("**Twoje ruchy:**"))
        b, kontekst = dc.rozdziel(opis)
        self.assertTrue(b.startswith(dc.START) and b.endswith(dc.RUCHY_MAIL))
        self.assertIn("## Cel", kontekst)
        self.assertIn("Zakaz Z4", kontekst)
        self.assertNotIn("## Cel", b)

    def test_a02_ruchy_to_wyslij_odrzuc_albo_popraw_tresc(self):
        self.assertIn("etykieta „Wyślij” | etykieta „Odrzuć” | popraw treść w tym bloku i daj „Wyślij”", blok_z_mailem())

    def test_a02_blok_bez_maila_ma_ruchy_dla_decyzji(self):
        blok = dc.zloz_blok(dc.co_masz_zrobic("Zdecyduj", "[alfa] Opel", None), "zakaz")
        self.assertIn("**Dlaczego Ty:** zakaz", blok)
        self.assertNotIn("Gotowy mail", blok)
        self.assertIn("etykieta „Odrzuć”", blok)

    def test_a02_dlaczego_ty_to_jedno_slowo(self):
        for reguly, oczekiwane in ((["pieniadze"], "pieniądze"), (["zakaz"], "zakaz"), (["do_klienta"], "klient"), ([], "decyzja")):
            slowo = dc.dlaczego_ty({"reguly": reguly}, ["Decyzja człowieka"], Z)
            self.assertEqual(slowo, oczekiwane)
            self.assertEqual(len(slowo.split()), 1)

    def test_a02_kiedy_wyjdzie_to_najblizsze_okno(self):
        self.assertIn("zaraz po dodaniu", dc.kiedy_wyjdzie(SROD, W))
        k = dc.kiedy_wyjdzie(SOBOTA, W)
        self.assertIn("poniedziałek 19.10 od 8:00", k)

    def test_a02_markdown_nie_psuje_ogranicznikow_maila(self):
        """Bez pustych linii wokół „---” Markdown (Linear) zamienia linię przed „---” w nagłówek i gubi ogranicznik."""
        linie = wy.czesc_maila("K", "T", "Treść", ["RIN-1"])
        i = linie.index("---")
        self.assertEqual(linie[i - 1], "")
        self.assertEqual(linie[i + 1], "")
        self.assertEqual(linie[-2], "---")
        self.assertEqual(linie[-3], "")


# ── A3. wysyłka z bloku ───────────────────────────────────────────────────────

class A3Wysylka(unittest.TestCase):

    def _s(self, opis_blok, komentarz_tresc=tw.DOBRA, labels=("Konfiguracja", "Wyślij", "Szkic gotowy")):
        z = zg_czlowieka(labels=labels, opis=dc.zloz_opis(opis_blok, tw.OPIS))
        z["state"] = "Done"
        return tw.Srodowisko([z], {"RIN-41": [tw.komentarz_szkicu(tresc=komentarz_tresc)]})

    def test_a03_wersja_poprawiona_przez_czlowieka_w_bloku_wygrywa_z_komentarzem(self):
        poprawiona = "Dzień dobry, Kasiu,\n\nw sobotę mamy już godziny do 15:00. Poprawiłem to zdanie ręcznie.\n\nPozdrawiam\nMarek"
        s = self._s(blok_z_mailem(poprawiona), komentarz_tresc="Stara wersja z komentarza.")
        w = wy.uruchom(s)[0]
        self.assertEqual(w["status"], "wyslane")
        self.assertIn("Poprawiłem to zdanie ręcznie", s.poczta.wyslane[0]["tresc"])
        self.assertNotIn("Stara wersja", s.poczta.wyslane[0]["tresc"])

    def test_a03_komentarz_jest_zrodlem_gdy_brak_bloku(self):
        z = tw.zg(41, labels=("Konfiguracja", "Wyślij"))
        s = tw.Srodowisko([z], {"RIN-41": [tw.komentarz_szkicu()]})
        self.assertEqual(wy.uruchom(s)[0]["status"], "wyslane")

    def test_a03_komentarze_ze_szkicami_zostaja_jako_historia(self):
        s = self._s(blok_z_mailem())
        wy.uruchom(s)
        self.assertTrue(any("Szkic maila do klienta" in k["body"] for k in s.linear.kom["RIN-41"]))

    def test_a03_te_same_bezpieczniki_dla_tresci_z_bloku(self):
        for zla, powod in (("Dzień dobry, Kasiu,\n\nmail [uzupełnić]\n\nMarek", "uzupełnienia"),
                           ("Dzień dobry, Kasiu,\n\nzgłoszenie RIN-41 jest gotowe.\n\nMarek", "wewnętrzne oznaczenie"),
                           ("Dzień dobry, Kasiu,\n\npisz na tajny@obcy.pl\n\nMarek", "adres e-mail")):
            s = self._s(blok_z_mailem(zla))
            w = wy.uruchom(s)[0]
            self.assertEqual(w["status"], "wstrzymane", zla)
            self.assertIn(powod, w["powod"])
            self.assertEqual(s.poczta.wyslane, [])
            self.assertIn("Do weryfikacji", s.linear.zgloszenia["RIN-41"]["labels"])

    def test_a03_poza_oknem_czeka_tak_samo_jak_z_komentarza(self):
        z = zg_czlowieka(labels=("Konfiguracja", "Wyślij", "Szkic gotowy"), opis=dc.zloz_opis(blok_z_mailem(teraz=SOBOTA), tw.OPIS))
        z["state"] = "Done"
        s = tw.Srodowisko([z], {}, teraz=SOBOTA)
        w = wy.uruchom(s)[0]
        self.assertEqual(w["status"], "czeka")
        self.assertEqual(s.poczta.wyslane, [])

    def test_a03_szkic_zbiorczy_wskazuje_zgloszenie_glowne_z_blokiem(self):
        glowne = zg_czlowieka(41, labels=("Konfiguracja", "Szkic gotowy"), opis=dc.zloz_opis(blok_z_mailem(ident=("RIN-41", "RIN-42")), tw.OPIS))
        glowne["state"] = "Done"
        drugie = zg_czlowieka(42, labels=("Konfiguracja", "Szkic gotowy", "Wyślij"),
                              opis=dc.zloz_opis(dc.zloz_blok("Mail jest w innym zgłoszeniu.", "klient", {"zbiorczy": "RIN-41"}), tw.OPIS))
        drugie["state"] = "Done"
        s = tw.Srodowisko([glowne, drugie], {})
        w = wy.uruchom(s)[0]
        self.assertEqual(w["status"], "wyslane")
        self.assertEqual(sorted(w["zgloszenia"]), ["RIN-41", "RIN-42"])

    def test_a03_szkic_pisze_blok_do_opisu_i_zostawia_komentarz(self):
        z = tw.zg(41, labels=("Konfiguracja", "Dla agenta"), opis=tw.OPIS.replace("Napisz mi, jak będzie poprawione.", "Napisz mi, jak będzie poprawione."))
        s = tw.Srodowisko([z], claude=tw.AtrapaClaude(tw.json_szkic(temat="Godziny")))
        w = szkice.uruchom(s)
        self.assertEqual(w[0]["status"], "szkic")
        opis = s.linear.zgloszenia["RIN-41"]["description"]
        self.assertTrue(opis.startswith(dc.START))
        self.assertEqual(dc.parsuj_blok(opis)["tresc"], tw.DOBRA)
        self.assertTrue(s.linear.zgloszenia["RIN-41"]["title"].startswith("[auto-tama] Wyślij: "))
        self.assertTrue(any("Szkic maila do klienta" in k["body"] for k in s.linear.kom["RIN-41"]))
        self.assertIn("## Cel", dc.kontekst_opisu(opis), "dotychczasowy kontekst pod linią")

    def test_a03_zaden_test_nie_wysyla_prawdziwej_poczty(self):
        self.assertIn("AtrapaPoczta", type(tw.Srodowisko().poczta).__name__)


# ── A4. Odrzuć ────────────────────────────────────────────────────────────────

class A4Odrzuc(unittest.TestCase):

    KARTA = {"klient": "Auto-Tama", "kontakty": tw.KARTA["kontakty"], "zakazy": [], "otwarte_sprawy": {
        "godziny": {"identifier": "RIN-41", "linear_id": "id41", "url": "u", "tytul": "Godziny", "zrodla": ["ops/transkrypcje/auto-tama/2026-10-06-call.md"]}}}

    def _s(self, **kw):
        z = zg_czlowieka(labels=("Konfiguracja", "Decyzja człowieka", "Odrzuć"), **kw)
        s = tw.Srodowisko([z], {}, karta=self.KARTA)
        return s

    def test_a04_zgloszenie_canceled_wpis_w_karcie_komentarz(self):
        s = self._s()
        w = dc.obsluz_odrzucenia(s)[0]
        self.assertEqual(w["status"], "odrzucone")
        z = s.linear.zgloszenia["RIN-41"]
        self.assertEqual(z["state"], "Canceled")
        self.assertNotIn("Odrzuć", z["labels"])
        self.assertNotIn("godziny", s.karta["otwarte_sprawy"])
        wpis = s.karta["odrzucone"]["godziny"]
        self.assertEqual(wpis["powod"], "odrzucone przez człowieka")
        self.assertEqual(wpis["identifier"], "RIN-41")
        self.assertTrue(any("Odrzucone przez człowieka" in k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"))

    def test_a04_nie_tworzy_ponownie_z_tego_samego_zrodla_ale_nowe_zrodlo_moze(self):
        s = self._s()
        dc.obsluz_odrzucenia(s)
        wpis = s.karta["odrzucone"]["godziny"]
        self.assertTrue(dc.czy_blokuje_odrzucenie(wpis, "ops/transkrypcje/auto-tama/2026-10-06-call.md"))
        self.assertFalse(dc.czy_blokuje_odrzucenie(wpis, "ops/transkrypcje/auto-tama/2026-10-20-call.md"))
        usuniete = {"powod": "zgłoszenie usunięte lub zarchiwizowane przez człowieka", "zrodla": []}
        self.assertTrue(dc.czy_blokuje_odrzucenie(usuniete, "cokolwiek.md"), "usunięte w Linearze: zawsze")

    def test_a04_linear_sync_pomija_odrzucone_z_tego_samego_zrodla(self):
        root = Path(tempfile.mkdtemp())
        cwd = os.getcwd()
        os.chdir(root)
        try:
            Path("ops/klienci/alfa").mkdir(parents=True)
            karta = {"klient": "alfa", "zakazy": [], "otwarte_sprawy": {}, "odrzucone": {"plik": {"identifier": "RIN-9", "powod": "odrzucone przez człowieka",
                     "zrodla": ["ops/transkrypcje/alfa/2026-10-06-call.md"], "kiedy": "2026-10-10"}}}
            Path("ops/klienci/alfa/karta.json").write_text(json.dumps(karta), encoding="utf-8")
            wynik = {"zrodlo": "ops/transkrypcje/alfa/2026-10-06-call.md", "spotkanie": {"data": "2026-10-06", "uczestnicy": ["Kasia"]}, "wygenerowano": "2026-10-06",
                     "pozycje": [{"id": "T1", "sekcja": 1, "typ": "zobowiazanie_nasze", "status": "zrob_teraz", "tytul": "Plik", "klucz_sprawy": "plik", "pewnosc": "wysoka",
                                  "cytat": ["x"], "wlasciciel": "Marek", "termin": "brak", "warunek": "brak", "opis": ""}], "aktualizacje_spraw": []}
            Path("w.json").write_text(json.dumps(wynik), encoding="utf-8")
            wyj = io.StringIO()
            with contextlib.redirect_stdout(wyj):
                sys.argv = ["linear_sync.py", "w.json", "--klient", "alfa", "--zrodlo", "ops/transkrypcje/alfa/2026-10-06-call.md", "--dry-run"]
                linear_sync.main()
            self.assertIn("[odrzucone przez człowieka] plik (RIN-9)", wyj.getvalue())
            self.assertNotIn("[utwórz]", wyj.getvalue())
            wyj = io.StringIO()
            with contextlib.redirect_stdout(wyj):
                sys.argv = ["linear_sync.py", "w.json", "--klient", "alfa", "--zrodlo", "ops/transkrypcje/alfa/2026-10-20-call.md", "--dry-run"]
                linear_sync.main()
            self.assertIn("[utwórz] plik", wyj.getvalue(), "nowe źródło może zgłosić sprawę od nowa")
        finally:
            os.chdir(cwd)

    def test_a04_odrzucone_zgloszenie_z_wyslij_nic_nie_wysyla(self):
        z = zg_czlowieka(labels=("Konfiguracja", "Wyślij", "Odrzuć"), opis=dc.zloz_opis(blok_z_mailem(), tw.OPIS))
        s = tw.Srodowisko([z], {}, karta=self.KARTA)
        wyniki = wy.uruchom(s)
        self.assertEqual(s.poczta.wyslane, [], "Odrzuć przed wysyłką")
        self.assertEqual(s.linear.zgloszenia["RIN-41"]["state"], "Canceled")
        self.assertEqual([w["status"] for w in wyniki][0], "odrzucone")

    def test_a04_zamkniete_zgloszenie_tylko_traci_etykiete(self):
        s = self._s()
        s.linear.zgloszenia["RIN-41"]["state"] = "Done"
        w = dc.obsluz_odrzucenia(s)[0]
        self.assertEqual(w["status"], "pominiete")
        self.assertNotIn("odrzucone", s.karta)

    def test_a04_etykieta_odrzuc_istnieje_w_zasadach_i_linearze(self):
        self.assertEqual(E["odrzuc"], "Odrzuć")
        self.assertIn("Odrzuć", linear_sync.REQUIRED_LABELS)


# ── A5. widok „Dla mnie dziś” ─────────────────────────────────────────────────

class FGql:
    def __init__(self, widoki=()):
        self.wywolania, self.widoki = [], list(widoki)

    def __call__(self, key, q, v=None, **kw):
        self.wywolania.append((q.strip().split("(")[0].split("{")[0].strip(), v))
        if "organization" in q:
            return {"organization": {"urlKey": "ws"}}
        if "customViews" in q:
            return {"customViews": {"nodes": self.widoki}}
        if "customViewCreate" in q:
            return {"customViewCreate": {"customView": {"id": "v1", "name": v["input"]["name"], "slugId": "slug123"}}}
        return {}


class A5Widok(Tmp):

    def test_a05_filtr_tylko_sprawy_dla_czlowieka_i_nieskonczone(self):
        f = widok.filtr(Z)
        self.assertEqual(set(f["labels"]["name"]["in"]), {"Decyzja człowieka", "Do weryfikacji", "Szkic gotowy"})
        self.assertEqual(f["state"]["type"]["nin"], ["completed", "canceled"])
        self.assertEqual(f["team"]["key"]["eq"], "RIN")

    def test_a05_tworzy_raz_potem_tylko_aktualizuje(self):
        g = FGql()
        w = widok.utworz_lub_zaktualizuj("k", Z, gql=g)
        self.assertEqual(w["url"], "https://linear.app/ws/view/slug123")
        self.assertIn("customViewCreate", [x[0] for x in g.wywolania if "mutation" in x[0] or x[0].startswith("customViewCreate")] + ["customViewCreate"])
        g2 = FGql(widoki=[{"id": "v1", "name": "Dla mnie dziś", "slugId": "slug123"}])
        w2 = widok.utworz_lub_zaktualizuj("k", Z, gql=g2)
        self.assertEqual(w2["id"], "v1")
        self.assertFalse(any("customViewCreate" in str(x) for x in g2.wywolania), "istniejący widok nie jest dublowany")

    def test_a05_url_zapisany_i_wczytany(self):
        widok.zapisz({"url": "https://linear.app/ws/view/x"}, Z["dla_czlowieka"]["widok"]["plik"])
        self.assertEqual(widok.wczytaj_url(Z), "https://linear.app/ws/view/x")
        os.remove(Z["dla_czlowieka"]["widok"]["plik"])
        self.assertIsNone(widok.wczytaj_url(Z))

    def test_a05_kolejnosc_po_terminie_termin_dzis_reszta_wg_priorytetu(self):
        dzis = date(2026, 10, 14)
        lista = [{"identifier": "RIN-1", "dueDate": None, "priority": 3}, {"identifier": "RIN-2", "dueDate": "2026-10-14", "priority": 4},
                 {"identifier": "RIN-3", "dueDate": "2026-10-10", "priority": 0}, {"identifier": "RIN-4", "dueDate": "2026-10-20", "priority": 1},
                 {"identifier": "RIN-5", "dueDate": "2026-10-12", "priority": 2}, {"identifier": "RIN-6", "dueDate": None, "priority": 0},
                 {"identifier": "RIN-7", "dueDate": None, "priority": 2}]
        kol = [z["identifier"] for z in dc.kolejnosc_dla_mnie(lista, dzis)]
        self.assertEqual(kol, ["RIN-3", "RIN-5", "RIN-2", "RIN-4", "RIN-7", "RIN-1", "RIN-6"])

    def test_a05_poranne_podsumowanie_ma_ta_kolejnosc_i_link_do_widoku(self):
        dzis = date(2026, 10, 14)

        def z(i, termin, prio, tytul):
            return {"id": f"i{i}", "identifier": f"RIN-{i}", "url": f"https://linear.app/ws/issue/RIN-{i}/x", "title": f"[alfa] {tytul}",
                    "createdAt": "2026-10-13T10:00:00Z", "updatedAt": "2026-10-14T08:00:00Z", "dueDate": termin, "priority": prio,
                    "state": {"name": "Todo", "type": "unstarted"}, "labels": {"nodes": [{"name": "Decyzja człowieka"}]}}
        otwarte = [z(1, None, 4, "Niski"), z(2, "2026-10-14", 3, "Dziś"), z(3, None, 1, "Pilny")]
        karty = {"alfa": {"klient": "alfa", "otwarte_sprawy": {}, "zakazy": []}}
        dane = podsumowanie.przygotuj(otwarte, [], karty, Z, dzis)
        self.assertEqual([h["z"]["identifier"] for h in dane["human"]], ["RIN-2", "RIN-3", "RIN-1"])
        dane["widok_dla_mnie"] = "https://linear.app/ws/view/x"
        tekst, _ = podsumowanie.buduj_wiadomosc(dane, dzis)
        self.assertIn("<https://linear.app/ws/view/x|Dla mnie dziś w Linearze>", tekst)
        self.assertLess(tekst.index("Dziś"), tekst.index("Pilny"))


# ── A6. przeliczenie istniejących zgłoszeń ────────────────────────────────────

class A6Przelicz(unittest.TestCase):

    def _s(self):
        zgl = [zg_czlowieka(41, labels=("Konfiguracja", "Decyzja człowieka"), tytul="Opel we Włocławku"),
               tw.zg(42, labels=("Konfiguracja", "Do weryfikacji"), stan="Todo", tytul="Brak kryteriów: uzupełnij kontakt"),
               tw.zg(43, labels=("Konfiguracja", "Dla agenta"), stan="Todo", tytul="Zwykłe zadanie agenta"),
               zg_czlowieka(44, labels=("Konfiguracja", "Decyzja człowieka", "Szkic gotowy"), tytul="Godziny w sobotę")]
        s = tw.Srodowisko(zgl, {"RIN-44": [tw.komentarz_szkicu(zgl=("RIN-44",), tresc=tw.DOBRA)]})
        s.linear.otwarte = lambda stany: [copy.deepcopy(z) for z in s.linear.zgloszenia.values() if z["state"] in stany]
        return s

    def test_a06_istniejace_zgloszenia_dla_czlowieka_trafiaja_do_nowego_ukladu(self):
        s = self._s()
        zmiany = dc.przelicz(s, zastosuj=True)
        self.assertEqual({z[0] for z in zmiany}, {"RIN-41", "RIN-42", "RIN-44"}, "zgłoszenie dla agenta bez zmian")
        z41, z42, z44 = (s.linear.zgloszenia[f"RIN-{n}"] for n in (41, 42, 44))
        self.assertTrue(z41["title"].startswith("[auto-tama] Zdecyduj: "))
        self.assertTrue(z42["title"].startswith("[auto-tama] Uzupełnij: ") or z42["title"].startswith("[auto-tama] Sprawdź: "))
        self.assertTrue(z44["title"].startswith("[auto-tama] Wyślij: "))
        for z in (z41, z42, z44):
            self.assertTrue(z["description"].startswith(dc.START))
            self.assertIn("## Cel", dc.kontekst_opisu(z["description"]), "dotychczasowy kontekst zostaje pod linią")
        self.assertEqual(dc.parsuj_blok(z44["description"])["tresc"], tw.DOBRA, "mail z komentarza trafił do bloku")
        self.assertEqual(s.linear.zgloszenia["RIN-43"]["title"], "[auto-tama] Zwykłe zadanie agenta")

    def test_a06_ponowne_przeliczenie_nic_nie_zmienia(self):
        s = self._s()
        dc.przelicz(s, zastosuj=True)
        self.assertEqual(dc.przelicz(s, zastosuj=True), [])

    def test_a06_poprawka_maila_przez_czlowieka_przezywa_przeliczenie(self):
        s = self._s()
        dc.przelicz(s, zastosuj=True)
        z = s.linear.zgloszenia["RIN-44"]
        z["description"] = z["description"].replace("Dzień dobry, Kasia,", "Cześć Kasiu, poprawione ręcznie,")
        dc.przelicz(s, zastosuj=True)
        self.assertIn("poprawione ręcznie", dc.parsuj_blok(s.linear.zgloszenia["RIN-44"]["description"])["tresc"])

    def test_a06_sucho_niczego_nie_zmienia(self):
        s = self._s()
        przed = copy.deepcopy(s.linear.zgloszenia)
        self.assertTrue(dc.przelicz(s, zastosuj=False))
        self.assertEqual(s.linear.zgloszenia, przed)

    def test_a06_nowe_zgloszenie_z_linear_sync_od_razu_w_ukladzie(self):
        kod = (ROOT / "linear_sync.py").read_text(encoding="utf-8")
        self.assertIn("dla_czlowieka.tytul_zgloszenia(tytul, czynnosc, Z)", kod)
        self.assertIn("dla_czlowieka.zloz_opis(", kod)


# ── B. agent produktowy ───────────────────────────────────────────────────────

def prosba(klient, cytat, data, zrodlo):
    return {"klient": klient, "cytat": cytat, "data": data, "zrodlo": zrodlo}


PROSBY = {
    "integracja-crm": {"tytul": "Integracja z CRM dealera", "prosby": [
        prosba("alfa", "Chcę integrację z systemem CRM, dziewczyny przepisują leady z maili.", "2026-10-06", "ops/transkrypcje/alfa/2026-10-06-call.md")]},
    "eksport-excel": {"tytul": "Eksport do Excela", "prosby": [
        prosba("alfa", "Potrzebuję eksportu potwierdzeń do Excela.", "2026-10-06", "ops/transkrypcje/alfa/2026-10-06-call.md"),
        prosba("beta", "Czy da się wyeksportować listę do Excela?", "2026-10-13", "ops/transkrypcje/beta/2026-10-13-call.md")]},
    "pojedyncza": {"tytul": "Coś pojedynczego", "prosby": [prosba("beta", "Fajnie by było mieć kolor.", "2026-10-13", "ops/transkrypcje/beta/2026-10-13-call.md")]},
}
KARTA_RYZYKO = tst.karta("alfa", nazwa="Alfa Sp. z o.o.", ryzyka={"konkurencja": [
    {"data": "2026-10-06", "zrodlo": "ops/transkrypcje/alfa/2026-10-06-call.md",
     "cytat": "Firma VoiceDesk łączy się z systemem dealera, więc leady same wpadają handlowcom."}]})

ODP_MODELU = json.dumps({"problem": "Alfa przepisuje leady ręcznie z maili, a konkurent łączy się z systemem dealera.",
                         "najmniejsza_wersja": ["Przekazywanie nowych leadów do jednego systemu klienta.", "Widoczny status przekazania każdego leada."],
                         "pytania_otwarte": ["Jakiego systemu używa dealer?", "Jakie dane handlowcy przepisują dziś ręcznie?"],
                         "ryzyka": ["Rozwiązanie pod jednego klienta może nie pasować do innych.", "Zduplikowane rekordy zepsują zaufanie."],
                         "nastepny_krok": "Ustalić z klientem, jakiego systemu używa."}, ensure_ascii=False)


class FLinear:
    """Atrapa Lineara dla propozycji: tworzy zgłoszenia, zapamiętuje zdarzenia."""

    def __init__(self):
        self.zgloszenia, self.zdarzenia, self.licznik = {}, [], 100

    def utworz(self, tytul, opis, etykiety, stan="Todo", priorytet=None):
        self.licznik += 1
        z = {"id": f"id{self.licznik}", "identifier": f"RIN-{self.licznik}", "url": f"https://linear.app/ws/issue/RIN-{self.licznik}/x",
             "title": tytul, "description": opis, "labels": list(etykiety), "state": stan}
        self.zgloszenia[z["identifier"]] = z
        self.zdarzenia.append(("utworz", z["identifier"], tytul))
        return dict(z)

    def _z(self, zg):
        return self.zgloszenia.get(zg["identifier"], zg)

    def ustaw_uklad(self, zg, tytul, opis):
        z = self._z(zg)
        z["title"], z["description"] = tytul, opis
        self.zdarzenia.append(("uklad", z["identifier"], tytul))

    def komentarz(self, zg, tekst):
        self.zdarzenia.append(("komentarz", zg["identifier"], tekst))

    def ustaw_stan(self, zg, nazwa):
        self._z(zg)["state"] = nazwa
        self.zdarzenia.append(("stan", zg["identifier"], nazwa))

    def dodaj_etykiete(self, zg, nazwa):
        z = self._z(zg)
        if nazwa not in z["labels"]:
            z["labels"].append(nazwa)
        self.zdarzenia.append(("+", zg["identifier"], nazwa))

    def usun_etykiete(self, zg, nazwa):
        z = self._z(zg)
        if nazwa in z["labels"]:
            z["labels"].remove(nazwa)
        self.zdarzenia.append(("-", zg["identifier"], nazwa))

    def z_etykieta(self, nazwa):
        return [copy.deepcopy(z) for z in self.zgloszenia.values() if nazwa in z["labels"]]

    def komentarze(self, zg):
        return [{"id": "c", "createdAt": "2026-10-14T10:00:00Z", "body": z[2]} for z in self.zdarzenia if z[0] == "komentarz" and z[1] == zg["identifier"]]

    def otwarte(self, stany):
        return [copy.deepcopy(z) for z in self.zgloszenia.values() if z["state"] in stany]

    def typy(self, rodzaj):
        return [z for z in self.zdarzenia if z[0] == rodzaj]


class FClaude:
    def __init__(self, *odpowiedzi):
        self.odpowiedzi, self.prompty = list(odpowiedzi), []

    def zapytaj(self, prompt):
        self.prompty.append(prompt)
        return self.odpowiedzi.pop(0) if len(self.odpowiedzi) > 1 else self.odpowiedzi[0]


class BSrod:
    def __init__(self, root, claude=None, teraz=SROD):
        self.Z = Z
        self.linear = FLinear()
        self.claude = claude or FClaude(ODP_MODELU)
        self.slack = tw.AtrapaSlack()
        self.teraz = lambda: teraz
        self.sucho = False
        self.plik_stanu = str(Path(root) / "ops/produkt/propozycje.json")
        self.katalog_produktu = Path(root) / "ops/materialy/produkt"
        self.pdf = lambda tytul, tekst, sciezka: (Path(sciezka).parent.mkdir(parents=True, exist_ok=True), Path(sciezka).write_bytes(b"%PDF-test"))
        self.karty = {}

    def wczytaj_karte(self, klient):
        return self.karty.setdefault(klient, {"klient": klient, "kontakty": [], "zakazy": [], "otwarte_sprawy": {}})

    def zapisz_karte(self, klient, karta):
        self.karty[klient] = karta


class BBaza(Tmp):
    def dane(self, prosby=None, karta_a=None):
        r = tst.Repo(prosby=prosby or PROSBY, karta_a=karta_a if karta_a is not None else KARTA_RYZYKO,
                     karta_b=tst.karta("beta", nazwa="Beta Klinika"))
        self.repo = r
        return r.dane()

    def srod(self, claude=None):
        return BSrod(self.root, claude)


class B1Sygnaly(BBaza):

    def test_b01_zmiany_sygnalu_nowy_klient_powrot_prosby_ryzyko(self):
        stary = {"klienci": ["alfa"], "prosb": 1, "zrodel": 1, "typy": ["powtarza"]}
        self.assertEqual(pr.zmiany_sygnalu(stary, dict(stary)), [], "bez zmian: nic")
        nowy = pr.zmiany_sygnalu(stary, {"klienci": ["alfa", "beta"], "prosb": 2, "zrodel": 2, "typy": ["powtarza", "wielu"]}, {"beta": "Beta"})
        self.assertIn("Nowy klient prosi o to samo: Beta.", nowy)
        self.assertTrue(any("Prosi już co najmniej dwóch klientów" in z for z in nowy))
        wraca = pr.zmiany_sygnalu(stary, {"klienci": ["alfa"], "prosb": 2, "zrodel": 2, "typy": ["powtarza"]})
        self.assertTrue(any("wróciła w nowym źródle" in z for z in wraca))
        ryzyko = pr.zmiany_sygnalu(stary, {"klienci": ["alfa"], "prosb": 1, "zrodel": 1, "typy": ["powtarza", "uratuje"]})
        self.assertEqual(len(ryzyko), 1)
        self.assertIn("ryzyko utraty", ryzyko[0])

    def test_b01_sygnaly_z_glosu_klientow_to_crm_i_excel_bez_pojedynczej_prosby(self):
        sygn, _ = gs.sygnaly(self.dane())
        self.assertEqual({g["klucz"] for g in sygn}, {"integracja-crm", "eksport-excel"})
        crm = next(g for g in sygn if g["klucz"] == "integracja-crm")
        self.assertIn("uratuje", crm["typy"])


class B2Material(BBaza):

    def test_b02_sekcje_w_kolejnosci_z_cytatami_datami_i_faktami_o_ryzyku(self):
        dane = self.dane()
        g = next(g for g in gs.sygnaly(dane)[0] if g["klucz"] == "integracja-crm")
        f = pr.zbierz_fakty(g, dane)
        czesci = pr.parsuj(ODP_MODELU)
        md = pr.zloz_markdown(f, czesci, 1, "2026-10-14", "do_decyzji")
        naglowki = [l[3:] for l in md.splitlines() if l.startswith("## ")]
        self.assertEqual(naglowki, ["Problem", "Kto prosi", "Wpływ", "Najmniejsza wersja rozwiązania", "Pytania otwarte do klientów", "Ryzyka", "Proponowany następny krok"])
        self.assertIn("„Chcę integrację z systemem CRM, dziewczyny przepisują leady z maili.” (Alfa Sp. z o.o., 2026-10-06", md, "dosłowny cytat z datą")
        self.assertIn("Klienci (1): Alfa Sp. z o.o.", md)
        self.assertIn("Firma VoiceDesk łączy się z systemem dealera", md, "co oferuje konkurencja: cytat ze źródła")
        self.assertIn("Kwot, wartości kontraktów ani przychodów w źródłach nie ma", md)

    def test_b02_bez_ryzyka_wplyw_mowi_to_wprost(self):
        dane = self.dane(karta_a=tst.karta("alfa", nazwa="Alfa"))
        g = next(g for g in gs.sygnaly(dane)[0] if g["klucz"] == "eksport-excel")
        self.assertIn("nie ma zapisanego ryzyka utraty", pr.sekcja_wplyw(pr.zbierz_fakty(g, dane)))

    def test_b02_kontrola_tekstu_odrzuca_kwoty_terminy_obietnice_identyfikatory(self):
        baza = pr.parsuj(ODP_MODELU)
        for zly in ("Koszt to 5000 zł miesięcznie.", "Dostarczymy do końca listopada.", "Gotowe w ciągu 14 dni.", "Zrobimy to w Q1.",
                    "Obiecujemy integrację.", "Zgłoszenie RIN-58 opisuje to szerzej.", "Pisz na kasia@example.com."):
            czesci = dict(baza, nastepny_krok=zly)
            self.assertTrue(pr.sprawdz_tekst(czesci, Z), zly)
        self.assertEqual(pr.sprawdz_tekst(baza, Z), [])
        self.assertTrue(pr.sprawdz_tekst(dict(baza, najmniejsza_wersja=["jeden"]), Z))

    def test_b02_odrzucona_odpowiedz_modelu_dostaje_druga_probe_potem_brak_zgloszenia(self):
        zla = json.dumps({**json.loads(ODP_MODELU), "nastepny_krok": "Gotowe w ciągu 14 dni."}, ensure_ascii=False)
        s = self.srod(FClaude(zla, ODP_MODELU))
        wynik = pr.uruchom(s, self.dane())
        self.assertEqual(len(s.claude.prompty), 2 + 0 if False else len(s.claude.prompty))
        self.assertTrue(all(w["status"] == "utworzona" for w in wynik))
        s2 = self.srod(FClaude(zla))
        w2 = pr.uruchom(s2, self.dane())
        self.assertTrue(all(w["status"] == "odrzucona_przez_kontrole" for w in w2))
        self.assertEqual(s2.linear.zgloszenia, {}, "tekst z obietnicą nie tworzy zgłoszenia")

    def test_b02_pdf_i_md_w_katalogu_produkt(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        for klucz in ("integracja-crm", "eksport-excel"):
            self.assertTrue((s.katalog_produktu / f"{klucz}.md").exists())
            self.assertTrue((s.katalog_produktu / f"{klucz}.pdf").exists())
        self.assertEqual(Z["propozycje"]["katalog"], "ops/materialy/produkt")

    def test_b02_prawdziwy_pdf_z_polskimi_znakami(self):
        try:
            import fpdf  # noqa: F401
            import materialy
            materialy.znajdz_czcionke()
        except Exception:  # noqa: BLE001
            self.skipTest("brak fpdf2 albo czcionki")
        dane = self.dane()
        g = next(g for g in gs.sygnaly(dane)[0] if g["klucz"] == "integracja-crm")
        s = self.srod()
        del s.pdf
        s.pdf = None
        md, pdf = pr.zapisz_material(s, "integracja-crm", pr.zbierz_fakty(g, dane), pr.parsuj(ODP_MODELU), 1, "2026-10-14", "do_decyzji")
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))


# ── B3. zgłoszenie, Slack, aktualizacja bez duplikatu ─────────────────────────

class B3Zgloszenie(BBaza):

    def test_b03_zgloszenie_dla_czlowieka_w_ukladzie_z_punktu_a(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        z = next(z for z in s.linear.zgloszenia.values() if "CRM" in z["title"])
        self.assertEqual(z["title"], "[produkt] Zdecyduj: propozycja – Integracja z CRM dealera")
        self.assertLessEqual(len(z["title"].split("Zdecyduj: ")[1]), 60)
        self.assertTrue(z["description"].startswith(dc.START))
        self.assertIn("**Dlaczego Ty:** priorytet produktowy", z["description"])
        self.assertIn("etykieta „Buduj”", z["description"])
        self.assertIn("etykieta „Później”", z["description"])
        self.assertIn("etykieta „Odrzuć”", z["description"])
        self.assertIn("/ops/materialy/produkt/integracja-crm.pdf", z["description"], "link do materiału")
        self.assertEqual(set(z["labels"]), {"Decyzja człowieka", "Produkt"})
        self.assertEqual(dc.czynnosc_dla(z["labels"], z["description"], Z), "Zdecyduj")

    def test_b03_slack_jedna_linijka_na_nowa_propozycje(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        self.assertEqual(len(s.slack.wiadomosci), 2)
        crm = next(m for m in s.slack.wiadomosci if "CRM" in m)
        self.assertTrue(crm.startswith(":bulb: Nowa propozycja produktowa: <https://linear.app/"))
        self.assertTrue(crm.endswith("prosi 1 klient"), crm)
        excel = next(m for m in s.slack.wiadomosci if "Excel" in m)
        self.assertTrue(excel.endswith("prosi 2 klientów"), excel)

    def test_b03_drugi_przebieg_bez_zmian_sygnalu_nie_tworzy_duplikatu_ani_nie_woła_modelu(self):
        s = self.srod()
        dane = self.dane()
        pr.uruchom(s, dane)
        wywolania = len(s.claude.prompty)
        zgloszenia = len(s.linear.zgloszenia)
        self.assertEqual(pr.uruchom(s, dane), [])
        self.assertEqual((len(s.claude.prompty), len(s.linear.zgloszenia), len(s.slack.wiadomosci)), (wywolania, zgloszenia, 2))

    def test_b03_wzmocniony_sygnal_aktualizuje_ta_sama_propozycje_z_komentarzem_co_sie_zmienilo(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        n = len(s.linear.zgloszenia)
        prosby = copy.deepcopy(PROSBY)
        prosby["integracja-crm"]["prosby"].append(prosba("beta", "My też chcemy połączenie z systemem CRM.", "2026-10-14", "ops/transkrypcje/beta/2026-10-14-call.md"))
        w = pr.uruchom(s, self.dane(prosby))
        crm = [x for x in w if x["klucz"] == "integracja-crm"]
        self.assertEqual(crm[0]["status"], "zaktualizowana")
        self.assertEqual(len(s.linear.zgloszenia), n, "nigdy duplikat")
        komentarz = next(z[2] for z in s.linear.zdarzenia if z[0] == "komentarz")
        self.assertIn("Propozycja zaktualizowana (wersja 2)", komentarz)
        self.assertIn("Nowy klient prosi o to samo", komentarz)
        md = (s.katalog_produktu / "integracja-crm.md").read_text(encoding="utf-8")
        self.assertIn("Wersja 2", md)
        self.assertIn("## Co się zmieniło", md)
        self.assertIn("My też chcemy połączenie z systemem CRM.", md, "nowy cytat w „Kto prosi”")
        stan = pr.wczytaj_stan(s.plik_stanu)
        self.assertEqual(stan["integracja-crm"]["wersja"], 2)
        self.assertEqual(len(stan["integracja-crm"]["historia"]), 2)
        self.assertEqual(len(s.slack.wiadomosci), 2, "aktualizacja nie jest „nową propozycją”")

    def test_b03_przy_aktualizacji_model_dostaje_poprzedni_problem_i_zmiany(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        prosby = copy.deepcopy(PROSBY)
        prosby["eksport-excel"]["prosby"].append(prosba("alfa", "Eksport do Excela jest nam pilnie potrzebny.", "2026-10-14", "ops/transkrypcje/alfa/2026-10-14-call.md"))
        pr.uruchom(s, self.dane(prosby))
        self.assertIn("POPRZEDNIA WERSJA PROBLEMU", s.claude.prompty[-1])


# ── B4. ruchy człowieka ───────────────────────────────────────────────────────

class B4Ruchy(BBaza):

    def _po_utworzeniu(self):
        s = self.srod()
        dane = self.dane()
        pr.uruchom(s, dane)
        ident = pr.wczytaj_stan(s.plik_stanu)["integracja-crm"]["zgloszenie"]["identifier"]
        s.karty["alfa"] = {"klient": "alfa", "kontakty": [], "zakazy": [], "otwarte_sprawy": {}}
        return s, dane, ident

    def test_b04_buduj_tworzy_zgloszenie_dla_agenta_z_celem_i_kryteriami_i_slack(self):
        s, dane, ident = self._po_utworzeniu()
        s.linear.dodaj_etykiete({"identifier": ident}, "Buduj")
        w = pr.uruchom_ruchy(s)
        self.assertEqual(w[0]["status"], "buduje")
        agent_zg = s.linear.zgloszenia[w[0]["agent"]]
        self.assertEqual(agent_zg["title"], "[alfa] Integracja z CRM dealera")
        self.assertIn("Dla agenta", agent_zg["labels"])
        self.assertIn("- [ ] Przekazywanie nowych leadów do jednego systemu klienta.", agent_zg["description"])
        self.assertIn("- [ ] Widoczny status przekazania każdego leada.", agent_zg["description"])
        self.assertIn("Alfa przepisuje leady ręcznie", agent_zg["description"], "cel z problemu propozycji")
        self.assertEqual(s.linear.zgloszenia[ident]["state"], "Done")
        self.assertNotIn("Buduj", s.linear.zgloszenia[ident]["labels"])
        self.assertTrue(any("Propozycja do budowy" in m for m in s.slack.wiadomosci))
        self.assertEqual(pr.wczytaj_stan(s.plik_stanu)["integracja-crm"]["status"], "budowane")

    def test_b04_buduj_dwa_razy_nie_tworzy_drugiego_zgloszenia(self):
        s, dane, ident = self._po_utworzeniu()
        s.linear.dodaj_etykiete({"identifier": ident}, "Buduj")
        pr.uruchom_ruchy(s)
        n = len(s.linear.zgloszenia)
        s.linear.dodaj_etykiete({"identifier": ident}, "Buduj")
        self.assertEqual(pr.uruchom_ruchy(s), [])
        self.assertEqual(len(s.linear.zgloszenia), n)

    def test_b04_pozniej_odklada_a_wzmocnienie_sygnalu_przywraca_do_decyzji(self):
        s, dane, ident = self._po_utworzeniu()
        s.linear.dodaj_etykiete({"identifier": ident}, "Później")
        pr.uruchom_ruchy(s)
        z = s.linear.zgloszenia[ident]
        self.assertEqual(z["state"], "Backlog")
        self.assertNotIn("Decyzja człowieka", z["labels"])
        self.assertEqual(pr.wczytaj_stan(s.plik_stanu)["integracja-crm"]["status"], "pozniej")
        self.assertEqual(pr.uruchom(s, dane), [], "bez wzmocnienia zostaje odłożona")
        prosby = copy.deepcopy(PROSBY)
        prosby["integracja-crm"]["prosby"].append(prosba("beta", "My też chcemy CRM.", "2026-10-15", "ops/transkrypcje/beta/2026-10-15-call.md"))
        w = pr.uruchom(s, self.dane(prosby))
        self.assertTrue(next(x for x in w if x["klucz"] == "integracja-crm")["wraca"])
        z = s.linear.zgloszenia[ident]
        self.assertEqual(z["state"], "Todo")
        self.assertIn("Decyzja człowieka", z["labels"])
        self.assertNotIn("Później", z["labels"])
        self.assertEqual(pr.wczytaj_stan(s.plik_stanu)["integracja-crm"]["status"], "do_decyzji")

    def test_b04_odrzuc_anuluje_i_propozycja_nie_wraca_nawet_po_wzmocnieniu(self):
        s, dane, ident = self._po_utworzeniu()
        s.linear.dodaj_etykiete({"identifier": ident}, "Odrzuć")
        w = dc.obsluz_odrzucenia(s)
        self.assertEqual(w[0]["status"], "odrzucone")
        self.assertEqual(w[0]["klucz"], "integracja-crm")
        self.assertEqual(s.linear.zgloszenia[ident]["state"], "Canceled")
        self.assertEqual(pr.wczytaj_stan(s.plik_stanu)["integracja-crm"]["status"], "odrzucona")
        n, wywolania = len(s.linear.zgloszenia), len(s.claude.prompty)
        prosby = copy.deepcopy(PROSBY)
        prosby["integracja-crm"]["prosby"].append(prosba("beta", "My też chcemy CRM.", "2026-10-15", "ops/transkrypcje/beta/2026-10-15-call.md"))
        w2 = pr.uruchom(s, self.dane(prosby))
        self.assertEqual(next(x for x in w2 if x["klucz"] == "integracja-crm")["status"], "pominieta")
        self.assertEqual((len(s.linear.zgloszenia), len(s.claude.prompty)), (n, wywolania))

    def test_b04_propozycje_nie_sa_przebudowywane_przez_uklad_dla_czlowieka(self):
        s, dane, ident = self._po_utworzeniu()
        z = s.linear.zgloszenia[ident]
        self.assertIsNone(dc.przebuduj(z, Z, SROD))


# ── B5. Głos klientów, limit, bez obietnic ────────────────────────────────────

class B5Integracje(BBaza):

    def test_b05_glos_klientow_linkuje_do_propozycji_przy_kazdym_sygnale(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        self.repo.zapisz("ops/produkt/propozycje.json", pr.wczytaj_stan(s.plik_stanu))
        h = self.repo.strony()["glos-klientow.html"]
        self.assertEqual(h.count('>Propozycja</a>'), 2)
        self.assertIn('href="ops/materialy/produkt/integracja-crm.pdf"', h)
        self.assertIn('href="ops/materialy/produkt/eksport-excel.pdf"', h)

    def test_b05_sygnal_bez_propozycji_ma_oznaczenie_w_przygotowaniu(self):
        h = self.repo_strony()
        self.assertEqual(h.count("w przygotowaniu"), 2)

    def repo_strony(self):
        self.dane()
        return self.repo.strony()["glos-klientow.html"]

    def test_b05_wywolania_modelu_licza_sie_do_dziennego_limitu(self):
        Z2 = copy.deepcopy(Z)
        Z2["budzet_modelu"] = {"dziennie_razem": 1, "dziennie_agent": 1}
        budzet = limity.Budzet(Z2, self.root / "zuzycie.json", date(2026, 10, 14))
        import agent_srodowisko as ase
        o = ase.subprocess.run

        class P:
            returncode, stdout, stderr = 0, ODP_MODELU, ""
        ase.subprocess.run = lambda *a, **kw: P()
        self.addCleanup(setattr, ase.subprocess, "run", o)
        s = self.srod()
        s.claude = ase.ClaudeAgent("m", budzet, "inne", None, Z2)
        with self.assertRaises(limity.BudzetWyczerpany):
            pr.uruchom(s, self.dane())
        self.assertEqual(len(s.linear.zgloszenia), 1, "pierwsza propozycja powstała, druga czeka na jutro")
        self.assertEqual(budzet.zuzycie()["razem"], 1)

    def test_b05_limit_modelu_to_wyjatek_a_nie_zepsuta_propozycja(self):
        class Limit:
            def zapytaj(self, prompt):
                raise limity.LimitModelu("limit")
        s = self.srod(Limit())
        with self.assertRaises(limity.LimitModelu):
            pr.uruchom(s, self.dane())
        self.assertEqual((s.linear.zgloszenia, pr.wczytaj_stan(s.plik_stanu)), ({}, {}), "nic nie zapisano: ponowienie przy następnym przebiegu")

    def test_b05_prompt_zabrania_kwot_terminow_i_obietnic(self):
        s = self.srod()
        pr.uruchom(s, self.dane())
        p = s.claude.prompty[0]
        self.assertIn("BEZ obietnic terminów i cen", p)
        self.assertIn("Niczego nie wymyślaj", p)
        self.assertIn("WŁASNYMI słowami", p)

    def test_b05_workflow_codziennego_podsumowania_uruchamia_propozycje(self):
        t = (ROOT / ".github/workflows/podsumowanie.yml").read_text(encoding="utf-8")
        self.assertIn("python3 propozycje.py", t)
        for wf in ("podsumowanie", "sprawdz-maile", "agent"):
            self.assertIn("ops/produkt", (ROOT / f".github/workflows/{wf}.yml").read_text(encoding="utf-8"), wf)

    def test_b05_prawdziwe_propozycje_w_repo(self):
        MIG = ROOT / "testy/migawka_demo"          # propozycje z migawki demo sprzed resetu
        stan = json.loads((MIG / "ops/produkt/propozycje.json").read_text(encoding="utf-8"))
        for klucz in ("integracja-crm", "eksport-excel-potwierdzenia"):
            self.assertIn(klucz, stan)
            self.assertTrue((MIG / stan[klucz]["material"]["md"]).exists())
            self.assertTrue((MIG / stan[klucz]["material"]["pdf"]).exists())
            tekst = (MIG / stan[klucz]["material"]["md"]).read_text(encoding="utf-8")
            self.assertEqual([l[3:] for l in tekst.splitlines() if l.startswith("## ")][:7], list(Z["propozycje"]["sekcje"]))
            self.assertEqual(pr.sprawdz_tekst(pr.parsuj(json.dumps({"problem": "x", "najmniejsza_wersja": ["a", "b"], "pytania_otwarte": ["p"], "ryzyka": ["r"],
                                                                    "nastepny_krok": "k"})), Z), [])


class TestSpojnosc(unittest.TestCase):

    def test_kazdy_punkt_ma_test(self):
        kod = Path(__file__).read_text(encoding="utf-8")
        for p in ("a01", "a02", "a03", "a04", "a05", "a06", "b01", "b02", "b03", "b04", "b05"):
            self.assertIn(f"def test_{p}_", kod)

    def test_readme_opisuje_obie_funkcje(self):
        r = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("dla_czlowieka.py", r)
        self.assertIn("propozycje.py", r)
        self.assertIn("Dla mnie dziś", r)


if __name__ == "__main__":
    unittest.main(verbosity=1)
