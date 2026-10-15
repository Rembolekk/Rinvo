#!/usr/bin/env python3
"""test_kryteria_pr.py – kryteria w opisie PR agenta (odhaczone po sprawdzeniu w plikach, reszta w „Sprawdzenie po wdrożeniu”), prawdziwy komentarz po
uwagach CodeRabbit, poprawa opisu istniejącego PR (RIN-164 / PR #7) i zgłoszenie po scaleniu. Bez sieci i bez modelu. Uruchomienie: python3 testy/test_kryteria_pr.py
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import agent
import agent_scal
import kryteria_pr as kp
import zasady
import test_agent as ta

Z = zasady.wczytaj_zasady()
A = Z["agent_wykonawczy"]

KRYT_PLIK = "W bazie wiedzy godziny jazd próbnych w sobotę to 9:00–14:00"
KRYT_NIEDZ = "W bazie wiedzy i konfiguracji nie ma jazd próbnych w niedzielę"
KRYT_ROZMOWA = "W rozmowie testowej agent na prośbę o niedzielę nie proponuje terminu i podaje dozwolony dzień"
KRYT_WIAD = "Kasia dostaje wiadomość, że adres jest poprawiony"
PLIKI = {"wiedza/motor-lux.md": "## Jazdy próbne\n\n- Pon–pt: 9:00–18:00\n- Sobota: 9:00–14:00\n", "config/motor-lux.yaml": "jazdy_probne:\n  dni:\n    pon-pt: {}\n"}


class Model:
    """Atrapa modelu: odpowiada na ocenę kryteriów JSON-em zadanym z góry."""

    def __init__(self, oceny=None, odpowiedz_zakazy='{"konflikt": false, "zakaz": null, "powod": ""}', edycja="Zmieniłem godziny."):
        self.oceny, self.odpowiedz_zakazy, self.edycja = oceny if oceny is not None else [], odpowiedz_zakazy, edycja
        self.pytania, self.prompty_edycji = [], []

    def zapytaj(self, prompt):
        self.pytania.append(prompt)
        if "KRYTERIA AKCEPTACJI są spełnione" in prompt:
            return json.dumps({"oceny": self.oceny}, ensure_ascii=False)
        return self.odpowiedz_zakazy

    def edytuj(self, katalog, prompt):
        self.prompty_edycji.append(prompt)
        return True, self.edycja


class K1Klasyfikacja(unittest.TestCase):

    def _s(self, oceny):
        s = ta.Srodowisko([ta.zgloszenie(41)])
        s.claude = Model(oceny)
        return s

    def test_k1_heurystyka_poza_plikami(self):
        for k in (KRYT_ROZMOWA, KRYT_WIAD, "Po wdrożeniu Kasia potwierdza", "Klientka dostaje maila z potwierdzeniem"):
            self.assertTrue(kp.poza_plikami(k, A), k)
        for k in (KRYT_PLIK, KRYT_NIEDZ, "config: Toruń sobota do 15:00"):
            self.assertFalse(kp.poza_plikami(k, A), k)

    def test_k1_odhaczone_tylko_z_dowodem_w_pliku_reszta_osobno(self):
        s = self._s([{"nr": 1, "plik": "wiedza/motor-lux.md", "fragment": "- Sobota: 9:00–14:00"}, {"nr": 2, "plik": "wiedza/motor-lux.md", "fragment": "Niedziela: 10:00–16:00"}])
        kl = kp.klasyfikuj(s, [KRYT_PLIK, KRYT_NIEDZ, KRYT_ROZMOWA], PLIKI, {"title": "x"})
        self.assertEqual([k["rodzaj"] for k in kl], ["plik", "plik", "po_wdrozeniu"])
        self.assertEqual(kl[0]["dowod"], ("wiedza/motor-lux.md", "- Sobota: 9:00–14:00"))
        self.assertIsNone(kl[1]["dowod"], "wymyślony fragment: nie odhaczamy")
        opis = kp.sekcje_opisu(kl)
        self.assertIn("- [x] " + KRYT_PLIK + " (sprawdzone w pliku `wiedza/motor-lux.md`: `- Sobota: 9:00–14:00`)", opis)
        self.assertIn("- [ ] " + KRYT_NIEDZ + " (agent nie potwierdził tego w plikach)", opis)
        sekcja = opis.split("## Sprawdzenie po wdrożeniu")[1]
        self.assertIn("- " + KRYT_ROZMOWA, sekcja)
        self.assertNotIn("[ ]", sekcja, "bez pól do odhaczenia")
        self.assertNotIn("[x]", sekcja)
        self.assertIn("Po scaleniu agent założy z nich krótkie zgłoszenie", sekcja)
        self.assertNotIn(KRYT_ROZMOWA, opis.split("## Sprawdzenie po wdrożeniu")[0], "kryterium spoza plików nie wisi na liście do odhaczenia")

    def test_k1_model_zawodzi_nic_nie_jest_odhaczone(self):
        s = ta.Srodowisko([ta.zgloszenie(41)])
        s.claude.zapytaj = lambda prompt: "to nie jest json"
        kl = kp.klasyfikuj(s, [KRYT_PLIK, KRYT_ROZMOWA], PLIKI, {"title": "x"})
        self.assertIsNone(kl[0]["dowod"])
        self.assertEqual(kl[1]["rodzaj"], "po_wdrozeniu", "heurystyka działa bez modelu")

    def test_k1_wszystkie_kryteria_poza_plikami(self):
        opis = kp.sekcje_opisu([{"tekst": KRYT_ROZMOWA, "rodzaj": "po_wdrozeniu", "dowod": None}])
        self.assertIn("Wszystkie kryteria wymagają sprawdzenia po wdrożeniu", opis)
        self.assertEqual(kp.punkty_po_wdrozeniu(opis), [KRYT_ROZMOWA])

    def test_k1_stary_format_i_podmiana_sekcji(self):
        stary = f"Fixes RIN-164\n\n## Cel\n\nX\n\n## Kryteria akceptacji\n\n- [ ] {KRYT_PLIK}\n- [ ] {KRYT_ROZMOWA}\n\n## Cytat klienta\n\n> c\n"
        self.assertTrue(kp.opis_w_starym_formacie(stary))
        nowy = kp.podmien_kryteria(stary, [{"tekst": KRYT_PLIK, "rodzaj": "plik", "dowod": ("a.md", "b")}, {"tekst": KRYT_ROZMOWA, "rodzaj": "po_wdrozeniu", "dowod": None}])
        self.assertFalse(kp.opis_w_starym_formacie(nowy))
        self.assertIn("## Cytat klienta", nowy, "reszta opisu zostaje")
        self.assertEqual(nowy.count("## Kryteria akceptacji"), 1)

    def test_k1_przeniesienie_kryterium_do_sekcji_po_wdrozeniu(self):
        opis = kp.sekcje_opisu([{"tekst": KRYT_PLIK, "rodzaj": "plik", "dowod": ("a.md", "b")}, {"tekst": KRYT_NIEDZ, "rodzaj": "plik", "dowod": None}])
        nowy = kp.przenies_do_po_wdrozeniu(opis, KRYT_NIEDZ)
        self.assertEqual(kp.punkty_po_wdrozeniu(nowy), [KRYT_NIEDZ])
        self.assertIn("- [x] " + KRYT_PLIK, nowy, "odhaczone zostaje odhaczone")
        self.assertNotIn("- [ ] " + KRYT_NIEDZ, nowy)
        self.assertIsNone(kp.przenies_do_po_wdrozeniu(opis, "kryterium, którego nie ma"))


class K2OpisNowegoPR(unittest.TestCase):

    def test_k2_agent_tworzy_pr_z_odhaczonymi_kryteriami_i_sekcja_po_wdrozeniu(self):
        zg = ta.zgloszenie(41)
        zg["description"] = zg["description"].replace("- [ ] config: Toruń sobota do 15:00\n- [ ] wiedza: Toruń sobota 9:00–15:00",
                                                       "- [ ] config: Toruń sobota do 15:00\n- [ ] W rozmowie testowej agent nie proponuje niedzieli")
        git = ta.AtrapaGit(pliki={"config/auto-tama.yaml": 'sobota: {od: "09:00", do: "15:00"}\n', "wiedza/auto-tama.md": "- Sobota: 9:00–15:00\n"})
        s = ta.Srodowisko([zg], git=git, claude=Model([{"nr": 1, "plik": "config/auto-tama.yaml", "fragment": 'sobota: {od: "09:00", do: "15:00"}'}]))
        w = agent.uruchom(s)[0]
        self.assertEqual(w["status"], "pr")
        opis = s.github.utworzone[0]["opis"]
        self.assertIn("- [x] config: Toruń sobota do 15:00 (sprawdzone w pliku `config/auto-tama.yaml`", opis)
        self.assertIn("## Sprawdzenie po wdrożeniu", opis)
        self.assertEqual(kp.punkty_po_wdrozeniu(opis), ["W rozmowie testowej agent nie proponuje niedzieli"])
        self.assertNotRegex(opis.split("## Sprawdzenie po wdrożeniu")[1].split("## ")[0], r"\[[ x]\]")


def inline(id_=55, tresc="Kryterium „w rozmowie testowej agent nie proponuje niedzieli” jest nieodhaczone"):
    return [{"id": id_, "pull_request_review_id": 1, "path": "config/motor-lux.yaml", "line": 3, "body": tresc}]


def opis_pr7():
    return (f"Fixes RIN-41\n\n## Cel\n\nX\n\n## Kryteria akceptacji\n\n- [ ] {KRYT_PLIK}\n- [ ] {KRYT_NIEDZ}\n- [ ] {KRYT_ROZMOWA}\n\n## Cytat klienta\n\n> c\n")


def srodowisko(edycja, oceny=None, body=None, zmienione=("config/auto-tama.yaml",)):
    git = ta.AtrapaGit(zmienione=list(zmienione), pliki={"wiedza/auto-tama.md": "- Sobota: 9:00–14:00\n", "config/auto-tama.yaml": "jazdy_probne: {}\n"})
    s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], git=git, claude=Model(oceny or [], edycja=edycja),
                      github=ta.AtrapaGitHub(prs=[ta.pr(body=body or opis_pr7())], recenzje=[ta.recenzja(uwagi=1)], inline=inline()))
    return s


class K3KomentarzPoUwagach(unittest.TestCase):

    def _edycja(self, decyzje, podsumowanie="Nic nie zmieniłem."):
        return "Przejrzałem uwagi.\n" + json.dumps({"podsumowanie": podsumowanie, "uwagi": decyzje}, ensure_ascii=False)

    def test_k3_uwaga_o_sprawdzeniu_po_wdrozeniu_bez_zmiany_plikow(self):
        s = srodowisko(self._edycja([{"nr": 1, "decyzja": "po_wdrozeniu", "powod": "rozmowa testowa nie jest sprawdzalna w plikach", "kryterium": KRYT_ROZMOWA}]), zmienione=())
        # PR #7 ma stary opis: najpierw poprawa opisu (osobny test), tu ścieżka „popraw” po poprawieniu opisu
        s.github.komentarze_lista.append({"body": f"x {agent_scal.ZNACZNIK_OPISU}"})
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "poprawione")
        self.assertFalse(w["zmiany"])
        self.assertEqual(w["przeniesione_po_wdrozeniu"], 1)
        komentarz = next(k[1] for k in s.github.dodane_komentarze if agent_scal.ZNACZNIK_POPRAWKI in k[1])
        self.assertIn("**nie zmienił żadnych plików**", komentarz)
        self.assertIn("dotyczy sprawdzenia po wdrożeniu, nie plików", komentarz)
        self.assertIn("rozmowa testowa nie jest sprawdzalna w plikach", komentarz)
        self.assertNotIn("uwzględnił uwagi CodeRabbit (jednorazowo)", komentarz, "bez dawnego zdania, które nic nie mówiło")
        self.assertIn("@coderabbitai review", komentarz, "bez nowego commita prosimy o ponowną recenzję")
        self.assertEqual(kp.punkty_po_wdrozeniu(s.github.opisy[-1][1]), [KRYT_ROZMOWA])
        self.assertEqual(s.github.odpowiedzi[0][1], 55, "odpowiedź w wątku uwagi")
        self.assertEqual(s.github.scalone, [])

    def test_k3_zmiana_plikow_jest_opisana_z_nazwami_plikow(self):
        s = srodowisko(self._edycja([{"nr": 1, "decyzja": "uwzgledniona", "powod": "dodałem niedzielę jako zamkniętą"}], "Dodałem jawny zapis, że w niedzielę nie ma jazd."))
        s.github.komentarze_lista.append({"body": f"x {agent_scal.ZNACZNIK_OPISU}"})
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertTrue(w["zmiany"])
        komentarz = next(k[1] for k in s.github.dodane_komentarze if agent_scal.ZNACZNIK_POPRAWKI in k[1])
        self.assertIn("zmienił: `config/auto-tama.yaml`", komentarz)
        self.assertIn("uwzględniona zmianą plików", komentarz)
        self.assertNotIn("@coderabbitai review", komentarz, "nowy commit uruchomi recenzję sam")
        self.assertEqual(len(s.git.push), 1)

    def test_k3_deklaracja_uwzgledniona_bez_zmiany_plikow_nie_jest_przedstawiona_jako_zmiana(self):
        s = srodowisko(self._edycja([{"nr": 1, "decyzja": "uwzgledniona", "powod": "poprawione"}], "Poprawione."), zmienione=())
        s.github.komentarze_lista.append({"body": f"x {agent_scal.ZNACZNIK_OPISU}"})
        agent_scal.uruchom_scalanie(s)
        komentarz = next(k[1] for k in s.github.dodane_komentarze if agent_scal.ZNACZNIK_POPRAWKI in k[1])
        self.assertIn("nie zmienił żadnych plików", komentarz)
        self.assertIn("model uznał ją za uwzględnioną, ale pliki się nie zmieniły", komentarz)

    def test_k3_uwaga_nietrafna_i_brak_decyzji(self):
        s = srodowisko(self._edycja([{"nr": 1, "decyzja": "nietrafna", "powod": "godziny są zgodne z rozmową"}]), zmienione=())
        s.github.komentarze_lista.append({"body": f"x {agent_scal.ZNACZNIK_OPISU}"})
        agent_scal.uruchom_scalanie(s)
        self.assertIn("nie uwzględniona, bo model uznał ją za nietrafną: godziny są zgodne z rozmową",
                      next(k[1] for k in s.github.dodane_komentarze if agent_scal.ZNACZNIK_POPRAWKI in k[1]))
        s2 = srodowisko("Zrobione, bez JSON-a.", zmienione=())
        s2.github.komentarze_lista.append({"body": f"x {agent_scal.ZNACZNIK_OPISU}"})
        agent_scal.uruchom_scalanie(s2)
        self.assertIn("model nie podał decyzji, pliki bez zmian", next(k[1] for k in s2.github.dodane_komentarze if agent_scal.ZNACZNIK_POPRAWKI in k[1]))


class K4PopravaOpisuIstniejacegoPR(unittest.TestCase):
    """PR #7 (RIN-164): CodeRabbit zgłosił nieodhaczone kryterium rozmowy testowej, agent napisał „uwzględnił uwagi” i nic nie zmienił."""

    def _s(self):
        oceny = [{"nr": 1, "plik": "wiedza/auto-tama.md", "fragment": "- Sobota: 9:00–14:00"}]
        return srodowisko("n/a", oceny=oceny)

    def test_k4_opis_poprawiony_odpowiedz_w_watku_i_prosba_o_recenzje(self):
        s = self._s()
        w = agent_scal.uruchom_scalanie(s)[0]
        self.assertEqual(w["akcja"], "opis_poprawiony")
        nowy = s.github.opisy[-1][1]
        self.assertIn("- [x] " + KRYT_PLIK, nowy)
        self.assertEqual(kp.punkty_po_wdrozeniu(nowy), [KRYT_ROZMOWA])
        self.assertIn("- [ ] " + KRYT_NIEDZ, nowy, "bez dowodu w plikach nie odhaczamy")
        self.assertIn("## Cytat klienta", nowy)
        odpowiedz = s.github.odpowiedzi[0]
        self.assertEqual(odpowiedz[1], 55, "odpowiedź w wątku CodeRabbit")
        self.assertIn("Sprawdzenie po wdrożeniu", odpowiedz[2])
        self.assertIn("@coderabbitai review", odpowiedz[2])
        glowny = next(k[1] for k in s.github.dodane_komentarze if agent_scal.ZNACZNIK_OPISU in k[1])
        self.assertIn("@coderabbitai review", glowny)
        self.assertIn("Pliki w PR się nie zmieniły", glowny)
        self.assertEqual((s.github.scalone, s.git.push), ([], []), "nie scala i nie dotyka plików")

    def test_k4_tylko_raz_i_tylko_gdy_coderabbit_ma_uwagi(self):
        s = self._s()
        agent_scal.uruchom_scalanie(s)
        liczba = len(s.github.opisy)
        s.github.prs[0]["body"] = s.github.opisy[-1][1]
        agent_scal.uruchom_scalanie(s)
        self.assertEqual(len(s.github.opisy), liczba, "opis poprawiany jeden raz")
        s2 = srodowisko("x")
        s2.github.recenzje_lista = [ta.recenzja(uwagi=0)]
        agent_scal.uruchom_scalanie(s2)
        self.assertEqual(getattr(s2.github, "opisy", []), [], "bez uwag CodeRabbit opis zostaje")

    def test_k4_nowy_opis_nie_wymaga_poprawy(self):
        nowy = kp.sekcje_opisu([{"tekst": KRYT_PLIK, "rodzaj": "plik", "dowod": ("a", "b")}, {"tekst": KRYT_ROZMOWA, "rodzaj": "po_wdrozeniu", "dowod": None}])
        self.assertFalse(agent_scal.opis_pr_wymaga_poprawy({"body": nowy}, [], {"uwagi": 2}))
        self.assertTrue(agent_scal.opis_pr_wymaga_poprawy({"body": opis_pr7()}, [], {"uwagi": 2}))
        self.assertFalse(agent_scal.opis_pr_wymaga_poprawy({"body": opis_pr7()}, [{"body": agent_scal.ZNACZNIK_OPISU}], {"uwagi": 2}))


