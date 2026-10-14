#!/usr/bin/env python3
"""test_agent.py – logika agenta wykonawczego (agent.py, agent_scal.py, agent_github.py) bez sieci.

Linear, git, claude, GitHub i Slack są atrapami. Sprawdzamy: ponowne sprawdzenie zakazów na aktualnej karcie,
limit 3 na przebieg, zakazane ścieżki, oddanie po dwóch nieudanych testach, warunki scalania, jednorazową poprawkę
po uwagach CodeRabbit, Slack tylko przy zakończeniu albo oddaniu.  Uruchomienie:  python3 testy/test_agent.py
"""

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent
import agent_github as ag
import agent_scal
import linear_sync
import zasady

Z = zasady.wczytaj_zasady()
A = Z["agent_wykonawczy"]
TERAZ = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

KARTA = {
    "decydenci": [{"imie": "Kasia Malinowska"}],
    "zakazy": [{"id": "Z4", "tytul": "Nie włączać Opla", "opis": "Opel czeka", "cytat": ["Opla na to nie puszczamy."]}],
    "decyzje_zastrzezone": [{"opis": "Opel: decyduje Kasia", "zastrzezone_dla": "Kasia Malinowska",
                             "klucze_spraw": ["decyzja-opel"], "zakazy": ["Z4"]}],
    "otwarte_sprawy": {"godziny-salonu-sobota": {"identifier": "RIN-41"}, "decyzja-opel": {"identifier": "RIN-70"},
                       "godziny-dzwonienia": {"identifier": "RIN-40"}},
}


def zgloszenie(numer=41, tytul="Toruń podaje sobotę do 14:00 zamiast do 15:00", etykiety=None, priorytet=0,
               stan="Todo", created="2026-10-06T10:00:00Z"):
    item = {"sekcja": 1, "typ": "bug", "tytul": tytul, "opis": "Toruń podaje złe godziny.", "pewnosc": "wysoka",
            "klucz_sprawy": "k", "cytat": ["Toruń dalej po staremu.", "Oba salony mają do piętnastej."],
            "cel": "Toruń podaje w sobotę godziny do 15:00.",
            "kryteria_akceptacji": ["config: Toruń sobota do 15:00", "wiedza: Toruń sobota 9:00–15:00"],
            "jak_sprawdzic": "Przejrzeć config i wiedzę.", "repo": "rinvo-app"}
    return {"id": f"id-{numer}", "identifier": f"RIN-{numer}", "title": f"[auto-tama] {tytul}",
            "description": linear_sync.build_description(item, "src.md", KARTA, zasady.przypisz(item, Z, KARTA), Z),
            "priority": priorytet, "createdAt": created, "url": f"https://linear.app/ws/issue/RIN-{numer}/x", "state": stan,
            "labels": list(etykiety) if etykiety is not None else ["Konfiguracja", "Dla agenta", "repo: rinvo-app"]}


class AtrapaLinear:
    def __init__(self, zgloszenia=()):
        self.zgloszenia, self.zdarzenia = list(zgloszenia), []

    def kandydaci(self):
        return copy.deepcopy(self.zgloszenia)

    def komentarz(self, zg, tekst):
        self.zdarzenia.append(("komentarz", zg["identifier"], tekst))

    def ustaw_stan(self, zg, nazwa):
        zg["state"] = nazwa
        self.zdarzenia.append(("stan", zg["identifier"], nazwa))

    def dodaj_etykiete(self, zg, nazwa):
        zg.setdefault("labels", []).append(nazwa)
        for z in self.zgloszenia:                                    # zgłoszenia z po_numerze to kopie: zapisz też w magazynie
            if z["identifier"] == zg["identifier"] and nazwa not in z.setdefault("labels", []):
                z["labels"].append(nazwa)
        self.zdarzenia.append(("etykieta", zg["identifier"], nazwa))

    def usun_etykiete(self, zg, nazwa):
        for z in (zg, next((x for x in self.zgloszenia if x["identifier"] == zg["identifier"]), zg)):
            if nazwa in z.get("labels", []):
                z["labels"].remove(nazwa)
        self.zdarzenia.append(("-etykieta", zg["identifier"], nazwa))

    def zgloszenie_po_numerze(self, numer):
        return next((copy.deepcopy(z) for z in self.zgloszenia if z["identifier"] == f"RIN-{numer}"), None)

    def typy(self, rodzaj):
        return [z[1:] for z in self.zdarzenia if z[0] == rodzaj]


class AtrapaGit:
    """Atrapa gita: kolejne wyniki testów i zmian są zadane z góry."""

    def __init__(self, wyniki_testow=((True, "OK"),), zmienione=("config/auto-tama.yaml", "wiedza/auto-tama.md"),
                 diff="-14:00\n+15:00\n"):
        self.wyniki_testow, self.zmienione_lista, self._diff = list(wyniki_testow), list(zmienione), diff
        self.wywolania, self.cofniete, self.push, self.testy_uruchomienia = [], [], [], 0

    def galaz_zdalna_istnieje(self, galaz):
        return False

    def przygotuj(self, galaz, istniejaca=False):
        self.wywolania.append(("przygotuj", galaz))
        return Path("/tmp/atrapa")

    def zmienione(self, katalog):
        return [s for s in self.zmienione_lista if s not in self.cofniete]

    def cofnij(self, katalog, sciezki):
        self.cofniete += list(sciezki)

    def diff(self, katalog, pliki):
        self.diff_pliki = list(pliki)
        return self._diff

    def testy(self, katalog):
        self.testy_uruchomienia += 1
        i = min(self.testy_uruchomienia - 1, len(self.wyniki_testow) - 1)
        return self.wyniki_testow[i]

    def commit_push(self, katalog, komunikat, galaz, pliki):
        self.push.append((galaz, komunikat))
        self.commitowane = list(pliki)

    def sprzatnij(self):
        pass


class AtrapaClaude:
    def __init__(self, odpowiedz_zakazy='{"konflikt": false, "zakaz": null, "powod": ""}', blad_edycji=None):
        self.odpowiedz_zakazy, self.blad_edycji = odpowiedz_zakazy, blad_edycji
        self.prompty_edycji, self.pytania = [], []

    def edytuj(self, katalog, prompt):
        if self.blad_edycji:
            raise RuntimeError(self.blad_edycji)
        self.prompty_edycji.append(prompt)
        return True, "Zmieniłem godziny."

    def zapytaj(self, prompt):
        self.pytania.append(prompt)
        if callable(self.odpowiedz_zakazy):
            return self.odpowiedz_zakazy(prompt)
        return self.odpowiedz_zakazy


class AtrapaGitHub:
    def __init__(self, prs=(), pliki=("config/auto-tama.yaml", "wiedza/auto-tama.md"), runy=None, statusy=(), recenzje=(),
                 inline=(), komentarze=(), blad_scalenia=None):
        self.prs, self.pliki, self.runy, self.statusy_lista = list(prs), list(pliki), runy, list(statusy)
        self.recenzje_lista, self.inline_lista, self.komentarze_lista = list(recenzje), list(inline), list(komentarze)
        self.blad_scalenia = blad_scalenia
        self.utworzone, self.scalone, self.dodane_komentarze = [], [], []

    def otwarte_pr(self):
        return self.prs

    def utworz_pr(self, tytul, galaz, opis, baza="main"):
        self.utworzone.append({"tytul": tytul, "galaz": galaz, "opis": opis})
        return {"html_url": "https://github.com/Rembolekk/Rinvo-app/pull/7", "number": 7}

    def check_runs(self, sha):
        return self.runy if self.runy is not None else [{"name": "testy", "status": "completed", "conclusion": "success"},
                                                      {"name": "CodeRabbit", "status": "completed", "conclusion": "success"}]

    def statusy(self, sha):
        return self.statusy_lista

    def pliki_pr(self, numer):
        return self.pliki

    def recenzje(self, numer):
        return self.recenzje_lista

    def komentarze_inline(self, numer):
        return self.inline_lista

    def komentarze(self, numer):
        return self.komentarze_lista

    def komentarz(self, numer, tekst):
        self.dodane_komentarze.append((numer, tekst))
        self.komentarze_lista.append({"body": tekst})

    def scal_pr(self, numer, tytul, opis):
        if self.blad_scalenia:
            raise RuntimeError(self.blad_scalenia)
        self.scalone.append({"numer": numer, "tytul": tytul, "opis": opis})


