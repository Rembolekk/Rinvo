#!/usr/bin/env python3
"""
linear_sync.py – wysyła wynik.json do Linear (team RIN).
Tylko biblioteka standardowa Pythona (urllib, json, os, sys, time, argparse, hashlib, pathlib).

Użycie:
  python linear_sync.py wyniki/auto-tama/2026-10-06-call-statusowy/wynik.json --klient auto-tama
  python linear_sync.py wyniki/auto-tama/2026-10-06-call-statusowy/wynik.json --klient auto-tama --dry-run
"""

import json
import os
import re
import ssl
import sys
import time
import argparse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

from maile import czy_mail, kontakt_ma_prawo_decyzji, wczytaj_meta_maila, znajdz_kontakt
import notatki
import zasady
from sekrety import czysc
from podpis import podpisz_agenta
import zakazy_czas


def _date_from_path(path_str):
    """Extract YYYY-MM-DD from a transcript filename, e.g. '2026-10-06-call.md' → '2026-10-06'."""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', Path(str(path_str)).name)
    return m.group(1) if m else ""

# ── progi ────────────────────────────────────────────────────────────────────

RISK_REPEAT_THRESHOLD = 2      # ile różnych rozmów z tym samym tematem ryzyka → "Powtarzające się ryzyko"
PRODUCT_REQUEST_THRESHOLD = 2  # ilu różnych klientów z tą samą prośbą → "Wielu klientów"

# ── stałe ────────────────────────────────────────────────────────────────────

TEAM_KEY = "RIN"
LINEAR_API = "https://api.linear.app/graphql"

REQUIRED_LABELS = [
    "Błąd", "Konfiguracja", "Finanse", "Zadanie", "Produkt",
    "Czeka na klienta", "Ryzyko", "Dla agenta", "Do weryfikacji",
    "Zablokowane przez zakaz", "Powtarzające się ryzyko", "Wielu klientów",
    "Decyzja człowieka",
    "repo: rinvo-app", "repo: rinvo", "repo: rinvo-ops",
    "Szkic gotowy", "Wyślij", "Wysłano",
]

LABEL_COLORS = {
    "Błąd": "#e11d48",
    "Konfiguracja": "#7c3aed",
    "Finanse": "#0ea5e9",
    "Zadanie": "#16a34a",
    "Produkt": "#f59e0b",
    "Czeka na klienta": "#6b7280",
    "Ryzyko": "#dc2626",
    "Dla agenta": "#8b5cf6",
    "Do weryfikacji": "#f97316",
    "Zablokowane przez zakaz": "#be123c",
    "Powtarzające się ryzyko": "#991b1b",
    "Wielu klientów": "#0891b2",
    "Decyzja człowieka": "#2563eb",
    "Szkic gotowy": "#eab308",
    "Wyślij": "#16a34a",
    "Wysłano": "#15803d",
    "repo: rinvo-app": "#0d9488",
    "repo: rinvo": "#475569",
    "repo: rinvo-ops": "#64748b",
}

TYP_DO_ETYKIETY = {
    "bug": "Błąd",
    "zmiana_konfiguracji": "Konfiguracja",
    "poprawka_bazy_wiedzy": "Konfiguracja",
    "finanse": "Finanse",
}

TYPY_DLA_AGENTA = {"bug", "zmiana_konfiguracji", "poprawka_bazy_wiedzy"}


# ── klucz API ────────────────────────────────────────────────────────────────

def load_api_key():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            name, _, val = line.partition("=")
            if czysc(name) == "LINEAR_API_KEY":
                key = czysc(val)  # bez spacji, enterów, \u2028/\u2029 z Notatek
                if key:
                    return key
    key = czysc(os.environ.get("LINEAR_API_KEY", ""))
    if key:
        return key
    sys.exit("Błąd: brak LINEAR_API_KEY w .env ani w środowisku.")


# ── SSL ──────────────────────────────────────────────────────────────────────

def _ssl_context():
    ctx = ssl.create_default_context()
    for ca in ["/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem",
               "/opt/homebrew/etc/openssl@3/cert.pem"]:
        if os.path.exists(ca):
            try:
                ctx.load_verify_locations(ca)
                return ctx
            except ssl.SSLError:
                continue
    return ctx


_SSL_CTX = _ssl_context()


# ── HTTP / GraphQL ────────────────────────────────────────────────────────────

def gql(api_key, query, variables=None, retries=3, delay=2):
    if query == M_ADD_COMMENT and variables and "body" in variables:      # każdy komentarz automatu: „Agent: …”
        variables = {**variables, "body": podpisz_agenta(variables["body"])}
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API, data=payload,
        headers={"Content-Type": "application/json", "Authorization": api_key},
        method="POST",
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if "errors" in body:
                msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
                raise RuntimeError(f"GraphQL error: {msgs}")
            return body.get("data", {})
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            last_err = RuntimeError(f"HTTP {exc.code}: {body_text[:300]}")
            if attempt < retries:
                print(f"  ⚠ Próba {attempt}/{retries}: {last_err}. Czekam {delay}s…")
                time.sleep(delay)
        except (urllib.error.URLError, RuntimeError, OSError) as exc:
            last_err = exc
            if attempt < retries:
                print(f"  ⚠ Próba {attempt}/{retries}: {exc}. Czekam {delay}s…")
                time.sleep(delay)
    sys.exit(f"Błąd sieci po {retries} próbach: {last_err}")


# ── zapytania GraphQL ─────────────────────────────────────────────────────────

Q_TEAM = """
query($key: String!) {
  teams(filter: { key: { eq: $key } }) {
    nodes { id key name }
  }
}
"""


def Q_LABELS(team_id):
    return f"""
query {{
  issueLabels(filter: {{ team: {{ id: {{ eq: "{team_id}" }} }} }}) {{
    nodes {{ id name }}
  }}
}}
"""


def Q_STATES(team_id):
    return f"""
query {{
  workflowStates(filter: {{ team: {{ id: {{ eq: "{team_id}" }} }} }}) {{
    nodes {{ id name type }}
  }}
}}
"""


def Q_ISSUE_LABELS(issue_id):
    return f"""
query {{
  issue(id: "{issue_id}") {{
    labels {{ nodes {{ id name }} }}
  }}
}}
"""


def Q_ISSUE_STATE(issue_id):
    return f"""
query {{
  issue(id: "{issue_id}") {{
    state {{ name type }}
    labels {{ nodes {{ id name }} }}
  }}
}}
"""


M_CREATE_LABEL = """
mutation($teamId: String!, $name: String!, $color: String!) {
  issueLabelCreate(input: { teamId: $teamId, name: $name, color: $color }) {
    success
    issueLabel { id name }
  }
}
"""

M_CREATE_ISSUE = """
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier url }
  }
}
"""

M_UPDATE_ISSUE = """
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue { id identifier }
  }
}
"""