class K5ZgloszeniePoScaleniu(unittest.TestCase):

    def _scal(self, body):
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=ta.AtrapaGitHub(prs=[ta.pr(body=body)], recenzje=[ta.recenzja()]))
        return s, agent_scal.uruchom_scalanie(s)[0]

    def test_k5_po_scaleniu_krotkie_zgloszenie_z_punktow_po_wdrozeniu(self):
        body = "Fixes RIN-41\n\n" + kp.sekcje_opisu([{"tekst": KRYT_PLIK, "rodzaj": "plik", "dowod": ("a", "b")}, {"tekst": KRYT_ROZMOWA, "rodzaj": "po_wdrozeniu", "dowod": None},
                                                    {"tekst": KRYT_WIAD, "rodzaj": "po_wdrozeniu", "dowod": None}])
        s, w = self._scal(body)
        self.assertEqual(w["akcja"], "scalone")
        z = s.linear.utworzone[0]
        self.assertTrue(z["title"].startswith("[auto-tama] Po wdrożeniu: "))
        self.assertEqual(z["labels"], ["Do weryfikacji"])
        self.assertIn(KRYT_ROZMOWA, z["description"])
        self.assertIn(KRYT_WIAD, z["description"])
        self.assertIn("RIN-41", z["description"])
        self.assertTrue(any("Sprawdzenie po wdrożeniu" in k[2] for k in s.linear.zdarzenia if k[0] == "komentarz"))

    def test_k5_bez_punktow_po_wdrozeniu_nie_ma_zgloszenia(self):
        s, w = self._scal("Fixes RIN-41\n\n## Kryteria akceptacji\n\n- [x] A (sprawdzone w pliku `a`: `b`)")
        self.assertEqual(w["akcja"], "scalone")
        self.assertEqual(s.linear.utworzone, [])

    def test_k5_blad_zalozenia_zgloszenia_nie_cofa_scalenia(self):
        body = "Fixes RIN-41\n\n" + kp.sekcje_opisu([{"tekst": KRYT_ROZMOWA, "rodzaj": "po_wdrozeniu", "dowod": None}])
        s = ta.Srodowisko([ta.zgloszenie(41, stan="In Progress")], github=ta.AtrapaGitHub(prs=[ta.pr(body=body)], recenzje=[ta.recenzja()]))
        s.linear.utworz = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("Linear niedostępny"))
        self.assertEqual(agent_scal.uruchom_scalanie(s)[0]["akcja"], "scalone")
        self.assertEqual(len(s.github.scalone), 1)


class K6Dokumentacja(unittest.TestCase):

    def test_readme_opisuje_zasady(self):
        r = (ROOT / "README.md").read_text(encoding="utf-8")
        for fraza in ("Sprawdzenie po wdrożeniu", "kryteria_pr.py", "@coderabbitai review"):
            self.assertIn(fraza, r, fraza)


if __name__ == "__main__":
    unittest.main(verbosity=1)