class AtrapaSlack:
    def __init__(self):
        self.wiadomosci = []

    def wyslij(self, tekst, bloki=None):
        self.wiadomosci.append(tekst)


class Srodowisko:
    def __init__(self, zgloszenia=(), git=None, claude=None, github=None, karta=None):
        self.Z = Z
        self.linear = AtrapaLinear(zgloszenia)
        self.git = git or AtrapaGit()
        self.claude = claude or AtrapaClaude()
        self.github = github or AtrapaGitHub()
        self.slack = AtrapaSlack()
        self._karta = karta if karta is not None else KARTA
        self.wczytania_karty = 0
        self.teraz = lambda: TERAZ

    def wczytaj_karte(self, klient):
        self.wczytania_karty += 1
        return self._karta() if callable(self._karta) else self._karta


# ── funkcje czyste ────────────────────────────────────────────────────────────

class TestFunkcjeCzyste(unittest.TestCase):

    def test_nazwa_galezi_z_identyfikatorem_zgloszenia(self):
        g = agent.nazwa_galezi(zgloszenie())
        self.assertTrue(g.startswith("rin-41-"), g)
        self.assertEqual(g, "rin-41-torun-podaje-sobote-do-14-00-zamiast-do")
        self.assertRegex(g, r"^rin-\d+-[a-z0-9-]+$")

    def test_slug_polskie_znaki_i_limit(self):
        self.assertEqual(agent.slug("Łódź: żółć, gęślą jaźń"), "lodz-zolc-gesla-jazn")
        self.assertLessEqual(len(agent.slug("x" * 100)), 40)
        self.assertEqual(agent.slug("!!!"), "zadanie")

    def test_rozbicie_opisu_na_sekcje(self):
        s = agent.rozbij_opis(zgloszenie()["description"])
        for n in ("Cel", "Kontekst", "Kryteria akceptacji", "Jak sprawdzić", "Czego nie ruszać", "Źródło"):
            self.assertIn(n, s)
        self.assertIn("- [ ] config: Toruń sobota do 15:00", s["Kryteria akceptacji"])

    def test_klient_z_tytulu(self):
        self.assertEqual(agent.klient_z_tytulu("[auto-tama] X"), "auto-tama")
        self.assertIsNone(agent.klient_z_tytulu("bez prefiksu"))


class TestZakazaneSciezki(unittest.TestCase):

    def test_dozwolone_tylko_config_i_wiedza(self):
        for s in ("config/auto-tama.yaml", "wiedza/auto-tama.md", "config/podkatalog/x.yaml"):
            self.assertTrue(agent.czy_dozwolona_sciezka(s, A), s)

    def test_zabronione_github_tests_zakazy_i_reszta(self):
        for s in (".github/workflows/testy.yml", "tests/test_config.py", "zakazy/auto-tama.json", "README.md",
                  ".coderabbit.yaml", "config", "configx/a.yaml", "src/app.py"):
            self.assertFalse(agent.czy_dozwolona_sciezka(s, A), s)

    def test_ucieczka_przez_kropki_i_sciezki_bezwzgledne(self):
        for s in ("config/../.github/workflows/testy.yml", "config/../tests/test_config.py", "../Rinvo/.env",
                  "/etc/passwd", "wiedza/../zakazy/auto-tama.json", "config\\..\\.github\\x"):
            self.assertFalse(agent.czy_dozwolona_sciezka(s, A), s)

    def test_sciezki_niedozwolone_zwraca_tylko_zle(self):
        zle = agent.sciezki_niedozwolone(["config/a.yaml", ".github/x", "tests/t.py", "wiedza/b.md", "zakazy/z.json"], A)
        self.assertEqual(zle, [".github/x", "tests/t.py", "zakazy/z.json"])


class TestSekrety(unittest.TestCase):

    def test_wzorce_kluczy_i_wartosci_srodowiska(self):
        self.assertTrue(agent.znajdz_sekrety("klucz lin_api_ABCDEFGH12345678"))
        self.assertTrue(agent.znajdz_sekrety("https://hooks.slack.com/services/T0/B0/xyz"))
        self.assertTrue(agent.znajdz_sekrety("ghp_" + "a" * 30))
        self.assertTrue(agent.znajdz_sekrety("tajny-token-123456", ["tajny-token-123456"]))
        self.assertEqual(agent.znajdz_sekrety("-14:00\n+15:00\n"), [])


# ── wybór kandydatów ──────────────────────────────────────────────────────────

class TestWyborKandydatow(unittest.TestCase):

    def test_tylko_dla_agenta_repo_rinvo_app_i_todo(self):
        zg = [zgloszenie(1), zgloszenie(2, etykiety=["Dla agenta"]), zgloszenie(3, etykiety=["repo: rinvo-app"]),
              zgloszenie(4, stan="In Progress"), zgloszenie(5, etykiety=["Dla agenta", "repo: rinvo"])]
        self.assertEqual([z["identifier"] for z in agent.wybierz_kandydatow(zg, Z)], ["RIN-1"])

    def test_pomijane_etykiety_wstrzymujace(self):
        baza = ["Dla agenta", "repo: rinvo-app"]
        zg = [zgloszenie(i, etykiety=baza + [e]) for i, e in
              enumerate(["Zablokowane przez zakaz", "Do weryfikacji", "Decyzja człowieka", "Czeka na klienta"], 1)]
        self.assertEqual(agent.wybierz_kandydatow(zg, Z), [])

    def test_kolejnosc_priorytet_potem_najstarsze(self):
        zg = [zgloszenie(1, priorytet=0, created="2026-10-01T00:00:00Z"), zgloszenie(2, priorytet=2, created="2026-10-05T00:00:00Z"),
              zgloszenie(3, priorytet=1, created="2026-10-09T00:00:00Z"), zgloszenie(4, priorytet=2, created="2026-10-02T00:00:00Z")]
        self.assertEqual([z["identifier"] for z in agent.wybierz_kandydatow(zg, Z)], ["RIN-3", "RIN-4", "RIN-2", "RIN-1"])


# ── limit 3 na przebieg ───────────────────────────────────────────────────────

class TestLimit(unittest.TestCase):

    def test_maksymalnie_3_zgloszenia_na_przebieg(self):
        s = Srodowisko([zgloszenie(i) for i in range(1, 7)])
        wyniki = agent.uruchom(s)
        self.assertEqual(len(wyniki), A["max_na_przebieg"])
        self.assertEqual(A["max_na_przebieg"], 3)
        self.assertEqual(sum(1 for w in s.git.wywolania if w[0] == "przygotuj"), 3)
        self.assertEqual({w["status"] for w in wyniki}, {"pr"})

    def test_parametr_max_nadpisuje_limit(self):
        s = Srodowisko([zgloszenie(i) for i in range(1, 7)])
        self.assertEqual(len(agent.uruchom(s, max_n=1)), 1)

    def test_zablokowane_zakazem_nie_zuzywaja_limitu(self):
        zg = [zgloszenie(i, tytul=f"Zadanie {'opel' if i <= 2 else 'zwykle'} {i}") for i in range(1, 6)]
        s = Srodowisko(zg, claude=AtrapaClaude(lambda p: '{"konflikt": true, "zakaz": "Z4", "powod": "włącza Opla"}'
                                               if "Zadanie opel" in p else '{"konflikt": false}'))
        wyniki = agent.uruchom(s)
        self.assertEqual([w["status"] for w in wyniki], ["zablokowane", "zablokowane", "pr", "pr", "pr"])