M_ADD_COMMENT = """
mutation($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
    comment { id }
  }
}
"""


# ── Linear: pobieranie danych ─────────────────────────────────────────────────

def get_team(api_key):
    data = gql(api_key, Q_TEAM, {"key": TEAM_KEY})
    nodes = data.get("teams", {}).get("nodes", [])
    if not nodes:
        sys.exit(f"Błąd: nie znaleziono zespołu '{TEAM_KEY}' w Linear.")
    return nodes[0]


def ensure_labels(api_key, team_id):
    data = gql(api_key, Q_LABELS(team_id))
    existing = {n["name"]: n["id"] for n in data.get("issueLabels", {}).get("nodes", [])}
    for name in REQUIRED_LABELS:
        if name not in existing:
            color = LABEL_COLORS.get(name, "#64748b")
            result = gql(api_key, M_CREATE_LABEL,
                         {"teamId": team_id, "name": name, "color": color})
            lc = result.get("issueLabelCreate", {})
            if lc.get("success"):
                existing[name] = lc["issueLabel"]["id"]
                print(f"  ✓ Etykieta: {name!r}")
            else:
                print(f"  ⚠ Nie udało się: {name!r}")
    return existing


def get_workflow_states(api_key, team_id):
    data = gql(api_key, Q_STATES(team_id))
    return data.get("workflowStates", {}).get("nodes", [])


def _pisownia(tekst):
    """Linear nazywa stan „Canceled” (typ „canceled”), a w kodzie bywa „Cancelled”: obie pisownie to to samo."""
    return str(tekst).lower().replace("cancelled", "canceled")


def find_state(states, preferred_name, fallback_type):
    for s in states:
        if _pisownia(s["name"]) == _pisownia(preferred_name):
            return s["id"]
    for s in states:
        if _pisownia(s.get("type")) == _pisownia(fallback_type):
            return s["id"]
    return None


# ── lokalne pliki ─────────────────────────────────────────────────────────────

def load_karta(klient):
    path = Path("ops") / "klienci" / klient / "karta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"klient": klient, "decydenci": [], "zakazy": [], "otwarte_sprawy": {}}


def save_karta(klient, karta):
    path = Path("ops") / "klienci" / klient / "karta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(karta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_karta_md(klient, karta):
    lines = [f"# Karta klienta: {klient}\n"]

    if karta.get("decydenci"):
        lines.append("## Decydenci\n")
        for d in karta["decydenci"]:
            role = f" – {d['rola']}" if d.get("rola") else ""
            lines.append(f"- **{d['imie']}**{role}")
        lines.append("")

    if karta.get("kontakty"):
        lines.append("## Kontakty (maile)\n")
        for k in karta["kontakty"]:
            flaga = "" if k.get("potwierdzony", True) else f" — **{k.get('status', 'niepotwierdzony')}**"
            lines.append(f"- **{k.get('imie', '?')}** <{k.get('email', '')}> — {k.get('rola', '')}; "
                         f"decyzje: {k.get('zakres_decyzji', 'brak')}{flaga}")
        if karta.get("domeny"):
            lines.append(f"- Domeny klienta: {', '.join(karta['domeny'])}")
        lines.append("")

    if karta.get("decyzje_zastrzezone"):
        lines.append("## Decyzje zastrzeżone dla konkretnej osoby\n")
        for d in karta["decyzje_zastrzezone"]:
            lines.append(f"- {d.get('opis', '')} — tylko: **{d.get('zastrzezone_dla', '')}**")
        lines.append("")

    if karta.get("zakazy"):
        lines.append("## Zakazy i ograniczenia\n")
        for z in karta["zakazy"]:
            lines.append(f"### {z['id']}: {z['tytul']}\n")
            if z.get("opis"):
                lines.append(f"{z['opis']}\n")
            for c in z.get("cytat", []):
                lines.append(f"> {c}\n")
            lines.append("")

    if karta.get("zakazy_wygasle"):
        lines.append("## Wygasłe zakazy (minął okres)\n")
        for z in karta["zakazy_wygasle"]:
            okres = z.get("okres") or {}
            lines.append(f"### {z['id']}: {z['tytul']} (wygasł {z.get('wygasl', okres.get('do', '?'))})\n")
            for c in z.get("cytat", []):
                lines.append(f"> {c}\n")
            lines.append("")

    if karta.get("historia_zakazow"):
        lines.append("## Historia zakazów (uchylone)\n")
        for z in karta["historia_zakazow"]:
            lines.append(f"- ~~{z['id']}: {z['tytul']}~~ — uchylony: _{z.get('uchylony', '')}_")
        lines.append("")

    otwarte = karta.get("otwarte_sprawy", {})
    if otwarte:
        lines.append("## Otwarte sprawy w Linearze\n")
        for klucz, info in otwarte.items():
            if isinstance(info, dict):
                url = info.get("url", "")
                identifier = info.get("identifier", klucz)
                tytul = info.get("tytul", "")
                line = f"- [{identifier}]({url})" if url else f"- `{identifier}`"
                if tytul:
                    line += f" – {tytul}"
                lines.append(line)
            else:
                lines.append(f"- {klucz}: {info}")
        lines.append("")

    ryzyka = karta.get("ryzyka", {})
    if ryzyka:
        lines.append("## Ryzyka powtarzające się\n")
        for temat, occurrences in ryzyka.items():
            unique_src = len({r["zrodlo"] for r in occurrences})
            lines.append(f"- **{temat}** ({unique_src} rozmów, {len(occurrences)} wzmianek)")
        lines.append("")

    path = Path("ops") / "klienci" / klient / "karta.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ karta.md: {path}")


