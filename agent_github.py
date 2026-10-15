#!/usr/bin/env python3
"""agent_github.py – minimalny klient GitHub REST dla agenta wykonawczego (tylko biblioteka standardowa).

Token (AGENT_GITHUB_TOKEN) ma dostęp tylko do repo Rinvo-app. Nigdy nie trafia do logów ani do komunikatów
błędów: wyjątek GitHubError niesie tylko kod HTTP i krótki komunikat serwera.
"""

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from podpis import podpisz_agenta

API = "https://api.github.com"
BOTY_CODERABBIT = {"coderabbitai[bot]", "coderabbitai"}


class GitHubError(RuntimeError):
    def __init__(self, status, komunikat):
        super().__init__(f"GitHub HTTP {status}: {komunikat}")
        self.status = status


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class GitHub:
    def __init__(self, token, repo):
        if not token:
            raise ValueError("brak AGENT_GITHUB_TOKEN")
        self._token = token
        self.repo = repo
        self._ctx = _ssl()

    # ── transport ────────────────────────────────────────────────────────────
    def _zapytaj(self, metoda, sciezka, dane=None, params=None):
        url = f"{API}/repos/{self.repo}{sciezka}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, method=metoda,
            data=json.dumps(dane).encode("utf-8") if dane is not None else None,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                     "User-Agent": "rinvo-agent"})
        try:
            with urllib.request.urlopen(req, timeout=30, context=self._ctx) as r:
                tresc = r.read().decode("utf-8")
                return json.loads(tresc) if tresc else {}
        except urllib.error.HTTPError as exc:
            try:
                komunikat = json.loads(exc.read().decode("utf-8")).get("message", "")
            except Exception:  # noqa: BLE001
                komunikat = ""
            raise GitHubError(exc.code, komunikat[:200]) from None

    def _lista(self, sciezka, params=None):
        """Wszystkie strony wyniku (po 100)."""
        wynik, strona = [], 1
        while True:
            dane = self._zapytaj("GET", sciezka, params={**(params or {}), "per_page": 100, "page": strona})
            if isinstance(dane, dict):          # np. check-runs: {"check_runs": [...]}
                dane = next((v for v in dane.values() if isinstance(v, list)), [])
            wynik += dane
            if len(dane) < 100:
                return wynik
            strona += 1

    # ── pull requesty ────────────────────────────────────────────────────────
    def otwarte_pr(self):
        return self._lista("/pulls", {"state": "open"})

    def pr(self, numer):
        return self._zapytaj("GET", f"/pulls/{numer}")

    def utworz_pr(self, tytul, galaz, opis, baza="main"):
        return self._zapytaj("POST", "/pulls", {"title": tytul, "head": galaz, "base": baza, "body": opis})

    def zaktualizuj_pr(self, numer, opis=None, tytul=None):
        """Zmienia opis (i/lub tytuł) PR."""
        dane = {k: v for k, v in (("body", opis), ("title", tytul)) if v is not None}
        return self._zapytaj("PATCH", f"/pulls/{numer}", dane)

    def odpowiedz_inline(self, numer, komentarz_id, tekst):
        """Odpowiedź w wątku komentarza inline (np. recenzji CodeRabbit)."""
        return self._zapytaj("POST", f"/pulls/{numer}/comments/{komentarz_id}/replies", {"body": podpisz_agenta(tekst)})

    def aktualizuj_galaz(self, numer):
        """Wciela main do gałęzi PR (GitHub: update-branch). Nowy commit uruchamia testy i CodeRabbit od nowa."""
        return self._zapytaj("PUT", f"/pulls/{numer}/update-branch", {})

    def pliki_pr(self, numer):
        return [f["filename"] for f in self._lista(f"/pulls/{numer}/files")]

    def recenzje(self, numer):
        return self._lista(f"/pulls/{numer}/reviews")

    def komentarze_inline(self, numer):
        return self._lista(f"/pulls/{numer}/comments")

    def komentarze(self, numer):
        return self._lista(f"/issues/{numer}/comments")

    def komentarz(self, numer, tekst):
        return self._zapytaj("POST", f"/issues/{numer}/comments", {"body": podpisz_agenta(tekst)})

    def scal_pr(self, numer, tytul, opis):
        return self._zapytaj("PUT", f"/pulls/{numer}/merge",
                             {"merge_method": "squash", "commit_title": tytul, "commit_message": opis})

    def data_commita(self, sha):
        """Data (ISO) ostatniego commita: od niej liczymy czekanie na testy i CodeRabbit."""
        return self._zapytaj("GET", f"/commits/{sha}")["commit"]["committer"]["date"]

    # ── testy i recenzje ─────────────────────────────────────────────────────
    def check_runs(self, sha):
        return self._lista(f"/commits/{sha}/check-runs")

    def statusy(self, sha):
        dane = self._zapytaj("GET", f"/commits/{sha}/status")
        return dane.get("statuses", [])