class TestCzegoNieRuszac(unittest.TestCase):
    """Sekcja „Czego nie ruszać”: krótkie tytuły zakazów, powiązane z tematem zgłoszenia na górze, bez cytatów."""

    KARTA2 = {"zakazy": [
        {"id": "Z1", "tytul": "Limit prób pozostaje 5", "opis": "x", "cytat": ["Zostaw pięć, to dosłowny cytat."]},
        {"id": "Z2", "tytul": "Nie podpinać agenta po godzinach", "opis": "x", "cytat": ["Trzymajcie u siebie."]},
        {"id": "Z3", "tytul": "Nie włączać Opla", "opis": "godzin dzwonienia w opisie nie liczą się", "cytat": ["Opla nie puszczamy."]},
        {"id": "Z4", "tytul": "Nic nowego w urlop Kasi", "opis": "", "cytat": ["urlop"]}], "decyzje_zastrzezone": []}

    def _sekcja(self, tytul, cel="", kryteria=()):
        item = {"sekcja": 1, "typ": "bug", "tytul": tytul, "cel": cel, "kryteria_akceptacji": list(kryteria), "opis": "o",
                "klucz_sprawy": "k", "cytat": ["c"], "repo": "rinvo-app"}
        d = linear_sync.build_description(item, "s.md", self.KARTA2, None, Z)
        return d[d.index("## Czego nie ruszać"):d.index("## Źródło")]

    def test_tylko_tytuly_bez_cytatow(self):
        t = self._sekcja("Zmiana godzin dzwonienia")
        self.assertIn("- Zakaz Z1: Limit prób pozostaje 5", t)
        for cytat in ("Zostaw pięć", "Trzymajcie u siebie", "Opla nie puszczamy"):
            self.assertNotIn(cytat, t)
        self.assertNotIn("_", t.replace("_brak", ""), "bez kursywy z cytatem")

    def test_zakazy_tej_samej_czesci_konfiguracji_na_gorze(self):
        t = self._sekcja("Zmiana godzin dzwonienia", "Godziny dzwonienia 9–19")
        self.assertLess(t.index("Zakaz Z2"), t.index("Zakaz Z1"))
        self.assertLess(t.index("Dotyczą tej samej części konfiguracji"), t.index("Zakaz Z2"))
        self.assertLess(t.index("Zakaz Z2"), t.index("Pozostałe zakazy klienta"))
        self.assertLess(t.index("Pozostałe zakazy klienta"), t.index("Zakaz Z1"))

    def test_limit_prob_i_marki_to_osobne_tematy(self):
        self.assertLess(self._sekcja("Limit prób do 3").index("Zakaz Z1"), self._sekcja("Limit prób do 3").index("Pozostałe"))
        t = self._sekcja("Włączyć Opla we Włocławku")
        self.assertLess(t.index("Zakaz Z3"), t.index("Pozostałe"))
        self.assertGreater(t.index("Zakaz Z2"), t.index("Pozostałe"), "godziny to inny temat niż marki")

    def test_temat_nie_pasuje_to_jedna_lista_bez_naglowkow(self):
        t = self._sekcja("Zmiana koloru logo")
        self.assertNotIn("Dotyczą tej samej", t)
        self.assertNotIn("Pozostałe zakazy", t)
        self.assertEqual(t.count("- Zakaz"), 4)

    def test_opis_zakazu_nie_decyduje_o_powiazaniu(self):
        t = self._sekcja("Zmiana godzin dzwonienia")
        self.assertGreater(t.index("Zakaz Z3"), t.index("Pozostałe"))

    def test_pr_przenosi_krotka_liste_ze_zgloszenia(self):
        item = {"sekcja": 1, "typ": "bug", "tytul": "Godziny", "cel": "godziny", "opis": "o", "klucz_sprawy": "k", "cytat": ["Toruń dalej."], "repo": "rinvo-app"}
        zg = {"id": "i", "identifier": "RIN-5", "title": "[x] Godziny", "url": "u",
              "description": linear_sync.build_description(item, "s.md", self.KARTA2, None, Z)}
        opis = agent.buduj_opis_pr(zg, agent.rozbij_opis(zg["description"]))
        self.assertIn("- Zakaz Z2: Nie podpinać agenta po godzinach", opis)
        self.assertNotIn("Trzymajcie u siebie", opis)


# ── ponowne sprawdzenie zakazów ───────────────────────────────────────────────

class TestPonowneSprawdzenieZakazow(unittest.TestCase):

    def test_decyzja_zastrzezona_z_karty_blokuje_bez_pytania_modelu(self):
        zg = zgloszenie(70, "Włączyć Opla w Włocławku")
        s = Srodowisko([zg])
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "zablokowane")
        self.assertIn("decyzja zastrzeżona dla Kasia Malinowska", w["powod"])
        self.assertEqual(s.claude.pytania, [], "decyzje zastrzeżone rozstrzyga kod, nie model")
        self.assertEqual(s.git.wywolania, [], "nic nie sklonowano")
        self.assertIn(("etykieta", "RIN-70", "Zablokowane przez zakaz"), s.linear.zdarzenia)
        self.assertEqual(s.linear.typy("stan"), [], "stan zgłoszenia bez zmian")
        self.assertTrue(any("zakaz" in k[2].lower() for k in s.linear.zdarzenia if k[0] == "komentarz"))

    def test_konflikt_z_zakazem_stwierdzony_przez_model(self):
        s = Srodowisko([zgloszenie(41)], claude=AtrapaClaude('Oto wynik: {"konflikt": true, "zakaz": "Z4", "powod": "włącza zakazaną markę"}'))
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "zablokowane")
        self.assertIn("zakaz Z4: włącza zakazaną markę", w["powod"])
        self.assertIn(("etykieta", "RIN-41", "Zablokowane przez zakaz"), s.linear.zdarzenia)
        self.assertEqual(s.linear.typy("stan"), [])
        self.assertEqual(s.git.wywolania, [])

    def test_sprawdzenie_uzywa_aktualnej_karty_a_nie_starej(self):
        """Zakaz dodany do karty między przebiegami musi trafić do pytania o konflikt."""
        karta = copy.deepcopy(KARTA)
        wczytania = {"n": 0}

        def aktualna():
            wczytania["n"] += 1
            if wczytania["n"] >= 2:                       # drugi przebieg widzi nowy zakaz
                karta["zakazy"].append({"id": "Z99", "tytul": "Nie zmieniać godzin Torunia", "opis": "", "cytat": []})
            return copy.deepcopy(karta)

        claude = AtrapaClaude(lambda p: '{"konflikt": true, "zakaz": "Z99", "powod": "zmienia godziny Torunia"}' if "Z99" in p
                              else '{"konflikt": false, "zakaz": null, "powod": ""}')
        s = Srodowisko([zgloszenie(41)], claude=claude, karta=aktualna)
        self.assertEqual(agent.uruchom(s)[0]["status"], "pr", "pierwszy przebieg: zakazu jeszcze nie ma")
        s.linear.zgloszenia = [zgloszenie(41)]
        self.assertEqual(agent.uruchom(s)[0]["status"], "zablokowane", "drugi: nowy zakaz z aktualnej karty")
        self.assertEqual(s.wczytania_karty, 2, "karta wczytywana przy każdym zgłoszeniu")
        self.assertIn("Z99", s.claude.pytania[-1])

    def test_nieczytelna_odpowiedz_modelu_to_pominiecie_bez_zmian_w_linearze(self):
        s = Srodowisko([zgloszenie(41)], claude=AtrapaClaude("nie wiem"))
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pominiete")
        self.assertEqual(s.linear.zdarzenia, [], "fail-closed: niczego nie zmieniamy")
        self.assertEqual(s.git.wywolania, [])

    def test_blad_modelu_przy_sprawdzaniu_to_pominiecie(self):
        def pada(prompt):
            raise RuntimeError("claude niedostępny")
        s = Srodowisko([zgloszenie(41)], claude=AtrapaClaude(pada))
        self.assertEqual(agent.uruchom(s)[0]["status"], "pominiete")
        self.assertEqual(s.linear.zdarzenia, [])

    def test_prompt_zakazow_zawiera_zakazy_i_traktuje_zgloszenie_jako_dane(self):
        zg = zgloszenie(41)
        p = agent.prompt_zakazow(KARTA, zg, agent.rozbij_opis(zg["description"]))
        self.assertIn("Z4", p)
        self.assertIn("DANE", p)
        self.assertIn("JSON", p)


