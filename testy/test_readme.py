#!/usr/bin/env python3
"""test_readme.py – README ma być krótkie i czytelne dla foundera (dwie minuty), a szczegóły leżą w docs/. Bez sieci i bez modelu.
Uruchomienie: python3 testy/test_readme.py
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

README = (ROOT / "README.md").read_text(encoding="utf-8")
KOLEJNOSC = ["Jak to płynie", "Kto co robi", "Wyniki próby od zera", "Struktura repo", "Jak uruchomić", "Ograniczenia i co dalej"]


class TestReadme(unittest.TestCase):

    def test_krotkie_na_okolo_dwa_ekrany(self):
        self.assertLessEqual(len(README.splitlines()), 80)

    def test_tytul_i_dwa_zdania_opisu(self):
        linie = README.splitlines()
        self.assertTrue(linie[0].startswith("# "))
        opis = [l for l in linie[1:6] if l.strip() and not l.startswith("**Zobacz")]
        self.assertEqual(len(re.findall(r"[.!?](?:\s|$)", " ".join(opis))), 2, "dwa zdania")
        self.assertIn("Linearze", opis[0])
        self.assertIn("człowiek dostaje rano tylko to", opis[0])

    def test_linki_na_gorze(self):
        gora = "\n".join(README.splitlines()[:8])
        for url in ("https://rembolekk.github.io/Rinvo/index.html", "https://rembolekk.github.io/Rinvo/glos-klientow.html", "https://github.com/Rembolekk/rinvo-app"):
            self.assertIn(url, gora)

    def test_sekcje_w_zadanej_kolejnosci(self):
        naglowki = re.findall(r"^## (.+)$", README, re.M)
        self.assertEqual(naglowki, KOLEJNOSC)

    def test_schemat_mermaid_ma_najwyzej_osiem_krokow(self):
        blok = re.search(r"```mermaid\n(.*?)```", README, re.S).group(1)
        wezly = set(re.findall(r"^\s*([A-Z])(?:\[|\s*-->)", blok, re.M)) | set(re.findall(r"-->\s*([A-Z])\[", blok))
        self.assertTrue(1 <= len(wezly) <= 8, wezly)

    def test_kto_co_robi_trzy_linijki_i_wyjatki(self):
        sekcja = README.split("## Kto co robi")[1].split("## ")[0]
        punkty = [l for l in sekcja.splitlines() if l.startswith("- ")]
        self.assertEqual([re.match(r"- \*\*([^:*]+)", p).group(1) for p in punkty], ["AI", "Kod", "Człowiek", "Wyjątki dla człowieka"])

    def test_wyniki_proby_3_do_4_punktow_z_liczbami(self):
        sekcja = README.split("## Wyniki próby od zera")[1].split("## ")[0]
        punkty = [l for l in sekcja.splitlines() if l.startswith("- ")]
        self.assertIn(len(punkty), (3, 4))
        self.assertIn("12 z 12", sekcja)
        self.assertIn("11 z 11", sekcja)
        self.assertIn("2 h 15 min", sekcja)

    def test_struktura_repo_maks_10_wierszy(self):
        sekcja = README.split("## Struktura repo")[1].split("## ")[0]
        wiersze = [l for l in sekcja.splitlines() if l.startswith("|") and not l.startswith("|---") and "Plik lub folder" not in l]
        self.assertLessEqual(len(wiersze), 10)

    def test_jak_uruchomic_trzy_kroki(self):
        sekcja = README.split("## Jak uruchomić")[1].split("## ")[0]
        kroki = re.findall(r"^\d\. ", sekcja, re.M)
        self.assertEqual(len(kroki), 3)
        for fraza in ("CLAUDE_CODE_OAUTH_TOKEN", "LINEAR_API_KEY", "AGENT_WLACZONY", "MAILE_WLACZONE", "ops/transkrypcje/"):
            self.assertIn(fraza, sekcja)

    def test_ograniczenia_4_do_5_punktow_uczciwie(self):
        sekcja = README.split("## Ograniczenia i co dalej")[1]
        punkty = [l for l in sekcja.splitlines() if l.startswith("- ")]
        self.assertIn(len(punkty), (4, 5))
        for fraza in ("Zastępczy wykonawca", "Token zamiast konta bota", "Cron zamiast zdarzeń", "Dane fikcyjne", "Repo publiczne tylko dla demo"):
            self.assertIn(fraza, sekcja)

    def test_bez_emoji_i_zargonu_z_dluzszych_opisow(self):
        self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-➿]", README))

    def test_szczegoly_przeniesione_do_docs_i_podlinkowane(self):
        for plik in ("docs/SZCZEGOLY.md", "docs/PRZYPADKI-BRZEGOWE.md"):
            self.assertTrue((ROOT / plik).exists(), plik)
            self.assertIn(plik, README)
        sz = (ROOT / "docs/SZCZEGOLY.md").read_text(encoding="utf-8")
        for fraza in ("Automat przetwarzania", "Agent wykonawczy", "Testy automatyczne", "Nowy klient", "Strony: układ i liczby", "Próba generalna"):
            self.assertIn(fraza, sz, fraza)
        self.assertNotIn("| 17. Odpowiedź klienta", sz, "tabela przypadków brzegowych jest w osobnym pliku")
        self.assertIn("| 17. Odpowiedź klienta", (ROOT / "docs/PRZYPADKI-BRZEGOWE.md").read_text(encoding="utf-8"))

    def test_linki_wzgledne_w_docs_prowadza_do_istniejacych_plikow(self):
        for plik in ("docs/SZCZEGOLY.md", "docs/PRZYPADKI-BRZEGOWE.md"):
            for cel in re.findall(r"\]\((?!http|#)([^)#]+)", (ROOT / plik).read_text(encoding="utf-8")):
                self.assertTrue((ROOT / "docs" / cel).exists(), f"{plik}: {cel}")
        for cel in re.findall(r"\]\((?!http|#)([^)#]+)", README):
            self.assertTrue((ROOT / cel).exists(), f"README: {cel}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