def stan_testow(check_runs, nazwa="testy"):
    """„success”, „failure”, „pending” albo „none” dla zadania testów (check run o danej nazwie)."""
    runy = [r for r in check_runs if r.get("name") == nazwa]
    if not runy:
        return "none"
    if any(r.get("status") != "completed" for r in runy):
        return "pending"
    ok = all(r.get("conclusion") == "success" for r in runy)
    return "success" if ok else "failure"


def stan_coderabbit_ci(check_runs, statusy):
    """Stan sprawdzenia CodeRabbit z check runów i statusów commita: „success”, „failure”, „pending” albo „none”."""
    stany = []
    for r in check_runs:
        if "coderabbit" in str(r.get("name", "")).lower():
            stany.append("pending" if r.get("status") != "completed"
                         else ("success" if r.get("conclusion") in ("success", "neutral", "skipped") else "failure"))
    for s in statusy:
        if "coderabbit" in str(s.get("context", "")).lower():
            stany.append({"success": "success", "pending": "pending"}.get(s.get("state"), "failure"))
    if not stany:
        return "none"
    for kolejnosc in ("failure", "pending", "success"):
        if kolejnosc in stany:
            return kolejnosc


def ostatnia_recenzja_coderabbit(recenzje, komentarze_inline):
    """Ostatnia recenzja CodeRabbit: {"commit": sha, "uwagi": N, "komentarze": [...]} albo None.

    „uwagi” = liczba zgłoszonych problemów: z nagłówka „Actionable comments posted: N”, a gdy go brak,
    z liczby komentarzy inline tej recenzji."""
    moje = [r for r in recenzje if (r.get("user") or {}).get("login") in BOTY_CODERABBIT and r.get("submitted_at")]
    if not moje:
        return None
    r = sorted(moje, key=lambda x: x["submitted_at"])[-1]
    inline = [c for c in komentarze_inline if c.get("pull_request_review_id") == r.get("id")]
    m = re.search(r"Actionable comments posted:\s*(\d+)", r.get("body") or "")
    uwagi = int(m.group(1)) if m else len(inline)
    if r.get("state") == "APPROVED":
        uwagi = 0
    return {"commit": r.get("commit_id"), "uwagi": uwagi,
            "komentarze": [{"id": c.get("id"), "sciezka": c.get("path"), "linia": c.get("line"), "tresc": c.get("body", "")} for c in inline]}


POMINIECIE_CODERABBIT = ("review skipped", "review failed", "rate limit", "review paused", "reviews paused")


def ocena_coderabbit(recenzje, komentarze_inline, komentarze_issue, statusy, sha):
    """Ocena CodeRabbit dla commita sha: {"commit", "uwagi", "komentarze"} albo None (jeszcze nie zrecenzował).

    1) recenzja bota dla tego commita (z komentarzami inline) → jej liczba uwag;
    2) bez obiektu recenzji CodeRabbit kończy też samym podsumowaniem w komentarzu PR i statusem „CodeRabbit” = success
       (gdy nie ma czego zgłaszać). Uznajemy to za recenzję bez uwag tylko, gdy status jest zielony dla TEGO commita, bot
       zostawił podsumowanie, a podsumowanie nie mówi „Review skipped/failed/paused” (np. przez filtr ścieżek) oraz nie ma
       komentarzy inline bota do tego commita."""
    rec = ostatnia_recenzja_coderabbit(recenzje, komentarze_inline)
    if rec is not None and rec["commit"] == sha:
        return rec
    status_ok = any("coderabbit" in str(x.get("context", "")).lower() and x.get("state") == "success" for x in statusy)
    bot = [k for k in komentarze_issue if (k.get("user") or {}).get("login") in BOTY_CODERABBIT]
    if not (status_ok and bot):
        return rec
    tekst = " ".join((k.get("body") or "") for k in bot).lower()
    if any(m in tekst for m in POMINIECIE_CODERABBIT):
        return rec                                   # pominięta albo nieudana recenzja to nie „brak uwag”
    inline = [c for c in komentarze_inline if (c.get("user") or {}).get("login") in BOTY_CODERABBIT and c.get("commit_id") == sha]
    return {"commit": sha, "uwagi": len(inline), "bez_obiektu_recenzji": True,
            "komentarze": [{"sciezka": c.get("path"), "linia": c.get("line"), "tresc": c.get("body", "")} for c in inline]}