# ── przebieg zgłoszenia ───────────────────────────────────────────────────────

class TestPrzebiegZgloszenia(unittest.TestCase):

    def test_pelny_przebieg_do_pr_z_komentarzami_w_linearze(self):
        s = Srodowisko([zgloszenie(41)])
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pr")
        self.assertEqual(w["pr"], "https://github.com/Rembolekk/Rinvo-app/pull/7")
        # kolejność: przejęcie (In Progress + komentarz), potem link do PR
        zd = s.linear.zdarzenia
        self.assertEqual(zd[0], ("stan", "RIN-41", "In Progress"))
        self.assertEqual(zd[1], ("komentarz", "RIN-41", "Agent przejął"))
        self.assertIn("https://github.com/Rembolekk/Rinvo-app/pull/7", zd[2][2])
        self.assertEqual(s.git.wywolania[0], ("przygotuj", "rin-41-torun-podaje-sobote-do-14-00-zamiast-do"))
        self.assertEqual(s.git.push[0][0], "rin-41-torun-podaje-sobote-do-14-00-zamiast-do")
        self.assertIn("Fixes RIN-41", s.git.push[0][1])

    def test_pr_ma_tytul_ze_zgloszenia_i_opis_z_wymaganymi_sekcjami(self):
        s = Srodowisko([zgloszenie(41)])
        agent.uruchom(s)
        pr = s.github.utworzone[0]
        self.assertEqual(pr["tytul"], "[auto-tama] Toruń podaje sobotę do 14:00 zamiast do 15:00")
        opis = pr["opis"]
        self.assertTrue(opis.startswith("Fixes RIN-41"))
        self.assertIn("- [ ] config: Toruń sobota do 15:00", opis, "kryteria jako lista")
        self.assertIn("> Toruń dalej po staremu.", opis, "cytat klienta")
        self.assertIn("## Czego nie ruszać", opis)
        self.assertIn("Zakaz Z4", opis)

    def test_slack_milczy_gdy_pr_otwarty_a_nie_skonczony(self):
        s = Srodowisko([zgloszenie(41)])
        agent.uruchom(s)
        self.assertEqual(s.slack.wiadomosci, [])

    def test_prompt_dla_modelu_ma_opis_zgloszenia_i_zasady_sciezek(self):
        s = Srodowisko([zgloszenie(41)])
        agent.uruchom(s)
        p = s.claude.prompty_edycji[0]
        self.assertIn("WYŁĄCZNIE pliki w config/ i wiedza/", p)
        self.assertIn("Nigdy .github/, tests/ ani zakazy/", p)
        self.assertIn("Toruń podaje w sobotę godziny do 15:00.", p, "cel")
        self.assertIn("config: Toruń sobota do 15:00", p, "kryteria")
        self.assertIn("Przejrzeć config i wiedzę.", p, "jak sprawdzić")
        self.assertIn("Zakaz Z4", p, "czego nie ruszać")
        self.assertIn("config/auto-tama.yaml", p)
        self.assertIn("DANE", p)

    def test_zmiany_poza_dozwolonymi_sciezkami_sa_cofane_a_pr_ich_nie_zawiera(self):
        git = AtrapaGit(zmienione=["config/auto-tama.yaml", ".github/workflows/testy.yml", "tests/test_config.py",
                                   "zakazy/auto-tama.json", "wiedza/auto-tama.md"])
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pr")
        self.assertEqual(sorted(git.cofniete), [".github/workflows/testy.yml", "tests/test_config.py", "zakazy/auto-tama.json"])
        self.assertTrue(any("Cofnięto zmiany poza dozwolonymi ścieżkami" in k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"))

    def test_commit_zawiera_tylko_dozwolone_pliki_nawet_gdy_testy_zostawily_smieci(self):
        """Regresja: tests/__pycache__/*.pyc po uruchomieniu testów trafiały do commita."""
        git = AtrapaGit(zmienione=["config/auto-tama.yaml", "wiedza/auto-tama.md", "tests/__pycache__/wspolne.cpython-312.pyc",
                                   "tests/__pycache__/test_config.cpython-312.pyc"])
        git.cofnij = lambda katalog, sciezki: None            # strażnik po edycji nie widzi śmieci: powstają dopiero przy testach
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pr")
        self.assertEqual(git.commitowane, ["config/auto-tama.yaml", "wiedza/auto-tama.md"])
        self.assertEqual(git.diff_pliki, ["config/auto-tama.yaml", "wiedza/auto-tama.md"], "sekrety skanowane w tym, co idzie do commita")

    def test_pliki_do_commita_loguje_pominiete(self):
        logi = []
        ok, pom = agent.pliki_do_commita(["config/a.yaml", "tests/__pycache__/x.pyc", ".github/x.yml", "wiedza/b.md"], A, logi.append)
        self.assertEqual(ok, ["config/a.yaml", "wiedza/b.md"])
        self.assertEqual(pom, ["tests/__pycache__/x.pyc", ".github/x.yml"])
        self.assertIn("tests/__pycache__/x.pyc", logi[0])
        logi.clear()
        agent.pliki_do_commita(["config/a.yaml"], A, logi.append)
        self.assertEqual(logi, [])

    def test_tylko_zmiany_zabronione_to_oddanie_bo_nic_nie_zostaje(self):
        git = AtrapaGit(zmienione=[".github/workflows/testy.yml", "tests/t.py"])
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "oddane")
        self.assertEqual(s.github.utworzone, [])

    def test_agent_nie_wprowadzil_zmian_to_oddanie(self):
        s = Srodowisko([zgloszenie(41)], git=AtrapaGit(zmienione=[]))
        self.assertEqual(agent.uruchom(s)[0]["status"], "oddane")

    def test_za_duzo_plikow_to_oddanie(self):
        git = AtrapaGit(zmienione=[f"config/k{i}.yaml" for i in range(A["max_plikow"] + 1)])
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "oddane")
        self.assertIn("limit", w["powod"])

    def test_sekret_w_diffie_blokuje_wypchniecie(self):
        git = AtrapaGit(diff="+token: lin_api_ABCDEFGH12345678\n")
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "oddane")
        self.assertEqual(git.push, [])
        self.assertEqual(s.github.utworzone, [])

    def test_wyjatek_w_trakcie_wykonania_to_oddanie_a_nie_zawieszenie_w_in_progress(self):
        s = Srodowisko([zgloszenie(41)], claude=AtrapaClaude(blad_edycji="claude padł"))
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "oddane")
        self.assertIn(("stan", "RIN-41", "Todo"), s.linear.zdarzenia)


