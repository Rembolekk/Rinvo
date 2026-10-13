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
import ssl
import sys
import time
import argparse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

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
            line = line.strip()
            if line.startswith("LINEAR_API_KEY="):
                key = line.split("=", 1)[1].strip()
                if key:
                    return key
    key = os.environ.get("LINEAR_API_KEY", "")
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


def find_state(states, preferred_name, fallback_type):
    for s in states:
        if s["name"].lower() == preferred_name.lower():
            return s["id"]
    for s in states:
        if s.get("type") == fallback_type:
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

    for z in karta.get("zakazy", []):
        pass  # zakazy section below
    if karta.get("zakazy"):
        lines.append("## Zakazy i ograniczenia\n")
        for z in karta["zakazy"]:
            lines.append(f"### {z['id']}: {z['tytul']}\n")
            if z.get("opis"):
                lines.append(f"{z['opis']}\n")
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

def should_get_agent_label(item):
    if item.get("konflikt_z_zakazem"):
        return False
    if item.get("pewnosc") == "niska":
        return False
    if item.get("rodzaj") == "nowa_funkcja":
        return False
    return item.get("typ") in TYPY_DLA_AGENTA


def get_issue_labels_from_linear(api_key, issue_id):
    data = gql(api_key, Q_ISSUE_LABELS(issue_id))
    return data.get("issue", {}).get("labels", {}).get("nodes", [])


# ── budowanie opisu ───────────────────────────────────────────────────────────

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
    if item.get("pewnosc") == "niska":
        meta.append("**⚠ Pewność: niska** — wymaga weryfikacji przed działaniem")
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
            r_parts.append(f"limit: {p['limit']}")
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


# ── ryzyka i prośby produktowe ────────────────────────────────────────────────

def update_risk_counter(karta, item, source, today):
    temat = item.get("temat_ryzyka", "inne")
    ryzyka = karta.setdefault("ryzyka", {})
    if temat not in ryzyka:
        ryzyka[temat] = []
    ryzyka[temat].append({
        "data": today,
        "zrodlo": source,
        "cytat": item.get("cytat", [""])[0] if item.get("cytat") else "",
    })
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
        "data": today,
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


# ── aktualizacje otwartych spraw ──────────────────────────────────────────────

def process_aktualizacje(api_key, wynik, karta, state_ids, label_map, dry_run):
    aktualizacje = wynik.get("aktualizacje_spraw", [])
    if not aktualizacje:
        return 0

    otwarte = karta.get("otwarte_sprawy", {})
    source = wynik.get("zrodlo", "")
    processed = 0

    for upd in aktualizacje:
        klucz = upd.get("klucz_sprawy", "")
        nowy_status = upd.get("nowy_status", "")
        cytat = upd.get("cytat", "")
        uzasadnienie = upd.get("uzasadnienie", "")

        # Zakaz (nie ma w otwarte_sprawy, jest w karta.zakazy)
        is_zakaz = any(z.get("id") == klucz for z in karta.get("zakazy", []))
        if is_zakaz and nowy_status == "anulowana":
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
            current_labels = get_issue_labels_from_linear(api_key, linear_id)
            czeka_id = label_map.get("Czeka na klienta")
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

        # Update karta
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
    parser.add_argument("--dry-run", action="store_true",
                        help="Podgląd operacji bez wysyłania niczego do Linear")
    args = parser.parse_args()

    wynik_path = Path(args.wynik)
    if not wynik_path.exists():
        sys.exit(f"Błąd: plik nie istnieje: {args.wynik}")

    wynik = json.loads(wynik_path.read_text(encoding="utf-8"))
    klient = args.klient
    source = wynik.get("zrodlo", str(wynik_path))
    today = wynik.get("wygenerowano", str(date.today()))

    karta = load_karta(klient)
    prosby = load_prosby()

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
        "zrob_teraz": todo_id,
        "zamknieta": done_id,
        "anulowana": cancelled_id,
    }

    # ── sekcja 4: zakazy → karta.json ────────────────────────────────────────

    pozycje = wynik.get("pozycje", [])
    nowe_zakazy = [p for p in pozycje if p.get("sekcja") == 4]
    istniejace_ids = {z.get("id") for z in karta.get("zakazy", [])}
    dodano_zakazow = 0
    for z in nowe_zakazy:
        if z.get("id") not in istniejace_ids:
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

    # ── aktualizacje otwartych spraw ──────────────────────────────────────────

    if args.dry_run:
        aktualizacje_dry = wynik.get("aktualizacje_spraw", [])
        for upd in aktualizacje_dry:
            print(f"  [aktualizacja] {upd.get('klucz_sprawy')} → {upd.get('nowy_status')}")
        n_upd = len(aktualizacje_dry)
    else:
        n_upd = process_aktualizacje(
            api_key, wynik, karta, state_ids, label_map, dry_run=False
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

        # Klasyfikacja sekcji
        if sekcja == 1:
            if blocked_by_ban:
                state_name = "Backlog"
            else:
                state_name = "Todo"
            typ = item.get("typ", "")
            base_label = TYP_DO_ETYKIETY.get(typ, "Zadanie")
            label_names = [base_label]
            if blocked_by_ban:
                label_names.append("Zablokowane przez zakaz")
            elif should_get_agent_label(item):
                label_names.append("Dla agenta")
            if item.get("pewnosc") == "niska":
                label_names.append("Do weryfikacji")
            priority = None
        elif sekcja == 2:
            state_name = "Backlog"
            label_names = ["Czeka na klienta"]
            if item.get("pewnosc") == "niska":
                label_names.append("Do weryfikacji")
            priority = None
        elif sekcja == 3:
            state_name = "Backlog"
            label_names = ["Produkt"]
            if item.get("pewnosc") == "niska":
                label_names.append("Do weryfikacji")
            priority = None
        elif sekcja == 5:
            state_name = "Todo"
            label_names = ["Ryzyko"]
            if item.get("pewnosc") == "niska":
                label_names.append("Do weryfikacji")
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
                # Ta sama rozmowa – pomiń po cichu
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
            if product_escalate:
                label_names.append("Wielu klientów")

        desc = build_description(item, source, zakazy_klienta)

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
        }

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


if __name__ == "__main__":
    main()