def load_prosby():
    path = Path("ops/produkt/prosby.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_prosby(prosby):
    path = Path("ops/produkt/prosby.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prosby, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")



# ── logika: etykiety i priorytety ─────────────────────────────────────────────

def should_get_agent_label(item, karta=None, zasady_=None, wielu=False):
    """Czy pozycja idzie do agenta wg ops/zasady.json (domyślnie tak; człowiek tylko wg reguł,
    a bez kryteriów akceptacji agent nie dostaje zadania)."""
    z = zasady_ or zasady.wczytaj_zasady()
    return zasady.przypisz(item, z, karta, wielu)["komu"] == "agent"


def get_issue_labels_from_linear(api_key, issue_id):
    data = gql(api_key, Q_ISSUE_LABELS(issue_id))
    return data.get("issue", {}).get("labels", {}).get("nodes", [])


# ── budowanie opisu ───────────────────────────────────────────────────────────

def _cytat_blok(tekst):
    return "\n".join(f"> {linia}" for linia in str(tekst).splitlines() or [""])


def build_description(item, source_path, karta=None, przyp=None, Z=None):
    """Stały układ: Cel, Kontekst (z cytatami), Kryteria akceptacji (lista do odhaczenia),
    Jak sprawdzić, Repo, [Dlaczego człowiek, Szkic], Czego nie ruszać, Źródło."""
    Z = Z or zasady.wczytaj_zasady()
    karta = karta or {}
    sekcja = item.get("sekcja")
    parts = [f"## Cel\n\n{item.get('cel') or item.get('tytul', '')}"]

    ctx = []
    if item.get("opis"):
        ctx.append(item["opis"])
    meta = []
    if item.get("wlasciciel"):
        meta.append(f"**Właściciel:** {item['wlasciciel']}")
    warunek = item.get("warunek", "brak")
    if warunek and warunek != "brak":
        meta.append(f"**Warunek:** {warunek}")
    if item.get("pewnosc") == "niska":
        meta.append("**⚠ Pewność: niska** — wymaga weryfikacji przed działaniem")
    if meta:
        ctx.append("\n".join(meta))
    cytaty = item.get("cytat", [])
    if cytaty:
        ctx.append("**Cytaty ze źródła:**\n\n" + "\n".join(f"> {c}" for c in cytaty))
    wnioski = item.get("wnioski", [])
    if wnioski:
        ctx.append("\n".join(f"- **[wniosek]** {w}" for w in wnioski))
    pr = item.get("przypomnienie", {})
    if pr:
        r_parts = []
        if pr.get("data") and str(pr["data"]) not in ("nie ustalono",):
            r_parts.append(f"data: {pr['data']}")
        if pr.get("limit") is not None and str(pr["limit"]) not in ("nie ustalono",):
            r_parts.append(f"limit: {pr['limit']}")
        if pr.get("uwagi"):
            r_parts.append(pr["uwagi"])
        if r_parts:
            ctx.append(f"**Przypomnienie:** {' · '.join(r_parts)}")
    parts.append("## Kontekst\n\n" + "\n\n".join(ctx or ["(brak)"]))

    kryteria = [str(k).strip() for k in (item.get("kryteria_akceptacji") or []) if str(k).strip()]
    if kryteria:
        parts.append("## Kryteria akceptacji\n\n" + "\n".join(f"- [ ] {k}" for k in kryteria))
    elif sekcja in (1, 3):
        parts.append("## Kryteria akceptacji\n\n_brak: uzupełnij, zanim zadanie trafi do agenta_")
    if item.get("jak_sprawdzic"):
        parts.append(f"## Jak sprawdzić\n\n{item['jak_sprawdzic']}")
    repo = zasady.repo_pozycji(item, Z) or item.get("repo")
    if repo:
        parts.append(f"## Repo\n\n`{repo}`: {Z.get('repo', {}).get(repo, '')}".rstrip(": "))

    if przyp and przyp.get("komu") == "czlowiek":
        parts.append("## Dlaczego człowiek\n\n" + "\n".join(f"- {t}" for t in zasady.powody_tekst(przyp)))
        if przyp.get("wymaga_szkicu"):
            if item.get("szkic_klienta"):
                parts.append("## Szkic dla klienta (do wysłania przez człowieka)\n\n"
                             + _cytat_blok(item["szkic_klienta"]))
            else:
                parts.append("## Szkic dla klienta\n\n_brak szkicu: agent ma go przygotować w tym zgłoszeniu_")
    elif przyp and przyp.get("komu") == "weryfikacja":
        parts.append("## Do weryfikacji\n\n" + "\n".join(f"- {t}" for t in zasady.powody_tekst(przyp)))

    nie_ruszac = []
    powiazane, pozostale = zasady.zakazy_wg_tematu(item, karta, Z)      # tylko krótkie tytuły, bez cytatów
    if powiazane:
        nie_ruszac.append("**Dotyczą tej samej części konfiguracji:**")
        nie_ruszac += [f"- Zakaz {z['id']}: {z['tytul']}" for z in powiazane]
        if pozostale:
            nie_ruszac.append("\n**Pozostałe zakazy klienta:**")
    nie_ruszac += [f"- Zakaz {z['id']}: {z['tytul']}" for z in pozostale]
    for d in karta.get("decyzje_zastrzezone", []):
        osoby = d.get("zastrzezone_dla")
        osoby = osoby if isinstance(osoby, str) else ", ".join(osoby or [])
        nie_ruszac.append(f"- **Decyzja zastrzeżona dla {osoby}:** {d.get('opis', '')}")
    parts.append("## Czego nie ruszać\n\n" + ("\n".join(nie_ruszac) or "_brak zakazów w karcie klienta_"))

    parts.append(f"## Źródło\n\n`{source_path}`")
    return "\n\n".join(parts)


def przypomnienie_z_pozycji(item, Z, karta=None):
    """Dane o przypomnieniach dla sprawy czekającej: limit z rozmowy, termin, brak prośby o ich zakaz."""
    pr = item.get("przypomnienie") or {}
    limit_txt = str(pr.get("limit", ""))
    m = re.search(r"\d+", limit_txt)
    limit = int(m.group()) if m and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", limit_txt.strip()) else None
    zakazane = limit == 0
    tekst_zakazu = " ".join([limit_txt, str(pr.get("uwagi", ""))]).lower()
    if any(s in tekst_zakazu for s in Z.get("przypomnienia", {}).get("slowa_zakazu", [])):
        zakazane = True
    for zk in (karta or {}).get("zakazy", []):
        t = " ".join([zk.get("tytul", ""), zk.get("opis", "")] + zk.get("cytat", [])).lower()
        if zk.get("klucz_sprawy") == item.get("klucz_sprawy") and any(
                s in t for s in Z.get("przypomnienia", {}).get("slowa_zakazu", [])):
            zakazane = True
    if limit is None:
        limit = Z.get("przypomnienia", {}).get("domyslny_limit", 1)
    return {"limit": limit, "wykorzystane": 0, "nie_przypominac": zakazane}


def zapisz_przypisanie(entry, item, Z, karta, wielu):
    """Zapamiętuje w karcie, komu przypisano zgłoszenie (do porównań i do wznowienia)."""
    sekcja = item.get("sekcja")
    p = zasady.przypisz(item, Z, karta, wielu)
    entry["przypisanie"] = {"komu": p["komu"], "powody": zasady.powody_tekst(p),
                            "reguly": [x["regula"] for x in p["powody"]]}
    if sekcja == 2:
        w = zasady.przypisz(item, Z, karta, wielu, sekcja=1)
        entry["po_wznowieniu"] = {"komu": w["komu"], "powody": zasady.powody_tekst(w),
                                  "wymaga_szkicu": w["wymaga_szkicu"]}
        stare = entry.get("przypomnienie") or {}
        entry["przypomnienie"] = przypomnienie_z_pozycji(item, Z, karta)
        for k in ("wykorzystane", "ostatni_szkic"):      # licznik wykorzystanych przypomnień nie wraca do zera
            if k in stare:
                entry["przypomnienie"][k] = stare[k]
    return p


def komentarz_przypisania(komu, powody, wymaga_szkicu=False):
    """Treść komentarza z powodem (None, gdy nic nie trzeba mówić)."""
    if komu == "czlowiek":
        t = "**Decyzja człowieka**\n\nPowody:\n" + "\n".join(f"- {x}" for x in powody)
        if wymaga_szkicu:
            t += "\n\nAgent przygotowuje gotowy szkic w tym zgłoszeniu, człowiek tylko wysyła."
        return t
    if komu == "weryfikacja":
        return ("**Do weryfikacji:** " + "; ".join(powody) +
                ". Agent nie dostanie zadania, dopóki w zgłoszeniu nie będzie kryteriów akceptacji.")
    return None


def parse_due_date(termin):
    if not termin or str(termin) in ("brak", "nie ustalono", ""):
        return None
    try:
        date.fromisoformat(str(termin))
        return str(termin)
    except ValueError:
        return None


# ── ryzyka i prośby produktowe ────────────────────────────────────────────────

def update_risk_counter(karta, item, source, today):
    temat = item.get("temat_ryzyka", "inne")
    ryzyka = karta.setdefault("ryzyka", {})
    if temat not in ryzyka:
        ryzyka[temat] = []
    cytat = item.get("cytat", [""])[0] if item.get("cytat") else ""
    if not any(r.get("zrodlo") == source and r.get("cytat") == cytat for r in ryzyka[temat]):
        # data = data ŹRÓDŁA (rozmowy albo maila, z nazwy pliku), a nie dzień przetwarzania
        ryzyka[temat].append({"data": _date_from_path(source) or today, "zrodlo": source, "cytat": cytat})
    unique_sources = len({r["zrodlo"] for r in ryzyka[temat]})
    return unique_sources >= RISK_REPEAT_THRESHOLD, unique_sources


def build_risk_history(karta, temat):
    occurrences = karta.get("ryzyka", {}).get(temat, [])
    lines = [f"**Powtarzające się ryzyko ({temat}) — {len(occurrences)} wystąpień:**"]
    for r in occurrences:
        lines.append(f"- {r['data']} | `{r['zrodlo']}`: _{r['cytat']}_")
    return "\n".join(lines)


def update_prosby(prosby, item, klient, source, today):
    klucz = item.get("klucz_funkcji")
    if not klucz:
        return False, 0
    if klucz not in prosby:
        prosby[klucz] = {"tytul": item.get("tytul", ""), "prosby": []}
    prosby[klucz]["prosby"].append({
        "klient": klient,
        "cytat": item.get("cytat", [""])[0] if item.get("cytat") else "",
        "data": _date_from_path(source) or today,           # data ŹRÓDŁA, nie dzień przetwarzania
        "zrodlo": source,
    })
    unique_clients = len({p["klient"] for p in prosby[klucz]["prosby"]})
    return unique_clients >= PRODUCT_REQUEST_THRESHOLD, unique_clients


def build_clients_comment(prosby, klucz):
    entry = prosby.get(klucz, {})
    seen = {}
    for r in entry.get("prosby", []):
        if r["klient"] not in seen:
            seen[r["klient"]] = r
    lines = [f"**Prośba od {len(seen)} klientów:**"]
    for client, r in seen.items():
        lines.append(f"- **{client}**: _{r['cytat']}_")
    return "\n".join(lines)


# ── uprawnienia: kto może uchylić zakaz albo zmienić zastrzeżoną decyzję ───────

def ustal_zrodlo(source, wynik, karta, meta=None):
    """Kim jest autor źródła i jaką ma datę. Dla maila nadawca i data pochodzą Z PLIKU MAILA
    zapisanego przez maile.py, nigdy z wynik.json (model nie może ich podmienić)."""
    if czy_mail(source):
        meta = meta if meta is not None else wczytaj_meta_maila(source)
        adres = meta.get("od_adres", "")
        kontakt = znajdz_kontakt(karta, adres) if adres else None
        if not kontakt:
            powod = "nadawca nie jest kontaktem klienta w karcie" if adres else "nie ustalono nadawcy maila"
        elif not kontakt_ma_prawo_decyzji(kontakt):
            powod = f"kontakt {adres} jest niepotwierdzony („{kontakt.get('status', 'bez prawa decyzji')}”)"
        else:
            powod = ""
        return {
            "typ": "mail", "data": meta.get("data") or _date_from_path(source),
            "imiona": [kontakt["imie"]] if kontakt else [], "email": adres, "kontakt": kontakt,
            "prawo": not powod, "powod_braku_prawa": powod,
            "opis": f"mail od {adres or 'nieznanego nadawcy'}",
        }
    spotkanie = wynik.get("spotkanie", {})
    uczestnicy = list(spotkanie.get("uczestnicy", []))
    return {
        "typ": "rozmowa", "data": spotkanie.get("data", "") or _date_from_path(source),
        "imiona": uczestnicy, "email": "", "kontakt": None, "prawo": True, "powod_braku_prawa": "",
        "opis": "rozmowa (uczestnicy: " + (", ".join(uczestnicy) or "brak danych") + ")",
    }


def _ta_sama_osoba(a, b):
    a, b = a.strip().casefold(), b.strip().casefold()
    return bool(a) and bool(b) and (a == b or a.startswith(b + " ") or b.startswith(a + " "))


def wymagani_decydenci(karta, zakaz_id=None, klucz=None):
    """Kto może uchylić zakaz / zmienić decyzję. None = brak ograniczenia.

    1) decyzje_zastrzezone w karcie wskazują konkretną osobę (np. Opel: Kasia, nie Paweł),
    2) uchylenie zakazu bez takiego wpisu: dowolny decydent z karty."""
    osoby = []
    for d in karta.get("decyzje_zastrzezone", []):
        if (zakaz_id and zakaz_id in d.get("zakazy", [])) or (klucz and klucz in d.get("klucze_spraw", [])):
            z = d.get("zastrzezone_dla", [])
            osoby += [z] if isinstance(z, str) else list(z)
    if osoby:
        return osoby
    if zakaz_id:
        return [d["imie"] for d in karta.get("decydenci", []) if d.get("imie")]
    return None


def sprawdz_uprawnienia(karta, upd, zrodlo, zakaz_id=None, klucz=None):
    """(True, "") albo (False, powód). Sprawdza kod, nie model."""
    wymagani = wymagani_decydenci(karta, zakaz_id, klucz)
    if wymagani is None:
        return True, ""
    co = f"uchylenie zakazu {zakaz_id}" if zakaz_id else f"decyzja w sprawie {klucz}"
    if upd.get("pewnosc") == "niska":
        return False, (f"{co}: pewność niska (np. polecenie przekazane w czyimś imieniu) — "
                       f"takie zmiany wymagają decyzji człowieka")
    if not zrodlo.get("prawo"):
        return False, f"{co}: {zrodlo.get('powod_braku_prawa') or 'źródło bez prawa decyzji'}"
    if not any(_ta_sama_osoba(n, w) for n in zrodlo.get("imiona", []) for w in wymagani):
        return False, (f"{co} jest zastrzeżone dla: {', '.join(wymagani) or 'brak decydentów w karcie'}; "
                       f"źródło: {zrodlo.get('opis', '?')}")
    return True, ""


def dodaj_etykiete(api_key, linear_id, label_map, nazwa):
    etykieta_id = label_map.get(nazwa)
    if not etykieta_id:
        return
    ids = [l["id"] for l in get_issue_labels_from_linear(api_key, linear_id)]
    if etykieta_id not in ids:
        gql(api_key, M_UPDATE_ISSUE, {"id": linear_id, "input": {"labelIds": ids + [etykieta_id]}})


def odrzuc_aktualizacje(api_key, karta, upd, source, powod, issue_info, is_zakaz,
                        label_map, state_ids, team_id, klient, dry_run):
    """Odrzucona aktualizacja: nic nie zmieniamy, ale człowiek ma to zobaczyć w Linearze
    (etykieta „Do weryfikacji” i komentarz z powodem; dla zakazu osobne zgłoszenie)."""
    klucz, status = upd.get("klucz_sprawy", ""), upd.get("nowy_status", "")
    print(f"  ⛔ Odrzucono aktualizację: {klucz} → {status} | {powod}")
    if dry_run:
        return
    odrzucone = karta.setdefault("odrzucone_aktualizacje", [])
    if any(r.get("klucz_sprawy") == klucz and r.get("zrodlo") == source for r in odrzucone):
        return  # już zgłoszone (ponowny przebieg)
    tresc = (f"**⛔ Odrzucono aktualizację → {status}**\n\n{powod}\n\n"
             f"> {upd.get('cytat', '')}\n\nŹródło: `{source}`")
    ident = ""
    if isinstance(issue_info, dict) and issue_info.get("linear_id"):
        dodaj_etykiete(api_key, issue_info["linear_id"], label_map, "Do weryfikacji")
        gql(api_key, M_ADD_COMMENT, {"issueId": issue_info["linear_id"], "body": tresc})
        ident = issue_info.get("identifier", "")
    elif is_zakaz and team_id:
        zakaz = next((z for z in karta.get("zakazy", []) if z.get("id") == klucz), {})
        etykiety = [label_map[n] for n in ("Do weryfikacji", "Zablokowane przez zakaz") if n in label_map]
        wynik = gql(api_key, M_CREATE_ISSUE, {"input": {
            "teamId": team_id,
            "title": f"[{klient}] Do weryfikacji: wniosek o uchylenie zakazu {klucz} odrzucony",
            "description": f"{tresc}\n\n## Zakaz, który nadal obowiązuje\n\n**{klucz} {zakaz.get('tytul', '')}**",
            "stateId": state_ids.get("backlog"),
            "labelIds": etykiety,
        }})
        ident = ((wynik.get("issueCreate") or {}).get("issue") or {}).get("identifier", "")
    odrzucone.append({"klucz_sprawy": klucz, "nowy_status": status, "zrodlo": source,
                      "powod": powod, "zgloszenie": ident})


# ── istniejące zgłoszenia: eskalacja ryzyka i termin ──────────────────────────

def get_issue_state_and_labels(api_key, issue_id):
    data = gql(api_key, Q_ISSUE_STATE(issue_id)).get("issue") or {}
    return {
        "type": (data.get("state") or {}).get("type", ""),
        "name": (data.get("state") or {}).get("name", ""),
        "labels": (data.get("labels") or {}).get("nodes", []),
    }


def _najnowsza_data_rozmowy(info):
    daty = [d for d in (_date_from_path(s) for s in info.get("zrodla", [])) if d]
    return max(daty) if daty else ""


def eskaluj_istniejace_ryzyko(api_key, karta, existing, klucz, item, label_map, source, today):
    """Ryzyko wspomniane w kolejnej rozmowie: licznik rozmów w karcie, a po przekroczeniu
    progu etykieta „Powtarzające się ryzyko”, priorytet Urgent i historia w komentarzu."""
    temat = item.get("temat_ryzyka", "inne")
    escalate, _ = update_risk_counter(karta, item, source, today)
    if not escalate:
        return
    linear_id = existing.get("linear_id")
    ident = existing.get("identifier", klucz)
    etykieta_id = label_map.get("Powtarzające się ryzyko")
    if not linear_id or not etykieta_id:
        return
    stan = get_issue_state_and_labels(api_key, linear_id)
    ids = [l["id"] for l in stan["labels"]]
    nowa = etykieta_id not in ids
    if nowa:
        ids.append(etykieta_id)
    gql(api_key, M_UPDATE_ISSUE, {"id": linear_id, "input": {"labelIds": ids, "priority": 1}})
    if nowa:
        gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": build_risk_history(karta, temat)})
    print(f"  ↑ Powtarzające się ryzyko: {ident} ({klucz}) | {existing.get('tytul', '')}")


def uzgodnij_istniejace(api_key, karta, existing, klucz, item, sekcja, label_map, termin,
                        meeting_date, source, today):
    """Idempotentne uzgodnienie zgłoszenia, które już istnieje (nowa rozmowa albo ponowna analiza):
    eskalacja ryzyka i termin z NAJNOWSZEJ rozmowy (starsza rozmowa nie nadpisuje nowszego terminu)."""
    if not isinstance(existing, dict) or not existing.get("linear_id"):
        return
    if sekcja == 5:
        eskaluj_istniejace_ryzyko(api_key, karta, existing, klucz, item, label_map, source, today)
    if termin and meeting_date and meeting_date >= _najnowsza_data_rozmowy(existing):
        gql(api_key, M_UPDATE_ISSUE, {"id": existing["linear_id"], "input": {"dueDate": termin}})
        print(f"  ✓ Termin → {existing.get('identifier', klucz)} ({klucz}): {termin}")


# ── zakazy: unikalne id w karcie ───────────────────────────────────────────────

def _numer_zakazu(zid):
    m = re.search(r"\d+", str(zid))
    return int(m.group()) if m else 0


def zakaz_juz_w_karcie(karta, z, source):
    """Czy ten zakaz (z bieżącego wyniku) już jest w karcie: aktywny albo uchylony?
    Id NIE wystarcza: numeracja Z1, Z2… zaczyna się od nowa w każdej rozmowie."""
    cytaty = set(z.get("cytat", []))
    for k in karta.get("zakazy", []) + karta.get("historia_zakazow", []) + karta.get("zakazy_wygasle", []):
        if k.get("klucz_sprawy") and k.get("zrodlo") == source and k["klucz_sprawy"] == z.get("klucz_sprawy"):
            return True
        if k.get("id") == z.get("id") and k.get("tytul") == z.get("tytul"):
            return True
        if cytaty & set(k.get("cytat", [])):
            return True
    return False


def dodaj_zakazy(karta, nowe_zakazy, source, dry_run=False):
    """Dodaje zakazy z rozmowy do karty z unikalnymi id. Zwraca liczbę dodanych."""
    uzyte = {z.get("id") for z in karta.get("zakazy", []) + karta.get("historia_zakazow", []) + karta.get("zakazy_wygasle", [])}
    nastepny = max([_numer_zakazu(i) for i in uzyte] + [0]) + 1
    dodano = 0
    for z in nowe_zakazy:
        if zakaz_juz_w_karcie(karta, z, source):
            continue
        zid = z["id"]
        if zid in uzyte:
            zid = f"Z{nastepny}"
            nastepny += 1
            print(f"  ⚠ Id {z['id']} zajęte w karcie → zakaz zapisany jako {zid}: {z.get('tytul', '')}")
        uzyte.add(zid)
        nastepny = max(nastepny, _numer_zakazu(zid) + 1)
        karta.setdefault("zakazy", []).append({
            "id": zid,
            "klucz_sprawy": z.get("klucz_sprawy", ""),
            "tytul": z["tytul"],
            "opis": z.get("opis", ""),
            "cytat": z.get("cytat", []),
            "wlasciciel": z.get("wlasciciel", ""),
            "zrodlo": source,
        })
        dodano += 1
        if dry_run:
            print(f"  [zakaz → karta.json] {zid}: {z['tytul']}")
    return dodano


# ── aktualizacje otwartych spraw ──────────────────────────────────────────────

def process_aktualizacje(api_key, wynik, karta, state_ids, label_map, dry_run, meeting_date="",
                         zrodlo_info=None, team_id=None, klient="", source=None):
    aktualizacje = wynik.get("aktualizacje_spraw", [])
    if not aktualizacje:
        return 0

    otwarte = karta.get("otwarte_sprawy", {})
    source = source or wynik.get("zrodlo", "")
    zrodlo_info = zrodlo_info or ustal_zrodlo(source, wynik, karta)
    processed = 0

    for upd in aktualizacje:
        klucz = upd.get("klucz_sprawy", "")
        nowy_status = upd.get("nowy_status", "")
        cytat = upd.get("cytat", "")
        uzasadnienie = upd.get("uzasadnienie", "")

        # Zakaz (nie ma w otwarte_sprawy, jest w karta.zakazy)
        is_zakaz = any(z.get("id") == klucz for z in karta.get("zakazy", []))
        uchyla_zakaz = is_zakaz and nowy_status == "anulowana"
        ok, powod = sprawdz_uprawnienia(karta, upd, zrodlo_info,
                                        zakaz_id=klucz if uchyla_zakaz else None, klucz=klucz)
        if not ok:
            odrzuc_aktualizacje(api_key, karta, upd, source, powod, otwarte.get(klucz), uchyla_zakaz,
                                label_map, state_ids, team_id, klient, dry_run)
            continue
        if uchyla_zakaz:
            if dry_run:
                print(f"  [aktualizacja-zakaz] {klucz} → uchylony")
            else:
                zakazy = karta.get("zakazy", [])
                zakaz_obj = next((z for z in zakazy if z.get("id") == klucz), None)
                if zakaz_obj:
                    karta["zakazy"] = [z for z in zakazy if z.get("id") != klucz]
                    karta.setdefault("historia_zakazow", []).append({
                        **zakaz_obj,
                        "uchylony": cytat,
                        "kiedy": wynik.get("wygenerowano", ""),
                    })
                    print(f"  ✓ Zakaz {klucz} przeniesiony do historii")
            processed += 1
            continue

        if klucz not in otwarte:
            continue

        issue_info = otwarte[klucz]
        if not isinstance(issue_info, dict):
            continue
        linear_id = issue_info.get("linear_id", "")
        identifier = issue_info.get("identifier", klucz)

        # Ponowna analiza rozmowy nie może aktualizować spraw, które sama utworzyła.
        # Aktualizacja wymaga rozmowy PÓŹNIEJSZEJ niż ta, z której sprawa POCHODZI (pierwsze
        # źródło). Późniejsza wzmianka w komentarzu (kolejne źródła) nie blokuje aktualizacji.
        issue_sources = issue_info.get("zrodla", [])
        origin = issue_sources[0] if issue_sources else ""
        if origin and source == origin:
            print(f"  [pominięto aktualizację] {identifier} ({klucz}): ta sama rozmowa ({source})")
            continue
        issue_date = issue_info.get("data_spotkania", "") or _date_from_path(origin)
        if issue_date and meeting_date and meeting_date <= issue_date:
            print(f"  [pominięto aktualizację] {identifier} ({klucz}): "
                  f"data rozmowy {meeting_date} nie jest późniejsza niż data sprawy {issue_date}")
            continue
        if source in issue_info.get("aktualizacje_zrodla", []):
            print(f"  [pominięto aktualizację] {identifier} ({klucz}): już zastosowana z tej rozmowy")
            continue

        if dry_run:
            print(f"  [aktualizacja] {klucz} ({identifier}) → {nowy_status}")
            processed += 1
            continue

        # Update state
        new_state_id = state_ids.get(nowy_status)
        update_input = {}
        if new_state_id:
            update_input["stateId"] = new_state_id

        # For zrob_teraz: remove "Czeka na klienta" label
        if nowy_status == "zrob_teraz":
            stan = get_issue_state_and_labels(api_key, linear_id)
            current_labels = stan["labels"]
            czeka_id = label_map.get("Czeka na klienta")
            if stan["type"] == "unstarted" and czeka_id not in [l["id"] for l in current_labels]:
                # zgłoszenie już jest wznowione (np. wcześniejszy przebieg): bez dubla komentarza
                issue_info.setdefault("aktualizacje_zrodla", []).append(source)
                print(f"  = {identifier} ({klucz}) → {nowy_status} (już w tym stanie, bez zmian)")
                continue
            new_ids = [l["id"] for l in current_labels if l["id"] != czeka_id]
            if new_ids != [l["id"] for l in current_labels]:
                update_input["labelIds"] = new_ids

        if update_input:
            gql(api_key, M_UPDATE_ISSUE, {"id": linear_id, "input": update_input})

        # Add comment with quote
        comment_parts = [f"**Status → {nowy_status}**"]
        if cytat:
            comment_parts.append(f"\n> {cytat}")
        if uzasadnienie:
            comment_parts.append(f"\n{uzasadnienie}")
        gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": "\n".join(comment_parts)})

        if nowy_status == "zrob_teraz" and issue_info.get("po_wznowieniu"):
            pw = issue_info["po_wznowieniu"]
            Z = zasady.wczytaj_zasady()
            nazwa = {"agent": "agent", "czlowiek": "czlowiek", "weryfikacja": "weryfikacja"}.get(pw.get("komu"))
            if nazwa:
                dodaj_etykiete(api_key, linear_id, label_map, Z["etykiety"][nazwa])
            kom = komentarz_przypisania(pw.get("komu"), pw.get("powody", []), pw.get("wymaga_szkicu", False))
            if kom:
                gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": kom})
            issue_info["przypisanie"] = {"komu": pw.get("komu"), "powody": pw.get("powody", [])}

        # Update karta
        issue_info.setdefault("aktualizacje_zrodla", []).append(source)
        if nowy_status in ("zamknieta", "anulowana"):
            karta.setdefault("zamkniete_sprawy", {})[klucz] = {
                **issue_info, "status_koncowy": nowy_status,
            }
            del otwarte[klucz]

        print(f"  ✓ {identifier} ({klucz}) → {nowy_status}")
        processed += 1

    return processed


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Synchronizuje wynik.json z Linear (team RIN).")
    parser.add_argument("wynik", help="Ścieżka do wynik.json")
    parser.add_argument("--klient", required=True, help="Slug klienta, np. auto-tama")
    parser.add_argument("--zrodlo", help="Ścieżka źródła (transkrypcja albo mail) przekazana przez "
                                         "przetworz.py; ma pierwszeństwo przed polem zrodlo z wynik.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Podgląd operacji bez wysyłania niczego do Linear")
    args = parser.parse_args()

    wynik_path = Path(args.wynik)
    if not wynik_path.exists():
        sys.exit(f"Błąd: plik nie istnieje: {args.wynik}")

    wynik = json.loads(wynik_path.read_text(encoding="utf-8"))
    klient = args.klient
    source = args.zrodlo or wynik.get("zrodlo", str(wynik_path))
    today = wynik.get("wygenerowano", str(date.today()))

    karta = load_karta(klient)
    prosby = load_prosby()
    Z = zasady.wczytaj_zasady()
    # autor i data źródła: dla maila z pliku maila (data maila = data źródła dla reguły „późniejsze źródło”)
    zrodlo_info = ustal_zrodlo(source, wynik, karta)
    meeting_date = zrodlo_info["data"]

    print(f"\n{'='*60}")
    mode = "DRY-RUN" if args.dry_run else "SYNCHRONIZACJA"
    print(f"{mode}: {args.wynik}  →  Linear [{TEAM_KEY}]  (klient: {klient})")
    print(f"{'='*60}\n")

    api_key = None
    team_id = None
    label_map = {}
    todo_id = None
    backlog_id = None
    done_id = None
    cancelled_id = None

    if not args.dry_run:
        api_key = load_api_key()
        team = get_team(api_key)
        team_id = team["id"]
        print(f"Zespół: {team['name']} ({team['key']})\n")

        print("Etykiety:")
        label_map = ensure_labels(api_key, team_id)
        print()

        states = get_workflow_states(api_key, team_id)
        todo_id = find_state(states, "Todo", "unstarted")
        backlog_id = find_state(states, "Backlog", "backlog")
        done_id = find_state(states, "Done", "completed")
        cancelled_id = find_state(states, "Cancelled", "cancelled")
        if not todo_id or not backlog_id:
            sys.exit(f"Błąd: nie znaleziono stanów Todo/Backlog w zespole {TEAM_KEY}.")
        print(f"Stany: Todo / Backlog / Done / Cancelled gotowe\n")

    state_ids = {
        "backlog": backlog_id,
        "zrob_teraz": todo_id,
        "zamknieta": done_id,
        "anulowana": cancelled_id,
    }

    # ── sekcja 4: zakazy → karta.json ────────────────────────────────────────

    pozycje = wynik.get("pozycje", [])
    nowe_zakazy = [p for p in pozycje if p.get("sekcja") == 4]
    dodano_zakazow = dodaj_zakazy(karta, nowe_zakazy, source, dry_run=args.dry_run)

    zakazy_klienta = zakazy_czas.aktywne_zakazy(karta, None, klient)       # wygasłe zakazy nie blokują nowych spraw

    # ── aktualizacje otwartych spraw ──────────────────────────────────────────

    if args.dry_run:
        n_upd = process_aktualizacje(
            None, wynik, karta, state_ids, label_map, dry_run=True, meeting_date=meeting_date,
            zrodlo_info=zrodlo_info, klient=klient, source=source
        )
    else:
        n_upd = process_aktualizacje(
            api_key, wynik, karta, state_ids, label_map, dry_run=False, meeting_date=meeting_date,
            zrodlo_info=zrodlo_info, team_id=team_id, klient=klient, source=source
        )

    if wynik.get("aktualizacje_spraw") or dodano_zakazow:
        print()

    # ── pozycje 1–3 i 5 → Linear ─────────────────────────────────────────────

    stats = {"utworzono": 0, "zaktualizowano": 0, "pominieto": 0}
    do_linear = [p for p in pozycje if p.get("sekcja") != 4]

    for item in do_linear:
        sekcja = item.get("sekcja")
        iid = item.get("id", "?")
        klucz = item.get("klucz_sprawy") or f"{klient}:{iid}"
        tytul = f"[{klient}] {item['tytul']}"
        termin = parse_due_date(item.get("termin"))
        blocked_by_ban = item.get("konflikt_z_zakazem")

        # Etykiety i przypisanie wg ops/zasady.json (domyślnie agent, człowiek tylko wg reguł)
        wielu = sekcja == 3 and zasady.wielu_klientow(prosby, Z, item, klient)
        label_names = zasady.etykiety_pozycji(item, Z, karta, wielu)
        etykieta_repo = zasady.etykieta_repo(item, Z)
        if etykieta_repo:
            label_names.append(etykieta_repo)          # repo, w którym agent ma wykonać zgłoszenie
        przyp = zasady.przypisz(item, Z, karta, wielu)
        priority = None
        if sekcja == 1:
            state_name = "Backlog" if blocked_by_ban else "Todo"
        elif sekcja in (2, 3):
            state_name = "Backlog"
        elif sekcja == 5:
            state_name = "Todo"
            priority = 2  # High
        else:
            stats["pominieto"] += 1
            continue

        otwarte = karta.get("otwarte_sprawy", {})

        # ── idempotencja ──────────────────────────────────────────────────────
        if klucz in otwarte:
            existing = otwarte[klucz]
            existing_sources = existing.get("zrodla", []) if isinstance(existing, dict) else []
            if source in existing_sources:
                # Ta sama rozmowa – bez nowego komentarza, ale uzgodnij stan (idempotentnie)
                if not args.dry_run:
                    uzgodnij_istniejace(api_key, karta, existing, klucz, item, sekcja,
                                        label_map, termin, meeting_date, source, today)
                stats["pominieto"] += 1
                continue
            # Inna rozmowa – dodaj komentarz z nowym cytatem
            if args.dry_run:
                ident = existing.get("identifier", klucz) if isinstance(existing, dict) else klucz
                print(f"  [komentarz] {klucz} ({ident}) – nowa rozmowa")
            else:
                linear_id = existing.get("linear_id") if isinstance(existing, dict) else existing
                ident = existing.get("identifier", klucz) if isinstance(existing, dict) else klucz
                first_quote = item.get("cytat", [""])[0] if item.get("cytat") else ""
                body = f"Ponownie wspomniane w rozmowie `{source}`"
                if first_quote:
                    body += f"\n\n> {first_quote}"
                gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": body})
                if isinstance(existing, dict):
                    existing.setdefault("zrodla", []).append(source)
                print(f"  ✓ Komentarz → {ident} ({klucz})")
                uzgodnij_istniejace(api_key, karta, existing, klucz, item, sekcja,
                                    label_map, termin, meeting_date, source, today)
            stats["zaktualizowano"] += 1
            continue

        # ── ryzyka: licznik ───────────────────────────────────────────────────
        risk_escalate = False
        if sekcja == 5 and not args.dry_run:
            risk_escalate, n_risk_src = update_risk_counter(karta, item, source, today)
            if risk_escalate:
                label_names.append("Powtarzające się ryzyko")
                priority = 1  # Urgent

        # ── prośby produktowe: licznik ────────────────────────────────────────
        product_escalate = False
        if sekcja == 3 and not args.dry_run:
            product_escalate, _ = update_prosby(prosby, item, klient, source, today)

        desc = build_description(item, source, karta, przyp, Z)

        # ── dry-run ───────────────────────────────────────────────────────────
        if args.dry_run:
            labels_str = ", ".join(label_names)
            prio_str = " · priorytet: Urgent" if priority == 1 else (" · priorytet: High" if priority == 2 else "")
            termin_str = f" · termin: {termin}" if termin else ""
            blocked_str = f" · ⛔ ZAKAZ {blocked_by_ban.get('zakaz', '')}" if blocked_by_ban else ""
            print(f"  [utwórz] {klucz}")
            print(f"    Tytuł:    {tytul}")
            print(f"    Stan:     {state_name}  ·  etykiety: {labels_str}{prio_str}{termin_str}{blocked_str}")
            snippet = desc[:100].replace("\n", " ")
            print(f"    Opis:     {snippet}…")
            print()
            stats["utworzono"] += 1
            continue

        # ── tworzenie zgłoszenia ──────────────────────────────────────────────
        state_id = todo_id if state_name == "Todo" else backlog_id
        label_ids = [label_map[n] for n in label_names if n in label_map]
        issue_input = {
            "teamId": team_id,
            "title": tytul,
            "description": desc,
            "stateId": state_id,
            "labelIds": label_ids,
        }
        if priority is not None:
            issue_input["priority"] = priority
        if termin:
            issue_input["dueDate"] = termin

        result = gql(api_key, M_CREATE_ISSUE, {"input": issue_input})
        issue = result.get("issueCreate", {}).get("issue")
        if not issue:
            print(f"  ⚠ Nie udało się utworzyć: {klucz}")
            stats["pominieto"] += 1
            continue

        linear_id = issue["id"]
        identifier = issue["identifier"]
        url = issue["url"]

        karta.setdefault("otwarte_sprawy", {})[klucz] = {
            "linear_id": linear_id,
            "identifier": identifier,
            "url": url,
            "tytul": item["tytul"],
            "zrodla": [source],
            "data_spotkania": meeting_date,
        }
        zapisz_przypisanie(karta["otwarte_sprawy"][klucz], item, Z, karta, wielu)
        if sekcja == 1 or sekcja == 3:
            kom = komentarz_przypisania(przyp["komu"], zasady.powody_tekst(przyp), przyp["wymaga_szkicu"])
            if kom:
                gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": kom})

        print(f"  ✓ {identifier} ({klucz}): {tytul[:50]}")

        # Komentarz o blokadzie zakazu
        if blocked_by_ban:
            ban_id = blocked_by_ban.get("zakaz", "")
            uzasadnienie = blocked_by_ban.get("uzasadnienie", "")
            ban_obj = next((z for z in zakazy_klienta if z.get("id") == ban_id), None)
            ban_text = ban_obj["cytat"][0] if ban_obj and ban_obj.get("cytat") else ""
            body = f"**⛔ Zablokowane przez zakaz {ban_id}**\n\n{uzasadnienie}"
            if ban_text:
                body += f"\n\n**Treść zakazu:** _{ban_text}_"
            gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": body})

        if risk_escalate:
            print(f"  ↑ Powtarzające się ryzyko: {identifier} ({klucz}) | {item['tytul']}")
        if product_escalate:
            print(f"  ★ Wielu klientów: {identifier} ({klucz}) | {item['tytul']}")

        # Komentarz o powtarzającym się ryzyku
        if risk_escalate:
            temat = item.get("temat_ryzyka", "inne")
            body = build_risk_history(karta, temat)
            gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": body})

        # Komentarz o wielu klientach
        if product_escalate:
            klucz_f = item.get("klucz_funkcji")
            if klucz_f:
                body = build_clients_comment(prosby, klucz_f)
                gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": body})

        stats["utworzono"] += 1

    # jedna notatka przed spotkaniem (albo na klienta) ze wszystkimi ryzykami i otwartymi tematami
    # zamiast osobnego zadania na każde ryzyko; dawne zadania na ryzyka są scalane (patrz notatki.py)
    import copy
    najnowsze = notatki.najnowsze_pozycje(klient)
    for zdarzenie in notatki.synchronizuj_notatki(
            sys.modules[__name__], api_key, team_id, karta if not args.dry_run else copy.deepcopy(karta),
            klient, najnowsze, Z, label_map, todo_id, state_ids, source, meeting_date, date.today(),
            dry_run=args.dry_run):
        print(f"  [notatki] {zdarzenie}" if args.dry_run else f"  {zdarzenie}")

    if not args.dry_run:
        save_karta(klient, karta)
        write_karta_md(klient, karta)
        save_prosby(prosby)

    print(f"\n{'─'*60}")
    print(f"Podsumowanie:")
    print(f"  Utworzono zgłoszeń:            {stats['utworzono']}")
    print(f"  Zaktualizowano (komentarz):    {stats['zaktualizowano']}")
    print(f"  Pominięto (ta sama rozmowa):   {stats['pominieto']}")
    print(f"  Zakazy → karta.json:           {dodano_zakazow}")
    print(f"  Aktualizacje otwartych spraw:  {n_upd}")
    print(f"{'─'*60}\n")
    if not args.dry_run:
        import stan_linear
        stan_linear.po_przebiegu()          # strony generują się z pliku stanu, bez zapytań do Lineara


if __name__ == "__main__":
    main()