# ── testy: jedna poprawka, potem oddanie ──────────────────────────────────────

class TestTestyIOddanie(unittest.TestCase):

    def test_testy_zielone_za_pierwszym_razem_bez_poprawki(self):
        s = Srodowisko([zgloszenie(41)], git=AtrapaGit([(True, "OK")]))
        agent.uruchom(s)
        self.assertEqual(s.git.testy_uruchomienia, 1)
        self.assertEqual(len(s.claude.prompty_edycji), 1)

    def test_jedna_poprawka_i_testy_zielone_to_pr(self):
        s = Srodowisko([zgloszenie(41)], git=AtrapaGit([(False, "FAIL: godziny"), (True, "OK")]))
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pr")
        self.assertEqual(s.git.testy_uruchomienia, 2)
        self.assertEqual(len(s.claude.prompty_edycji), 2, "edycja + jedna poprawka")
        self.assertIn("FAIL: godziny", s.claude.prompty_edycji[1], "poprawka dostaje wynik testów")

    def test_oddanie_po_dwoch_nieudanych_testach(self):
        git = AtrapaGit([(False, "FAIL 1"), (False, "FAIL 2: Toruń w wiedzy różni się od config")])
        s = Srodowisko([zgloszenie(41)], git=git)
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "oddane")
        self.assertEqual(git.testy_uruchomienia, 2, "testy dokładnie dwa razy: przed i po jednej poprawce")
        self.assertEqual(len(s.claude.prompty_edycji), 2, "jedna edycja i jedna poprawka, nie więcej")
        self.assertEqual(git.push, [], "bez wypchnięcia")
        self.assertEqual(s.github.utworzone, [], "bez PR")
        zd = s.linear.zdarzenia
        self.assertIn(("etykieta", "RIN-41", "Do weryfikacji"), zd)
        self.assertEqual(zd[-1], ("stan", "RIN-41", "Todo"), "stan z powrotem Todo")
        komentarz = next(z[2] for z in zd if z[0] == "komentarz" and "oddał" in z[2])
        self.assertIn("testy nie przechodzą", komentarz)
        self.assertIn("różni się od config", komentarz, "powód zawiera końcówkę wyniku testów")

    def test_slack_przy_oddaniu_krotko_z_powodem(self):
        s = Srodowisko([zgloszenie(41)], git=AtrapaGit([(False, "x"), (False, "y")]))
        agent.uruchom(s)
        self.assertEqual(len(s.slack.wiadomosci), 1)
        self.assertTrue(s.slack.wiadomosci[0].startswith(":raising_hand: Agent oddał: <https://linear.app/ws/issue/RIN-41/x|"))
        self.assertIn("testy nie przechodzą", s.slack.wiadomosci[0])

    def test_poprawka_modelu_poza_sciezkami_tez_jest_cofana(self):
        git = AtrapaGit([(False, "FAIL"), (True, "OK")], zmienione=["config/a.yaml", "tests/t.py"])
        s = Srodowisko([zgloszenie(41)], git=git)
        agent.uruchom(s)
        self.assertIn("tests/t.py", git.cofniete)


# ── scalanie: warunki ─────────────────────────────────────────────────────────

def fakty(**kw):
    f = {"pliki": ["config/auto-tama.yaml", "wiedza/auto-tama.md"], "etykiety_zgloszenia": ["Konfiguracja", "Dla agenta"],
         "testy": "success", "coderabbit_ci": "success", "recenzja": {"commit": "abc", "uwagi": 0, "komentarze": []},
         "sha": "abc", "poprawki": 0, "wiek_godzin": 1.0}
    f.update(kw)
    return f


class TestWarunkiScalania(unittest.TestCase):

    def test_scala_gdy_wszystkie_warunki_jednoczesnie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(), A)["akcja"], "scal")

    def test_testy_czerwone_to_oddanie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(testy="failure"), A)["akcja"], "oddaj")

    def test_testy_w_toku_to_czekanie(self):
        for stan in ("pending", "none"):
            self.assertEqual(agent_scal.ocen_pr(fakty(testy=stan), A)["akcja"], "czekaj", stan)

    def test_brak_wyniku_testow_po_dwoch_godzinach_to_oddanie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(testy="none", wiek_godzin=3), A)["akcja"], "oddaj")

    def test_coderabbit_jeszcze_nie_zakonczyl_to_czekanie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(recenzja=None), A)["akcja"], "czekaj")
        self.assertEqual(agent_scal.ocen_pr(fakty(coderabbit_ci="pending"), A)["akcja"], "czekaj")
        self.assertEqual(agent_scal.ocen_pr(fakty(recenzja={"commit": "stary", "uwagi": 0, "komentarze": []}), A)["akcja"], "czekaj",
                         "recenzja nie dotyczy ostatniego commita")

    def test_brak_recenzji_coderabbit_po_terminie_to_oddanie(self):
        d = agent_scal.ocen_pr(fakty(recenzja=None, wiek_godzin=A["czekaj_na_coderabbit_godzin"] + 1), A)
        self.assertEqual(d["akcja"], "oddaj")
        self.assertIn("brak recenzji CodeRabbit", d["powod"])

    def test_blad_sprawdzenia_coderabbit_to_oddanie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(coderabbit_ci="failure"), A)["akcja"], "oddaj")

    def test_uwagi_coderabbit_pierwszy_raz_to_poprawka(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(recenzja={"commit": "abc", "uwagi": 2, "komentarze": []}), A)["akcja"], "popraw")

    def test_uwagi_po_poprawce_to_oddanie(self):
        d = agent_scal.ocen_pr(fakty(recenzja={"commit": "abc", "uwagi": 1, "komentarze": []}, poprawki=1), A)
        self.assertEqual(d["akcja"], "oddaj")
        self.assertIn("po poprawce", d["powod"])

    def test_zmiana_poza_config_i_wiedza_to_oddanie_mimo_zielonych_testow(self):
        for pliki in (["config/a.yaml", ".github/workflows/x.yml"], ["tests/t.py"], ["zakazy/a.json", "config/a.yaml"],
                      ["README.md"], ["config/../.github/x"]):
            d = agent_scal.ocen_pr(fakty(pliki=pliki), A)
            self.assertEqual(d["akcja"], "oddaj", pliki)
            self.assertIn("poza dozwolone ścieżki", d["powod"])

    def test_zgloszenie_innego_typu_niz_konfiguracja_to_oddanie(self):
        for et in (["Błąd", "Dla agenta"], ["Produkt", "Dla agenta"], ["Dla agenta"]):
            self.assertEqual(agent_scal.ocen_pr(fakty(etykiety_zgloszenia=et), A)["akcja"], "oddaj", et)

    def test_pusty_pr_to_oddanie(self):
        self.assertEqual(agent_scal.ocen_pr(fakty(pliki=[]), A)["akcja"], "oddaj")

    def test_kazdy_warunek_osobno_blokuje_scalenie(self):
        """Wszystkie cztery warunki muszą być spełnione JEDNOCZEŚNIE: złamanie którejkolwiek daje brak scalenia."""
        zepsute = [fakty(testy="failure"), fakty(recenzja={"commit": "abc", "uwagi": 1, "komentarze": []}, poprawki=1),
                   fakty(pliki=["tests/t.py"]), fakty(etykiety_zgloszenia=["Błąd"])]
        for f in zepsute:
            self.assertNotEqual(agent_scal.ocen_pr(f, A)["akcja"], "scal")


