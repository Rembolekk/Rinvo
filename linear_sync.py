#!/usr/bin/env python3
"""
linear_sync.py – wysyła wynik.json do Linear (team RIN).
Tylko biblioteka standardowa Pythona (urllib, json, os, sys, time, argparse, pathlib).

Użycie:
  python linear_sync.py wyniki/transkrypcja-spotkanie/wynik.json --klient auto-tama
  python linear_sync.py wyniki/transkrypcja-spotkanie/wynik.json --klient auto-tama --dry-run
"""

import json
import os
import ssl
import sys
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date

TEAM_KEY = "RIN"
LINEAR_API = "https://api.linear.app/graphql"

REQUIRED_LABELS = [
    "Błąd", "Konfiguracja", "Finanse", "Zadanie", "Produkt",
    "Czeka na klienta", "Ryzyko", "Dla agenta", "Do weryfikacji",
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
}

# typ z wynik.json → etykieta Linear
TYP_DO_ETYKIETY = {
    "bug": "Błąd",
    "zmiana_konfiguracji": "Konfiguracja",
    "poprawka_bazy_wiedzy": "Konfiguracja",
    "finanse": "Finanse",
}

# te typy dostają dodatkowo etykietę "Dla agenta"
TYPY_DLA_AGENTA = {"bug", "zmiana_konfiguracji", "poprawka_bazy_wiedzy"}


# ── klucz API ────────────────────────────────────────────────────────────────

