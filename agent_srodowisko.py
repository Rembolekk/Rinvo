#!/usr/bin/env python3
"""agent_srodowisko.py – produkcyjne implementacje „środowiska” agenta: Linear, git, claude, Slack.

Logika agenta (agent.py, agent_scal.py) zależy tylko od metod tych klas, więc testy offline podstawiają atrapy.
Zasady bezpieczeństwa:
  * token GitHub trafia do gita wyłącznie przez zmienne środowiska (nie przez argumenty i nie do logów),
  * `claude` dostaje tylko narzędzia Read/Write/Edit, tryb acceptEdits (bez dangerously-skip-permissions: dostęp
    poza katalogiem roboczym jest odrzucany) i środowisko bez kluczy Linear, Slack, Gmail i GitHub.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import linear_sync
import zasady
from maile import slack_bezpiecznie
from podpis import podpisz_agenta

TAJNE_DLA_MODELU = ("LINEAR_API_KEY", "SLACK_WEBHOOK_URL", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "AGENT_GITHUB_TOKEN")


def env_modelu():
    """Środowisko procesu `claude`: bez kluczy do Lineara, Slacka, Gmaila i GitHuba (zostaje tylko jego logowanie)."""
    env = os.environ.copy()
    for nazwa in TAJNE_DLA_MODELU:
        env.pop(nazwa, None)
    return env


def maskuj(tekst, sekrety):
    for s in sekrety:
        if s and len(s) >= 8:
            tekst = tekst.replace(s, "***")
    return tekst


# ── Linear ────────────────────────────────────────────────────────────────────

class LinearAgent:
    def __init__(self, api_key, Z):
        self.api_key, self.Z = api_key, Z
        self.team = linear_sync.get_team(api_key)
        self.etykiety = linear_sync.ensure_labels(api_key, self.team["id"])
        stany = linear_sync.get_workflow_states(api_key, self.team["id"])
        self._stany = {
            "Todo": linear_sync.find_state(stany, "Todo", "unstarted"),
            "In Progress": linear_sync.find_state(stany, "In Progress", "started"),
            "Done": linear_sync.find_state(stany, "Done", "completed"),
        }

    _POLA = "id identifier title description priority createdAt url state { name } labels { nodes { name } }"

    def _normalizuj(self, n):
        return {**n, "labels": [l["name"] for l in (n.get("labels") or {}).get("nodes", [])],
                "state": (n.get("state") or {}).get("name", "")}

    def kandydaci(self):
        A = self.Z["agent_wykonawczy"]
        q = ('query { issues(first: 50, filter: { and: [ { team: { key: { eq: "%s" } } }, '
             '{ state: { name: { eq: "Todo" } } }, { labels: { name: { eq: "%s" } } }, '
             '{ labels: { name: { eq: "%s" } } } ] }) { nodes { %s } } }'
             % (linear_sync.TEAM_KEY, self.Z["etykiety"]["agent"], A["etykieta_repo"], self._POLA))
        return [self._normalizuj(n) for n in linear_sync.gql(self.api_key, q)["issues"]["nodes"]]

    def zgloszenie_po_numerze(self, numer):
        q = ('query { issues(filter: { team: { key: { eq: "%s" } }, number: { eq: %d } }) { nodes { %s } } }'
             % (linear_sync.TEAM_KEY, int(numer), self._POLA))
        nodes = linear_sync.gql(self.api_key, q)["issues"]["nodes"]
        return self._normalizuj(nodes[0]) if nodes else None

    def komentarz(self, zg, tekst):
        linear_sync.gql(self.api_key, linear_sync.M_ADD_COMMENT, {"issueId": zg["id"], "body": tekst})

    def ustaw_stan(self, zg, nazwa):
        linear_sync.gql(self.api_key, linear_sync.M_UPDATE_ISSUE,
                        {"id": zg["id"], "input": {"stateId": self._stany[nazwa]}})
        zg["state"] = nazwa

    def dodaj_etykiete(self, zg, nazwa):
        linear_sync.dodaj_etykiete(self.api_key, zg["id"], self.etykiety, nazwa)
        if nazwa not in zg.get("labels", []):
            zg.setdefault("labels", []).append(nazwa)

    def usun_etykiete(self, zg, nazwa):
        lab = linear_sync.get_issue_labels_from_linear(self.api_key, zg["id"])
        if any(l["name"] == nazwa for l in lab):
            linear_sync.gql(self.api_key, linear_sync.M_UPDATE_ISSUE,
                            {"id": zg["id"], "input": {"labelIds": [l["id"] for l in lab if l["name"] != nazwa]}})
        if nazwa in zg.get("labels", []):
            zg["labels"].remove(nazwa)

    _POLA_PELNE = _POLA + " completedAt"

    def z_etykieta(self, nazwa):
        """Zgłoszenia zespołu z daną etykietą (dowolny stan)."""
        q = ('query { issues(first: 50, filter: { and: [ { team: { key: { eq: "%s" } } }, '
             '{ labels: { name: { eq: "%s" } } } ] }) { nodes { %s } } }' % (linear_sync.TEAM_KEY, nazwa, self._POLA_PELNE))
        return [self._normalizuj(n) for n in linear_sync.gql(self.api_key, q)["issues"]["nodes"]]

    def ukonczone(self, od_iso):
        """Zgłoszenia zespołu zamknięte jako Done od podanej daty (ISO)."""
        q = ('query { issues(first: 100, filter: { and: [ { team: { key: { eq: "%s" } } }, '
             '{ state: { type: { eq: "completed" } } }, { completedAt: { gt: "%s" } } ] }) { nodes { %s } } }'
             % (linear_sync.TEAM_KEY, od_iso, self._POLA_PELNE))
        return [self._normalizuj(n) for n in linear_sync.gql(self.api_key, q)["issues"]["nodes"]]

    def otwarte(self, stany):
        """Otwarte zgłoszenia zespołu w podanych stanach (nazwy)."""
        nazwy = ", ".join('"%s"' % n for n in stany)
        q = ('query { issues(first: 100, filter: { and: [ { team: { key: { eq: "%s" } } }, '
             '{ state: { name: { in: [%s] } } } ] }) { nodes { %s } } }' % (linear_sync.TEAM_KEY, nazwy, self._POLA_PELNE))
        return [self._normalizuj(n) for n in linear_sync.gql(self.api_key, q)["issues"]["nodes"]]

    def edytuj_komentarz(self, komentarz_id, tresc):
        linear_sync.gql(self.api_key, "mutation($id: String!, $input: CommentUpdateInput!) { commentUpdate(id: $id, input: $input) { success } }",
                        {"id": komentarz_id, "input": {"body": podpisz_agenta(tresc)}})

    def komentarze(self, zg):
        q = 'query { issue(id: "%s") { comments(first: 100) { nodes { id body createdAt } } } }' % zg["id"]
        return linear_sync.gql(self.api_key, q)["issue"]["comments"]["nodes"]


# ── git ───────────────────────────────────────────────────────────────────────

class GitRepo:
    """Klon repo Rinvo-app w katalogu tymczasowym. Token tylko w środowisku procesów git."""

    def __init__(self, token, repo, Z):
        self._token, self.repo = token, repo
        self.autor = Z["agent_wykonawczy"]["autor_git"]
        self.komenda_testow = Z["agent_wykonawczy"]["komenda_testow"]
        self._katalogi = []

    def _env(self):
        env = os.environ.copy()
        b64 = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {b64}"})
        return env

    def _git(self, katalog, *args, sprawdz=True):
        r = subprocess.run(["git", "-c", f"user.name={self.autor['imie']}", "-c", f"user.email={self.autor['email']}", *args],
                           cwd=katalog, env=self._env(), capture_output=True, text=True, timeout=180)
        if sprawdz and r.returncode != 0:
            raise RuntimeError(f"git {args[0]} nie powiódł się: {maskuj(r.stderr, [self._token])[:300]}")
        return r

    def przygotuj(self, galaz, istniejaca=False):
        """Klonuje repo i przechodzi na nową gałąź (albo na istniejącą zdalną, gdy istniejaca=True)."""
        katalog = Path(tempfile.mkdtemp(prefix="rinvo-app-"))
        self._katalogi.append(katalog)
        self._git(katalog.parent, "clone", "--quiet", f"https://github.com/{self.repo}.git", str(katalog))
        if istniejaca:
            self._git(katalog, "checkout", "--quiet", galaz)
        else:
            self._git(katalog, "checkout", "--quiet", "-b", galaz)
        return katalog

    def galaz_zdalna_istnieje(self, galaz):
        katalog = Path(tempfile.gettempdir())
        r = self._git(katalog, "ls-remote", "--heads", f"https://github.com/{self.repo}.git", galaz, sprawdz=False)
        return bool(r.stdout.strip())

    def zmienione(self, katalog):
        """Ścieżki zmienione albo nowe (względem HEAD), także nieśledzone."""
        r = self._git(katalog, "status", "--porcelain", "-uall", "-z")
        sciezki = []
        for wpis in r.stdout.split("\0"):
            if len(wpis) > 3:
                sciezki.append(wpis[3:])
        return sciezki

    def cofnij(self, katalog, sciezki):
        for s in sciezki:
            self._git(katalog, "checkout", "--quiet", "HEAD", "--", s, sprawdz=False)
            plik = Path(katalog) / s
            if plik.exists() and s in self.zmienione(katalog):      # nowy plik spoza dozwolonych ścieżek
                plik.unlink()

    def diff(self, katalog, pliki):
        """Diff tylko wskazanych plików (nigdy `git add -A`)."""
        if not pliki:
            return ""
        self._git(katalog, "add", "--", *pliki)
        return self._git(katalog, "diff", "--cached", "--no-color").stdout

    def testy(self, katalog):
        r = subprocess.run(self.komenda_testow, cwd=katalog, capture_output=True, text=True, timeout=300)
        return r.returncode == 0, (r.stdout + r.stderr)[-4000:]

    def commit_push(self, katalog, komunikat, galaz, pliki):
        """Commituje WYŁĄCZNIE wskazane pliki (agent przekazuje tylko te z dozwolonych ścieżek)."""
        if not pliki:
            raise RuntimeError("brak plików do commita")
        self._git(katalog, "add", "--", *pliki)
        self._git(katalog, "commit", "--quiet", "-m", komunikat)
        self._git(katalog, "push", "--quiet", "origin", f"HEAD:refs/heads/{galaz}")

    def sprzatnij(self):
        for k in self._katalogi:
            shutil.rmtree(k, ignore_errors=True)


# ── claude ────────────────────────────────────────────────────────────────────

class ClaudeAgent:
    def __init__(self, model):
        self.model = model

    def edytuj(self, katalog, prompt):
        """Edycja plików w katalogu (tylko Read/Write/Edit, tryb acceptEdits). Zwraca (ok, tekst)."""
        r = subprocess.run(
            ["claude", "--print", prompt, "--model", self.model, "--tools", "Read,Write,Edit",
             "--allowedTools", "Read,Write,Edit", "--permission-mode", "acceptEdits"],
            cwd=katalog, env=env_modelu(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        return r.returncode == 0, (r.stdout + r.stderr)[-3000:]

    def zapytaj(self, prompt):
        """Pytanie bez narzędzi (np. sprawdzenie zakazów). Zwraca tekst odpowiedzi."""
        r = subprocess.run(
            ["claude", "--print", prompt, "--model", self.model, "--tools", ""],
            env=env_modelu(), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            raise RuntimeError(f"claude zakończył się kodem {r.returncode}")
        return r.stdout


# ── poczta ────────────────────────────────────────────────────────────────────

class Poczta:
    """Wysyłka przez SMTP z GMAIL_ADDRESS (hasło aplikacji). Dane logowania tylko ze środowiska, nigdy do logów."""

    def __init__(self, W):
        self.W = W

    def nadawca(self):
        from sekrety import czysc
        return czysc(os.environ.get("GMAIL_ADDRESS", ""))

    def wyslij(self, email_do, imie_do, temat, tresc, ics=None, zalaczniki=()):
        import smtplib
        import ssl
        from email.message import EmailMessage
        from email.utils import formataddr, make_msgid

        from sekrety import czysc
        nadawca = czysc(os.environ.get("GMAIL_ADDRESS", ""))
        haslo = czysc(os.environ.get("GMAIL_APP_PASSWORD", ""))
        if not nadawca or not haslo:
            raise RuntimeError("brak GMAIL_ADDRESS albo GMAIL_APP_PASSWORD")
        msg = EmailMessage()
        msg["From"] = formataddr((self.W["nadawca_imie"], nadawca))
        msg["To"] = formataddr((imie_do, email_do))
        msg["Subject"] = " ".join(temat.split())
        msg["Message-ID"] = make_msgid(domain=nadawca.split("@")[-1])
        msg.set_content(tresc)
        for nazwa, dane in zalaczniki:
            msg.add_attachment(dane, maintype="application", subtype="pdf", filename=nazwa)
        if ics:
            msg.add_attachment(ics.encode("utf-8"), maintype="text", subtype="calendar", filename="zaproszenie.ics",
                               params={"method": "REQUEST", "charset": "utf-8"})
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        smtp = self.W["smtp"]
        try:
            with smtplib.SMTP_SSL(smtp["host"], smtp["port"], context=ctx, timeout=60) as srv:
                srv.login(nadawca, haslo)
                srv.send_message(msg)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(maskuj(f"{type(exc).__name__}: {exc}", [haslo, nadawca])) from None
        return msg["Message-ID"]


# ── Slack ─────────────────────────────────────────────────────────────────────

class SlackAgent:
    def wyslij(self, tekst, bloki=None):
        from przetworz import send_slack
        ok, blad = send_slack(tekst, blocks=bloki)
        if not ok:
            print(f"Slack: {slack_bezpiecznie(blad or '', 120)}")