class TestKlientGitHubCzyste(unittest.TestCase):

    def test_stan_testow(self):
        ok = {"name": "testy", "status": "completed", "conclusion": "success"}
        self.assertEqual(ag.stan_testow([ok]), "success")
        self.assertEqual(ag.stan_testow([{**ok, "conclusion": "failure"}]), "failure")
        self.assertEqual(ag.stan_testow([{**ok, "status": "in_progress", "conclusion": None}]), "pending")
        self.assertEqual(ag.stan_testow([{"name": "inne", "status": "completed", "conclusion": "success"}]), "none")

    def test_stan_coderabbit_z_check_runow_i_statusow(self):
        self.assertEqual(ag.stan_coderabbit_ci([{"name": "CodeRabbit", "status": "completed", "conclusion": "success"}], []), "success")
        self.assertEqual(ag.stan_coderabbit_ci([], [{"context": "CodeRabbit", "state": "pending"}]), "pending")
        self.assertEqual(ag.stan_coderabbit_ci([], [{"context": "CodeRabbit", "state": "failure"}]), "failure")
        self.assertEqual(ag.stan_coderabbit_ci([], []), "none")
        self.assertEqual(ag.stan_coderabbit_ci([{"name": "CodeRabbit", "status": "completed", "conclusion": "success"}],
                                               [{"context": "coderabbit", "state": "pending"}]), "pending", "najgorszy stan wygrywa")

    def test_ostatnia_recenzja_coderabbit_liczba_uwag(self):
        bot = {"login": "coderabbitai[bot]"}
        recenzje = [{"id": 1, "user": bot, "submitted_at": "2026-10-14T10:00:00Z", "commit_id": "a", "body": "Actionable comments posted: 3", "state": "COMMENTED"},
                    {"id": 2, "user": bot, "submitted_at": "2026-10-14T11:00:00Z", "commit_id": "b", "body": "Actionable comments posted: 0", "state": "COMMENTED"},
                    {"id": 3, "user": {"login": "ktos"}, "submitted_at": "2026-10-14T12:00:00Z", "commit_id": "c", "body": "", "state": "COMMENTED"}]
        r = ag.ostatnia_recenzja_coderabbit(recenzje, [])
        self.assertEqual((r["commit"], r["uwagi"]), ("b", 0), "ostatnia recenzja bota, nie innej osoby")

    def test_uwagi_z_komentarzy_inline_gdy_brak_naglowka_i_zatwierdzenie(self):
        bot = {"login": "coderabbitai[bot]"}
        rec = [{"id": 9, "user": bot, "submitted_at": "2026-10-14T10:00:00Z", "commit_id": "a", "body": "Podsumowanie", "state": "COMMENTED"}]
        inline = [{"pull_request_review_id": 9, "path": "config/a.yaml", "line": 3, "body": "Błąd godzin"},
                  {"pull_request_review_id": 5, "path": "x", "line": 1, "body": "inny"}]
        r = ag.ostatnia_recenzja_coderabbit(rec, inline)
        self.assertEqual(r["uwagi"], 1)
        self.assertEqual(r["komentarze"][0]["sciezka"], "config/a.yaml")
        rec[0]["state"] = "APPROVED"
        self.assertEqual(ag.ostatnia_recenzja_coderabbit(rec, inline)["uwagi"], 0)

    def test_brak_recenzji_coderabbit_to_none(self):
        self.assertIsNone(ag.ostatnia_recenzja_coderabbit([], []))

    def test_klient_nie_ujawnia_tokenu_w_bledzie(self):
        e = ag.GitHubError(404, "Not Found")
        self.assertNotIn("token", str(e).lower())


# ── scalanie: przebieg ────────────────────────────────────────────────────────

def pr(numer=7, sha="abc", ref="rin-41-torun", body="Fixes RIN-41\n\n## Cel"):
    return {"number": numer, "title": "[auto-tama] Toruń sobota", "html_url": f"https://github.com/Rembolekk/Rinvo-app/pull/{numer}",
            "head": {"sha": sha, "ref": ref}, "body": body, "created_at": "2026-10-14T11:00:00Z"}


BOT = {"login": "coderabbitai[bot]"}


def recenzja(commit="abc", uwagi=0, id_=1):
    return {"id": id_, "user": BOT, "submitted_at": "2026-10-14T11:30:00Z", "commit_id": commit,
            "body": f"Actionable comments posted: {uwagi}", "state": "COMMENTED"}


def srodowisko_scalania(zg=None, **gh_kw):
    zg = zg if zg is not None else zgloszenie(41, stan="In Progress")
    s = Srodowisko([zg], github=AtrapaGitHub(prs=[pr()], **gh_kw))
    return s