def load_api_key():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("LINEAR_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return key
    key = os.environ.get("LINEAR_API_KEY", "")
    if key:
        return key
    sys.exit("Błąd: brak LINEAR_API_KEY w .env ani w środowisku.")


# ── HTTP / GraphQL ────────────────────────────────────────────────────────────

def _ssl_context():
    ctx = ssl.create_default_context()
    ca_candidates = [
        "/etc/ssl/cert.pem",
        "/usr/local/etc/openssl/cert.pem",
        "/opt/homebrew/etc/openssl@3/cert.pem",
    ]
    for ca in ca_candidates:
        if os.path.exists(ca):
            try:
                ctx.load_verify_locations(ca)
                return ctx
            except ssl.SSLError:
                continue
    return ctx


_SSL_CTX = _ssl_context()


def gql(api_key, query, variables=None, retries=3, delay=2):
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API,
        data=payload,
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
    return """
query {
  issueLabels(filter: { team: { id: { eq: \"""" + team_id + """\" } } }) {
    nodes { id name }
  }
}
"""


def Q_STATES(team_id):
    return """
query {
  workflowStates(filter: { team: { id: { eq: \"""" + team_id + """\" } } }) {
    nodes { id name type }
  }
}
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
            result = gql(api_key, M_CREATE_LABEL, {"teamId": team_id, "name": name, "color": color})
            lc = result.get("issueLabelCreate", {})
            if lc.get("success"):
                new_id = lc["issueLabel"]["id"]
                existing[name] = new_id
                print(f"  ✓ Utworzono etykietę: {name!r}")
            else:
                print(f"  ⚠ Nie udało się utworzyć etykiety: {name!r}")
    return existing


def get_workflow_states(api_key, team_id):
    data = gql(api_key, Q_STATES(team_id))
    return data.get("workflowStates", {}).get("nodes", [])


def find_state(states, preferred_name, fallback_type):
    for s in states:
        if s["name"].lower() == preferred_name.lower():
            return s["id"]
    for s in states:
        if s.get("type") == fallback_type:
            return s["id"]
    return None


# ── karta.json / karta.md ─────────────────────────────────────────────────────

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

    zakazy = karta.get("zakazy", [])
    if zakazy:
        lines.append("## Zakazy i ograniczenia\n")
        for z in zakazy:
            lines.append(f"### {z['id']}: {z['tytul']}\n")
            if z.get("opis"):
                lines.append(f"{z['opis']}\n")
            for c in z.get("cytat", []):
                lines.append(f"> {c}\n")
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

    path = Path("ops") / "klienci" / klient / "karta.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ karta.md: {path}")


# ── budowanie opisu zgłoszenia ────────────────────────────────────────────────

def build_description(item, source_path, zakazy):
    parts = []

    if item.get("opis"):
        parts.append(f"## Opis\n\n{item['opis']}")

    meta = []
    if item.get("wlasciciel"):
        meta.append(f"**Właściciel:** {item['wlasciciel']}")
    warunek = item.get("warunek", "brak")
    if warunek and warunek != "brak":
        meta.append(f"**Warunek:** {warunek}")
    if meta:
        parts.append("\n".join(meta))

    cytaty = item.get("cytat", [])
    if cytaty:
        block = "\n".join(f"> {c}" for c in cytaty)
        parts.append(f"## Cytaty z rozmowy\n\n{block}")

    wnioski = item.get("wnioski", [])
    if wnioski:
        block = "\n".join(f"- **[wniosek]** {w}" for w in wnioski)
        parts.append(f"## Wnioski\n\n{block}")

    p = item.get("przypomnienie", {})
    if p:
        r_parts = []
        if p.get("data") and str(p["data"]) not in ("nie ustalono",):
            r_parts.append(f"data: {p['data']}")
        if p.get("limit") is not None and str(p["limit"]) not in ("nie ustalono",):
            r_parts.append(f"limit przypomnień: {p['limit']}")
        if p.get("uwagi"):
            r_parts.append(p["uwagi"])
        if r_parts:
            parts.append(f"**Przypomnienie:** {' · '.join(r_parts)}")

    parts.append(f"## Źródło\n\n`{source_path}`")

    if zakazy:
        rows = "\n".join(
            "- **{id} {tytul}**{cytat}".format(
                id=z["id"],
                tytul=z["tytul"],
                cytat=f" — _{z['cytat'][0]}_" if z.get("cytat") else "",
            )
            for z in zakazy
        )
        parts.append(f"---\n\n## Zakazy klienta\n\n{rows}")

    return "\n\n".join(parts)


def parse_due_date(termin):
    if not termin or str(termin) in ("brak", "nie ustalono", ""):
        return None
    try:
        date.fromisoformat(str(termin))
        return str(termin)
    except ValueError:
        return None


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Synchronizuje wynik.json z Linear (team RIN)."
    )
    parser.add_argument("wynik", help="Ścieżka do wynik.json")
    parser.add_argument("--klient", required=True, help="Slug klienta, np. auto-tama")
    parser.add_argument("--dry-run", action="store_true",
                        help="Podgląd operacji bez wysyłania niczego do Linear")
    args = parser.parse_args()

    wynik_path = Path(args.wynik)
    if not wynik_path.exists():
        sys.exit(f"Błąd: plik nie istnieje: {args.wynik}")

    wynik = json.loads(wynik_path.read_text(encoding="utf-8"))
    klient = args.klient
    source = wynik.get("zrodlo", str(wynik_path))

    karta = load_karta(klient)

    print(f"\n{'='*60}")
    mode = "DRY-RUN" if args.dry_run else "SYNCHRONIZACJA"
    print(f"{mode}: {args.wynik}  →  Linear [{TEAM_KEY}]  (klient: {klient})")
    print(f"{'='*60}\n")

    api_key = None
    team_id = None
    label_map = {}
    todo_id = None
    backlog_id = None

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
        if not todo_id or not backlog_id:
            sys.exit(f"Błąd: nie znaleziono stanów Todo/Backlog w zespole {TEAM_KEY}.")
        print(f"Stany: Todo i Backlog gotowe\n")

    # ── sekcja 4: zakazy → karta.json, bez zgłoszeń Linear ───────────────────

    pozycje = wynik.get("pozycje", [])
    nowe_zakazy = [p for p in pozycje if p.get("sekcja") == 4]
    istniejace_ids = {z["id"] for z in karta.get("zakazy", [])}
    dodano_zakazow = 0
    for z in nowe_zakazy:
        if z["id"] not in istniejace_ids:
            karta.setdefault("zakazy", []).append({
                "id": z["id"],
                "tytul": z["tytul"],
                "opis": z.get("opis", ""),
                "cytat": z.get("cytat", []),
                "wlasciciel": z.get("wlasciciel", ""),
            })
            dodano_zakazow += 1
            if args.dry_run:
                print(f"  [zakaz → karta.json] {z['id']}: {z['tytul']}")

    zakazy_klienta = karta.get("zakazy", [])

    # ── pozostałe sekcje → Linear ─────────────────────────────────────────────

    stats = {"utworzono": 0, "zaktualizowano": 0, "pominieto": 0}
    do_linear = [p for p in pozycje if p.get("sekcja") != 4]

    if args.dry_run:
        print()

    for item in do_linear:
        sekcja = item.get("sekcja")
        iid = item["id"]
        klucz = f"{klient}:{iid}"
        tytul = f"[{klient}] {item['tytul']}"
        termin = parse_due_date(item.get("termin"))

        if sekcja == 1:
            state_name = "Todo"
            typ = item.get("typ", "")
            label_names = [TYP_DO_ETYKIETY.get(typ, "Zadanie")]
            if typ in TYPY_DLA_AGENTA:
                label_names.append("Dla agenta")
            priority = None
        elif sekcja == 2:
            state_name = "Backlog"
            label_names = ["Czeka na klienta"]
            priority = None
        elif sekcja == 3:
            state_name = "Backlog"
            label_names = ["Produkt"]
            priority = None
        elif sekcja == 5:
            state_name = "Todo"
            label_names = ["Ryzyko"]
            priority = 2  # High
        else:
            stats["pominieto"] += 1
            continue

        otwarte = karta.get("otwarte_sprawy", {})

        # idempotencja
        if klucz in otwarte:
            if args.dry_run:
                existing = otwarte[klucz]
                ident = existing.get("identifier", klucz) if isinstance(existing, dict) else klucz
                print(f"  [komentarz] {klucz}  →  {ident} (już istnieje)")
            else:
                existing = otwarte[klucz]
                linear_id = existing.get("linear_id") if isinstance(existing, dict) else existing
                body = f"Ponownie wspomniane w rozmowie `{source}`"
                gql(api_key, M_ADD_COMMENT, {"issueId": linear_id, "body": body})
                ident = existing.get("identifier", klucz) if isinstance(existing, dict) else klucz
                print(f"  ✓ Komentarz → {ident} ({klucz})")
            stats["zaktualizowano"] += 1
            continue

        desc = build_description(item, source, zakazy_klienta)

        if args.dry_run:
            labels_str = ", ".join(label_names)
            prio_str = " · priorytet: High" if priority else ""
            termin_str = f" · termin: {termin}" if termin else ""
            print(f"  [utwórz] {klucz}")
            print(f"    Tytuł:    {tytul}")
            print(f"    Stan:     {state_name}  ·  etykiety: {labels_str}{prio_str}{termin_str}")
            snippet = desc[:120].replace("\n", " ")
            print(f"    Opis:     {snippet}…")
            print()
        else:
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

            karta.setdefault("otwarte_sprawy", {})[klucz] = {
                "linear_id": issue["id"],
                "identifier": issue["identifier"],
                "url": issue["url"],
                "tytul": item["tytul"],
            }
            print(f"  ✓ {issue['identifier']} ({klucz}): {tytul[:55]}")

        stats["utworzono"] += 1

    if not args.dry_run:
        save_karta(klient, karta)
        write_karta_md(klient, karta)

    print(f"\n{'─'*60}")
    print(f"Podsumowanie:")
    print(f"  Utworzono zgłoszeń:          {stats['utworzono']}")
    print(f"  Zaktualizowano (komentarz):  {stats['zaktualizowano']}")
    print(f"  Pominięto:                   {stats['pominieto']}")
    print(f"  Zakazy dodane do karta.json: {dodano_zakazow}")
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