class TestPrzebiegScalania(unittest.TestCase):

    def test_czekanie_na_coderabbit_liczone_od_ostatniego_commita_a_nie_od_utworzenia_pr(self):
        """Po wypchnięciu poprawki stary PR dostaje pełny czas na nową recenzję."""
        s = srodowisko_scalania(recenzje=[])                     # PR z 11:00, jest 12:00; brak recenzji
        s.github.prs = [{**pr(), "created_at": "2026-10-10T11:00:00Z"}]     # PR sprzed 4 dni
        s.github.data_commita = lambda sha: "2026-10-14T11:45:00Z"           # ale commit sprzed 15 minut
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "czekaj")
        s2 = srodowisko_scalania(recenzje=[])
        s2.github.data_commita = lambda sha: "2026-10-10T11:00:00Z"
        self.assertEqual(agent_scal.uruchom_scalanie(s2)[0]["akcja"], "oddane", "stary commit bez recenzji: oddanie")

    def test_pr_agenta_rozpoznawany_po_galezi_i_fixes(self):
        self.assertTrue(agent_scal.pr_agenta(pr()))
        self.assertFalse(agent_scal.pr_agenta(pr(ref="feature-x")))
        self.assertFalse(agent_scal.pr_agenta(pr(body="bez powiązania")))
        self.assertEqual(agent_scal.numer_zgloszenia(pr()), 41)

    def test_scalenie_squash_zgloszenie_done_i_slack_naprawil(self):
        s = srodowisko_scalania(recenzje=[recenzja()])
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "scalone")
        self.assertEqual(len(s.github.scalone), 1)
        self.assertIn(("stan", "RIN-41", "Done"), s.linear.zdarzenia)
        self.assertEqual(len(s.slack.wiadomosci), 1)
        self.assertTrue(s.slack.wiadomosci[0].startswith(":white_check_mark: Agent naprawił: <https://github.com/Rembolekk/Rinvo-app/pull/7|"))

    def test_czekanie_nie_zmienia_niczego_i_nie_wysyla_slacka(self):
        s = srodowisko_scalania(recenzje=[])          # CodeRabbit jeszcze nie zrecenzował
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "czekaj")
        self.assertEqual((s.github.scalone, s.linear.zdarzenia, s.slack.wiadomosci), ([], [], []))

    def test_pr_poza_config_i_wiedza_etykieta_decyzja_czlowieka_z_powodem_przeglad_kodu(self):
        s = srodowisko_scalania(recenzje=[recenzja()], pliki=["config/auto-tama.yaml", ".github/workflows/x.yml"])
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oddane")
        self.assertTrue(w["powod"].startswith("przegląd kodu:"))
        self.assertEqual(s.github.scalone, [], "nie scala")
        self.assertIn(("etykieta", "RIN-41", "Decyzja człowieka"), s.linear.zdarzenia)
        komentarz = next(z[2] for z in s.linear.zdarzenia if z[0] == "komentarz")
        self.assertIn("przegląd kodu", komentarz)
        self.assertTrue(any("przegląd kodu" in k[1] for k in s.github.dodane_komentarze))
        self.assertTrue(s.slack.wiadomosci[0].startswith(":raising_hand: Agent oddał:"))

    def test_uwagi_coderabbit_poprawka_raz_potem_oddanie(self):
        inline = [{"pull_request_review_id": 1, "path": "config/auto-tama.yaml", "line": 12, "body": "Godziny nie zgadzają się z wiedzą"}]
        s = srodowisko_scalania(recenzje=[recenzja(uwagi=1)], inline=inline)
        w1 = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w1["akcja"], "poprawione")
        self.assertEqual(len(s.git.push), 1, "poprawka wypchnięta")
        self.assertIn("Godziny nie zgadzają się z wiedzą", s.claude.prompty_edycji[0])
        self.assertEqual(s.github.scalone, [])
        self.assertTrue(any(agent_scal.ZNACZNIK_POPRAWKI in k[1] for k in s.github.dodane_komentarze))
        # kolejny przebieg: nowy commit po poprawce, CodeRabbit dalej zgłasza uwagi → oddanie człowiekowi
        s.github.prs = [pr(sha="nowy")]
        s.github.recenzje_lista = [recenzja(commit="nowy", uwagi=2, id_=2)]
        w2 = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w2["akcja"], "oddane")
        self.assertIn("po poprawce", w2["powod"])
        self.assertIn(("etykieta", "RIN-41", "Decyzja człowieka"), s.linear.zdarzenia)
        self.assertEqual(len(s.git.push), 1, "druga poprawka nie powstaje")

    def test_poprawka_ktora_psuje_testy_to_oddanie(self):
        git = AtrapaGit([(False, "FAIL")])
        s = Srodowisko([zgloszenie(41, stan="In Progress")], git=git,
                       github=AtrapaGitHub(prs=[pr()], recenzje=[recenzja(uwagi=1)]))
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oddane")
        self.assertEqual(git.push, [])

    def test_poprawka_zmienia_tylko_dozwolone_sciezki(self):
        git = AtrapaGit(zmienione=["config/a.yaml", "tests/t.py"])
        s = Srodowisko([zgloszenie(41, stan="In Progress")], git=git,
                       github=AtrapaGitHub(prs=[pr()], recenzje=[recenzja(uwagi=1)]))
        agent_scal.uruchom_scalanie(s)
        self.assertEqual(git.cofniete, ["tests/t.py"])

    def test_zgloszenie_typu_blad_nie_jest_scalane_automatycznie(self):
        s = srodowisko_scalania(zgloszenie(41, etykiety=["Błąd", "Dla agenta", "repo: rinvo-app"], stan="In Progress"), recenzje=[recenzja()])
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "oddane")
        self.assertEqual(s.github.scalone, [])

    def test_zakonczone_albo_oddane_zgloszenia_sa_pomijane(self):
        for zg in (zgloszenie(41, stan="Done"), zgloszenie(41, etykiety=["Konfiguracja", "Decyzja człowieka"], stan="In Progress")):
            s = srodowisko_scalania(zg, recenzje=[recenzja()])
            self.assertEqual(agent_scal.uruchom_scalanie(s), [])
            self.assertEqual(s.github.scalone, [])

    def test_obce_pr_sa_ignorowane(self):
        s = srodowisko_scalania(recenzje=[recenzja()])
        s.github.prs = [pr(ref="dependabot/pip/x"), pr(numer=9, body="bez fixes")]
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])

    def test_blad_scalenia_to_oddanie_a_nie_done(self):
        s = srodowisko_scalania(recenzje=[recenzja()], blad_scalenia="konflikt")
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "oddane")
        self.assertNotIn(("stan", "RIN-41", "Done"), s.linear.zdarzenia)

    def test_testy_czerwone_na_pr_to_oddanie_bez_scalenia(self):
        s = srodowisko_scalania(recenzje=[recenzja()], runy=[{"name": "testy", "status": "completed", "conclusion": "failure"}])
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "oddane")
        self.assertEqual(s.github.scalone, [])


# ── powrót PR oddanego człowiekowi na ścieżkę scalania ────────────────────────

ODDANIE_STARE = {"body": "Agent oddaje ten PR człowiekowi (przegląd kodu: zmiana wychodzi poza dozwolone ścieżki: "
                         "tests/__pycache__/x.pyc). Automatyczne scalenie wstrzymane."}


def srodowisko_oddane(komentarze=(ODDANIE_STARE,), etykiety=("Konfiguracja", "Decyzja człowieka"), **gh_kw):
    zg = zgloszenie(41, etykiety=etykiety, stan="In Progress")
    return Srodowisko([zg], github=AtrapaGitHub(prs=[pr()], komentarze=list(komentarze), **gh_kw))


class TestPowrotDoScalania(unittest.TestCase):

    def test_pr_agenta_z_etykieta_decyzja_czlowieka_nie_odpada_przy_rozpoznaniu(self):
        """Rozpoznanie PR agenta (gałąź rin-N-… + „Fixes RIN-N”) nie zależy od etykiety w Linearze."""
        self.assertTrue(agent_scal.pr_agenta(pr()))

    def test_przyczyna_zniknela_pr_wraca_i_jest_scalany(self):
        s = srodowisko_oddane(recenzje=[recenzja()])               # pliki już czyste, testy zielone, CodeRabbit bez uwag
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "scalone")
        self.assertNotIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        self.assertIn(("-etykieta", "RIN-41", "Decyzja człowieka"), s.linear.zdarzenia)
        self.assertIn(("stan", "RIN-41", "Done"), s.linear.zdarzenia)
        self.assertTrue(any(agent_scal.ZNACZNIK_WZNOWIENIA in k[1] for k in s.github.dodane_komentarze))
        self.assertTrue(any("wznawia scalanie" in k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"))
        self.assertEqual(len(s.github.scalone), 1)

    def test_przyczyna_zniknela_ale_coderabbit_jeszcze_nie_skonczyl_pr_wraca_i_czeka(self):
        s = srodowisko_oddane(recenzje=[])
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "czekaj")
        self.assertNotIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"], "wrócił na ścieżkę, choć jeszcze nie scalony")
        self.assertEqual(s.github.scalone, [])
        self.assertEqual(s.slack.wiadomosci, [], "bez Slacka: dopiero scalenie albo oddanie")

    def test_przyczyna_nadal_jest_pr_zostaje_oddany_bez_powtarzania_komentarzy(self):
        s = srodowisko_oddane(recenzje=[recenzja()], pliki=["config/a.yaml", "tests/__pycache__/x.pyc"])
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])
        self.assertIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        self.assertEqual((s.linear.zdarzenia, s.github.dodane_komentarze, s.slack.wiadomosci, s.github.scalone), ([], [], [], []))

    def test_etykieta_nalozona_przez_czlowieka_zostaje(self):
        s = srodowisko_oddane(komentarze=[], recenzje=[recenzja()])
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])
        self.assertIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        self.assertEqual(s.github.scalone, [])

    def test_czlowiek_po_wznowieniu_ponownie_oddaje_i_agent_nie_wraca_na_sile(self):
        kom = [ODDANIE_STARE, {"body": f"Przyczyna oddania zniknęła, agent wznawia scalanie. {agent_scal.ZNACZNIK_WZNOWIENIA}"}]
        s = srodowisko_oddane(komentarze=kom, recenzje=[recenzja()])          # etykieta znów jest, ale po wznowieniu: to człowiek
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])
        self.assertIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        self.assertEqual(s.github.scalone, [])

    def test_nowe_oddanie_po_wznowieniu_znowu_pozwala_wrocic(self):
        kom = [ODDANIE_STARE, {"body": f"x {agent_scal.ZNACZNIK_WZNOWIENIA}"}, {"body": f"Agent oddaje ten PR człowiekowi (przegląd kodu: y). {agent_scal.ZNACZNIK_ODDANIA}"}]
        self.assertEqual(agent_scal.stan_oddania(kom), "oddane")
        self.assertIsNone(agent_scal.stan_oddania([{"body": "zwykły komentarz"}]))
        self.assertEqual(agent_scal.stan_oddania([{"body": f"{agent_scal.ZNACZNIK_WZNOWIENIA}"}]), "wznowione")

    def test_oddanie_zapisuje_znacznik_i_wskazuje_ze_agent_wznowi(self):
        s = srodowisko_scalania(recenzje=[recenzja()], pliki=["config/a.yaml", ".github/x.yml"])
        agent_scal.uruchom_scalanie(s)
        tekst = s.github.dodane_komentarze[0][1]
        self.assertIn(agent_scal.ZNACZNIK_ODDANIA, tekst)
        self.assertIn("agent sam wznowi", tekst)
        self.assertEqual(agent_scal.stan_oddania([{"body": tekst}]), "oddane")

    def test_zakonczone_zgloszenie_nie_wraca(self):
        zg = zgloszenie(41, etykiety=("Konfiguracja", "Decyzja człowieka"), stan="Done")
        s = Srodowisko([zg], github=AtrapaGitHub(prs=[pr()], komentarze=[ODDANIE_STARE], recenzje=[recenzja()]))
        self.assertEqual(agent_scal.uruchom_scalanie(s), [])
        self.assertEqual(s.github.scalone, [])

    def test_pelny_cykl_oddanie_potem_naprawa_potem_scalenie(self):
        s = srodowisko_scalania(recenzje=[recenzja()], pliki=["config/a.yaml", "tests/__pycache__/x.pyc"])
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "oddane")
        self.assertIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])
        s.github.pliki = ["config/a.yaml"]                         # usunięto .pyc z gałęzi
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "scalone")
        self.assertNotIn("Decyzja człowieka", s.linear.zgloszenia[0]["labels"])


# ── CodeRabbit bez obiektu recenzji (samo podsumowanie + zielony status) ───────

def podsumowanie_cr(tresc="## Walkthrough\nZmiany w konfiguracji."):
    return {"user": BOT, "body": tresc}


STATUS_CR = [{"context": "CodeRabbit", "state": "success", "description": "Review completed"}]


class TestCodeRabbitBezRecenzji(unittest.TestCase):

    def test_podsumowanie_i_zielony_status_dla_commita_to_brak_uwag(self):
        r = ag.ocena_coderabbit([], [], [podsumowanie_cr()], STATUS_CR, "abc")
        self.assertEqual((r["commit"], r["uwagi"]), ("abc", 0))

    def test_review_skipped_to_nie_recenzja(self):
        self.assertIsNone(ag.ocena_coderabbit([], [], [podsumowanie_cr("> ## Review skipped\n> Files ignored due to path filters")], STATUS_CR, "abc"))
        for marker in ("Review failed", "rate limit exceeded", "Reviews paused"):
            self.assertIsNone(ag.ocena_coderabbit([], [], [podsumowanie_cr(marker)], STATUS_CR, "abc"), marker)

    def test_bez_statusu_albo_bez_podsumowania_bota_nie_ma_oceny(self):
        self.assertIsNone(ag.ocena_coderabbit([], [], [podsumowanie_cr()], [], "abc"))
        self.assertIsNone(ag.ocena_coderabbit([], [], [], STATUS_CR, "abc"))
        self.assertIsNone(ag.ocena_coderabbit([], [], [{"user": {"login": "ktos"}, "body": "ok"}], STATUS_CR, "abc"))
        self.assertIsNone(ag.ocena_coderabbit([], [], [podsumowanie_cr()], [{"context": "CodeRabbit", "state": "pending"}], "abc"))

    def test_komentarze_inline_bota_do_commita_to_uwagi(self):
        inline = [{"user": BOT, "commit_id": "abc", "path": "config/a.yaml", "line": 3, "body": "Błąd"},
                  {"user": BOT, "commit_id": "stary", "path": "x", "line": 1, "body": "stare"}]
        r = ag.ocena_coderabbit([], inline, [podsumowanie_cr()], STATUS_CR, "abc")
        self.assertEqual(r["uwagi"], 1)

    def test_recenzja_dla_innego_commita_nie_liczy_sie_ale_podsumowanie_dla_nowego_tak(self):
        rec = [{"id": 1, "user": BOT, "submitted_at": "2026-10-14T11:00:00Z", "commit_id": "stary", "body": "Actionable comments posted: 3", "state": "COMMENTED"}]
        r = ag.ocena_coderabbit(rec, [], [podsumowanie_cr()], STATUS_CR, "nowy")
        self.assertEqual((r["commit"], r["uwagi"]), ("nowy", 0))

    def test_scalanie_dziala_gdy_coderabbit_skonczyl_samym_podsumowaniem(self):
        s = srodowisko_scalania(recenzje=[], komentarze=[podsumowanie_cr()], statusy=STATUS_CR)
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "scalone")

    def test_review_skipped_przez_pyc_czeka_a_nie_scala(self):
        s = srodowisko_scalania(recenzje=[], komentarze=[podsumowanie_cr("> ## Review skipped")], statusy=STATUS_CR)
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "czekaj")
        self.assertEqual(s.github.scalone, [])


# ── workflow ──────────────────────────────────────────────────────────────────

class TestWorkflowAgenta(unittest.TestCase):

    def setUp(self):
        self.tekst = (Path(__file__).parent.parent / ".github/workflows/agent.yml").read_text(encoding="utf-8")

    def test_wyzwalacze_cron_po_przetwarzaniu_i_recznie(self):
        self.assertIn('cron: "*/15 * * * *"', self.tekst)
        self.assertIn("workflow_run:", self.tekst)
        self.assertIn('"Przetwarzanie rozmów"', self.tekst)
        self.assertIn('"Sprawdzanie maili"', self.tekst)
        self.assertIn("workflow_dispatch", self.tekst)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.tekst, "tylko po udanym przetwarzaniu")

    def test_uruchamia_agenta_i_scalanie_z_potrzebnymi_sekretami(self):
        self.assertIn("python3 agent.py", self.tekst)
        self.assertIn("python3 agent_scal.py", self.tekst)
        for sekret in ("AGENT_GITHUB_TOKEN", "LINEAR_API_KEY", "SLACK_WEBHOOK_URL", "CLAUDE_CODE_OAUTH_TOKEN"):
            self.assertIn(f"secrets.{sekret}", self.tekst)

    def test_cron_i_workflow_run_za_zmienna_a_reczne_zawsze(self):
        self.assertIn("vars.AGENT_WLACZONY == 'true'", self.tekst)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.tekst)

    def test_jeden_przebieg_naraz(self):
        self.assertIn("concurrency:", self.tekst)
        self.assertIn("cancel-in-progress: false", self.tekst)

    def test_workflow_nie_wypisuje_sekretow(self):
        self.assertNotIn("set -x", self.tekst)
        self.assertNotIn("echo $AGENT_GITHUB_TOKEN", self.tekst)


if __name__ == "__main__":
    unittest.main(verbosity=2)
