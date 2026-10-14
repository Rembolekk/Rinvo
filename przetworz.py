#!/usr/bin/env python3
"""przetworz.py – automat przetwarzania transkrypcji od początku do końca.

Użycie:
  python3 przetworz.py ops/transkrypcje/<klient>/<plik>.md      # transkrypcja rozmowy
  python3 przetworz.py ops/maile/<klient>/<plik>.md             # mail zapisany przez maile.py
  python3 przetworz.py ops/transkrypcje/<klient>/<plik>.md --wymus
  python3 przetworz.py --test-slack

Kroki:
  a) Wyznacz klienta ze ścieżki (ops/transkrypcje/<klient>/...)
  b) Sprawdź rejestr sha256 transkrypcji — pomiń jeśli już przetworzona (--wymus pomija)
  c) Zablokuj plik lock (zapobiega równoległym przebiegom)
  d) Uruchom claude --print z instrukcją analizuj.md (do 30 min)
  e) Uruchom render.py → daty.py → linear_sync.py
  f) Wyślij podsumowanie do Slack (SLACK_WEBHOOK_URL z .env) — zawsze, niezależnie od liczby nowych zgłoszeń
  g) Zarejestruj sha256 transkrypcji tylko po pełnym sukcesie

Klucze API czytane z .env — nigdy nie są logowane ani drukowane.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from maile import czy_mail, wczytaj_meta_maila
from sekrety import NAZWY_SEKRETOW, czysc, wyczysc_srodowisko


# ── .env ─────────────────────────────────────────────────────────────────────

def load_env():
    """Czyta .env (setdefault: zmienne środowiskowe mają pierwszeństwo).
    Bez pliku .env (np. GitHub Actions) klucze pochodzą ze środowiska."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key = czysc(key)  # BOM i niewidoczne znaki z edytorów (Notatki)
            val = czysc(val) if key in NAZWY_SEKRETOW else val.strip()
            os.environ.setdefault(key, val)


# ── rejestr ───────────────────────────────────────────────────────────────────

REGISTRY_PATH = Path("ops/.przetworzone.json")

DEFAULT_MODEL = "claude-sonnet-5-5"


def transcript_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_registry():
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(reg):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── klient ────────────────────────────────────────────────────────────────────

def extract_klient(transkrypcja):
    """Klient ze ścieżki ops/transkrypcje/<klient>/… albo ops/maile/<klient>/…"""
    parts = Path(transkrypcja).parts
    for i, part in enumerate(parts):
        if part in ("transkrypcje", "maile") and i + 1 < len(parts):
            return parts[i + 1]
    return None


# ── lock ──────────────────────────────────────────────────────────────────────

LOCK_PATH = Path("ops/.przetworz.lock")
LOCK_STALE_SECONDS = 35 * 60  # 35 minut


def acquire_lock():
    if LOCK_PATH.exists():
        try:
            age = time.time() - LOCK_PATH.stat().st_mtime
            if age < LOCK_STALE_SECONDS:
                return False
            LOCK_PATH.unlink()
        except OSError:
            return False
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock():
    try:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()
    except OSError:
        pass


# ── slack ─────────────────────────────────────────────────────────────────────

def send_slack(message, log_path=None):
    """Send Slack message. Returns (ok: bool, error: str|None).
    Logs result to log_path if provided. Never logs the webhook URL."""
    import ssl
    import urllib.request

    webhook = czysc(os.environ.get("SLACK_WEBHOOK_URL", ""))
    if not webhook:
        note = "SLACK_WEBHOOK_URL nie ustawiony w .env — pominięto Slack."
        if log_path:
            _log(log_path, f"Slack: {note}\n")
        return False, note

    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            status = resp.status
        if log_path:
            _log(log_path, f"Slack: wysłano (HTTP {status})\n")
        return True, None
    except Exception as exc:
        err = str(exc)
        if log_path:
            _log(log_path, f"Slack: BŁĄD wysyłki — {err}\n")
        return False, err


def _log(log_path, text):
    try:
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(text)
    except OSError:
        pass


# ── redakcja kluczy i ogon logu ───────────────────────────────────────────────

SECRET_ENV_VARS = NAZWY_SEKRETOW
SECRET_PATTERNS = [
    r"lin_api_\w+",
    r"https://hooks\.slack\.com/\S+",
    r"sk-ant-[\w-]+",
    r"(?i)(bearer\s+)[\w.~+/=-]{12,}",
]


def redact(text):
    """Usuwa z tekstu wartości sekretów (ze środowiska) i typowe wzorce kluczy."""
    for name in SECRET_ENV_VARS:
        val = os.environ.get(name, "")
        if len(val) >= 8:
            text = text.replace(val, "***")
    for pat in SECRET_PATTERNS:
        text = re.sub(pat, lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text


def tail_log(log_path, n=30):
    """Ostatnie n niepustych linii logu, bez kluczy."""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    lines = [ln for ln in lines if ln.strip()]
    return redact("\n".join(lines[-n:]))


# ── subprocesy ────────────────────────────────────────────────────────────────

def run_step(cmd, log_path, step_name, timeout=120):
    """Run a subprocess, append output to log_path. Returns CompletedProcess."""
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write(f"\n{'='*60}\n=== {step_name} ===\n{'='*60}\n")
        lf.write(f"Komenda: {' '.join(str(c) for c in cmd)}\n\n")
        lf.flush()
        result = subprocess.run(
            cmd,
            stdout=lf,
            stderr=lf,
            timeout=timeout,
        )
    return result


# ── Slack: podsumowanie ───────────────────────────────────────────────────────

def slack_bezpiecznie(tekst, limit=120):
    """Tekst z maila/transkrypcji bez znaków sterujących Slacka (<@U…>, <!channel>, linki)."""
    t = re.sub(r"\s+", " ", str(tekst or "")).strip()[:limit]
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _linia_slack(emoji, nazwa, pozycje, limit=5):
    """Linia z licznikiem (także 0) i listą tytułów pod spodem."""
    out = [f"{emoji} {nazwa}: {len(pozycje)}"]
    out += [f"  • {t}" for t in pozycje[:limit]]
    if len(pozycje) > limit:
        out.append(f"  … i {len(pozycje) - limit} więcej")
    return out


def parse_sync_zdarzenia(sync_stdout):
    """Wyciąga z wyjścia linear_sync.py to, co faktycznie zrobiono w tym przebiegu."""
    wynik = {"zamkniete": [], "wznowione": [], "ryzyka": [], "wielu_klientow": [], "odrzucone": []}
    for ln in sync_stdout.splitlines():
        m = re.match(r"\s*✓ (RIN-\d+) \(([^)]+)\) → (\w+)\s*$", ln)
        if m:
            ident, klucz, status = m.groups()
            if status in ("zamknieta", "anulowana"):
                wynik["zamkniete"].append((ident, klucz))
            elif status == "zrob_teraz":
                wynik["wznowione"].append((ident, klucz))
            continue
        m = re.match(r"\s*↑ Powtarzające się ryzyko: (RIN-\d+) \(([^)]+)\) \| (.*)$", ln)
        if m:
            wynik["ryzyka"].append(m.groups())
            continue
        m = re.match(r"\s*★ Wielu klientów: (RIN-\d+) \(([^)]+)\) \| (.*)$", ln)
        if m:
            wynik["wielu_klientow"].append(m.groups())
            continue
        m = re.match(r"\s*⛔ Odrzucono aktualizację: (.+?) → (\w+) \| (.*)$", ln)
        if m:
            wynik["odrzucone"].append(m.groups())
    return wynik


def build_slack_summary(klient, wynik_path, sync_stdout, testy_wynik=None, model=None, meta_maila=None):
    try:
        d = json.loads(wynik_path.read_text(encoding="utf-8"))
    except Exception:
        return f":white_check_mark: *[{klient}]* Przetworzono."

    spotkanie = d.get("spotkanie", {})
    data = spotkanie.get("data", "?")
    pozycje = d.get("pozycje", [])

    s1 = [p for p in pozycje if p.get("sekcja") == 1]
    s2 = [p for p in pozycje if p.get("sekcja") == 2]
    s5 = [p for p in pozycje if p.get("sekcja") == 5]
    blocked = [p for p in pozycje if p.get("konflikt_z_zakazem")]
    niska = [p for p in pozycje if p.get("pewnosc") == "niska"]
    aktualizacje = d.get("aktualizacje_spraw", [])
    ostrzezenia = d.get("ostrzezenia_dat", [])

    nowe = 0
    n_aktualizacji = 0
    pominieto = 0
    for line in sync_stdout.splitlines():
        if "Utworzono zgłoszeń:" in line:
            try:
                nowe = int(line.split(":")[-1].strip())
            except ValueError:
                pass
        elif "Aktualizacje otwartych spraw:" in line:
            try:
                n_aktualizacji = int(line.split(":")[-1].strip())
            except ValueError:
                pass
        elif "Pominięto (ta sama rozmowa):" in line:
            try:
                pominieto = int(line.split(":")[-1].strip())
            except ValueError:
                pass

    # karta klienta: tytuły i linki do spraw, o których mówi sync
    karta = {}
    karta_path = Path("ops") / "klienci" / klient / "karta.json"
    if karta_path.exists():
        try:
            karta = json.loads(karta_path.read_text(encoding="utf-8"))
        except Exception:
            karta = {}
    zdarzenia = parse_sync_zdarzenia(sync_stdout)

    def sprawa(ident, klucz, tytul=""):
        info = (karta.get("otwarte_sprawy", {}).get(klucz)
                or karta.get("zamkniete_sprawy", {}).get(klucz) or {})
        tytul = slack_bezpiecznie(tytul or info.get("tytul", "") or klucz, 70)
        url = info.get("url", "") if isinstance(info, dict) else ""
        etykieta = f"<{url}|{ident}>" if url else ident
        return f"{etykieta} {tytul}"

    zamkniete = [sprawa(i, k) for i, k in zdarzenia["zamkniete"]]
    wznowione = [sprawa(i, k) for i, k in zdarzenia["wznowione"]]
    ryzyka_powt = [sprawa(i, k, t) for i, k, t in zdarzenia["ryzyka"]]
    wielu = [sprawa(i, k, t) for i, k, t in zdarzenia["wielu_klientow"]]
    zablokowane = [f"{p.get('id', '?')} {slack_bezpiecznie(p.get('tytul', ''), 70)}" for p in blocked]
    do_weryfikacji = [f"{p.get('id', '?')} {slack_bezpiecznie(p.get('tytul', ''), 70)}" for p in niska]
    odrzucone = [f"{slack_bezpiecznie(k, 40)} → {st}: {slack_bezpiecznie(pow, 110)}"
                 for k, st, pow in zdarzenia["odrzucone"]]

    if meta_maila is not None:
        # źródłem był mail: Slack mówi to wprost i podaje temat
        lines = [f":email: *[{klient}]* Źródło: mail z {meta_maila.get('data', data)}, "
                 f"temat: „{slack_bezpiecznie(meta_maila.get('temat', '(bez tematu)'))}” przetworzony"]
    else:
        lines = [f":white_check_mark: *[{klient}]* Rozmowa z {data} przetworzona"]
    lines.append(
        f"Zrób teraz: {len(s1)} | Czeka: {len(s2)} | Ryzyka: {len(s5)} | "
        f"Nowe w Linear: {nowe} | Pominięte: {pominieto}"
    )

    # Te linie są zawsze, także gdy wynoszą 0 (brak linii wyglądałby jak brak informacji).
    lines += _linia_slack(":white_check_mark:", "Zamknięte", zamkniete)
    lines += _linia_slack(":arrows_counterclockwise:", "Wznowione", wznowione)
    lines += _linia_slack(":no_entry:", "Zablokowane przez zakaz", zablokowane)
    lines += _linia_slack(":rotating_light:", "Powtarzające się ryzyka", ryzyka_powt)
    lines += _linia_slack(":busts_in_silhouette:", "Wielu klientów", wielu)
    lines += _linia_slack(":warning:", "Do weryfikacji", do_weryfikacji)
    lines += _linia_slack(":no_good:", "Odrzucone (brak uprawnień)", odrzucone)

    if ostrzezenia:
        lines.append(f":clock1: Brak faktów czasowych dla {len(ostrzezenia)} pozycji z cytatami o czasie")
    if model:
        lines.append(f":robot_face: Model analizy: {model}")
    if testy_wynik:
        icon = ":white_check_mark:" if testy_wynik.startswith("PASS") else ":x:"
        lines.append(f"{icon} Testy oczekiwań: {testy_wynik}")

    # Linki do spraw z sekcji 1
    otwarte = karta.get("otwarte_sprawy", {})
    if s1:
        lines.append(f":pushpin: Zrób teraz ({len(s1)}):")
    for p in s1[:5]:
        klucz = p.get("klucz_sprawy", "")
        info = otwarte.get(klucz)
        if isinstance(info, dict) and info.get("url"):
            lines.append(f"  • <{info['url']}|{info.get('identifier', klucz)}> "
                         f"{slack_bezpiecznie(p['tytul'], 60)}")
    if len(s1) > 5:
        lines.append(f"  … i {len(s1) - 5} więcej")

    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    load_env()
    wyczysc_srodowisko()  # sekrety ze środowiska (np. GitHub) też mogą mieć wklejone znaki

    parser = argparse.ArgumentParser(
        description="Przetwarza transkrypcję od początku do końca."
    )
    parser.add_argument("transkrypcja", nargs="?",
                        help="Ścieżka do pliku transkrypcji .md")
    parser.add_argument("--wymus", action="store_true",
                        help="Pomiń rejestr i przetworz ponownie")
    parser.add_argument("--bez-analizy", action="store_true",
                        help="Pomiń model: użyj istniejącego wynik.json (render, daty, Linear, testy, Slack). "
                             "Do naprawy stanu po poprawce kodu; wymaga --wymus, jeśli transkrypcja jest w rejestrze")
    parser.add_argument("--test-slack", action="store_true",
                        help="Wyślij wiadomość testową na Slack i zakończ")
    args = parser.parse_args()

    # ── --test-slack ──────────────────────────────────────────────────────────
    if args.test_slack:
        msg = f":test_tube: przetworz.py test Slack — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ok, err = send_slack(msg)
        if ok:
            print("OK: wiadomość testowa wysłana na Slack.")
        else:
            print(f"BŁĄD Slack: {err}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if not args.transkrypcja:
        parser.error("Podaj ścieżkę do transkrypcji albo użyj --test-slack.")

    transkrypcja = args.transkrypcja

    # a) klient
    klient = extract_klient(transkrypcja)
    if klient is None:
        msg = (f"Nie można wyznaczyć klienta z '{transkrypcja}'. "
               f"Oczekiwany format: ops/transkrypcje/<klient>/...")
        print(f"BŁĄD: {msg}", file=sys.stderr)
        send_slack(f":x: przetworz.py: {msg}")
        sys.exit(1)

    if not Path(transkrypcja).exists():
        print(f"BŁĄD: plik nie istnieje: {transkrypcja}", file=sys.stderr)
        sys.exit(1)

    # b) rejestr
    h = transcript_hash(transkrypcja)
    registry = load_registry()
    if h in registry and not args.wymus:
        entry = registry[h]
        print(f"Pominięto: '{transkrypcja}' była już przetworzona "
              f"({entry.get('przetworzone', '?')}).")
        sys.exit(0)

    # c) lock
    if not acquire_lock():
        print("BŁĄD: inny przebieg przetworz.py już trwa (ops/.przetworz.lock). "
              "Usuń plik lock ręcznie jeśli to błąd.", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = Path("logi/przebiegi")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{timestamp}-{klient}.log"

    nazwa = Path(transkrypcja).stem
    wynik_dir = Path("wyniki") / klient / nazwa
    wynik_path = wynik_dir / "wynik.json"

    sync_stdout = ""

    def fail(step, msg):
        full = f"BŁĄD w kroku '{step}': {msg}"
        _log(log_path, f"\n{full}\n")
        print(full, file=sys.stderr)
        tail = tail_log(log_path, 30)
        if tail:
            print(f"--- ostatnie linie logu ({log_path}) ---\n{tail}\n--- koniec ---",
                  file=sys.stderr)
        send_slack(
            f":x: *[{klient}]* przetworz.py — błąd w `{step}`\n{msg}\nLog: `{log_path}`",
            log_path=log_path,
        )
        release_lock()
        sys.exit(1)

    try:
        print(f"Przetwarzam: {transkrypcja}  (klient: {klient})")
        print(f"Log: {log_path}")

        model = "istniejący wynik.json (bez analizy modelu)"
        if args.bez_analizy:
            if not wynik_path.exists():
                fail("analiza", f"--bez-analizy: brak {wynik_path}")
            print("Pominięto analizę modelu (--bez-analizy), używam istniejącego wynik.json")
        else:
            # d) claude --print
            cmd_file = Path(".claude/commands/analizuj-mail.md" if czy_mail(transkrypcja)
                            else ".claude/commands/analizuj.md")
            if not cmd_file.exists():
                fail("claude", f"Brak pliku komendy: {cmd_file}")

            raw = cmd_file.read_text(encoding="utf-8")
            # Strip YAML frontmatter
            prompt = re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL)
            prompt = prompt.replace("$ARGUMENTS", transkrypcja).strip()

            env = os.environ.copy()
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "64000"
            # Pusta zmienna (np. nieustawiony sekret w GitHubie) to nie to samo co brak zmiennej:
            # claude uznaje ją za podany, ale pusty token i kończy z "Not logged in".
            for name in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
                if name in env and not env[name].strip():
                    del env[name]
            env.setdefault("HOME", str(Path.home()))
            # Model nie potrzebuje kluczy do Linear/Slacka/Gmaila. Treść maila to dane od obcych,
            # więc nawet po udanej prompt injection nie ma czego wyciec.
            for name in ("LINEAR_API_KEY", "SLACK_WEBHOOK_URL", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
                env.pop(name, None)

            # Różnice Mac vs serwer: ścieżka instalacji i logowanie.
            if not shutil.which("claude", path=env.get("PATH")):
                fail("claude", "Nie znaleziono polecenia `claude` w PATH "
                               "(npm install -g @anthropic-ai/claude-code).")
            if os.environ.get("GITHUB_ACTIONS") == "true" and not (
                    env.get("CLAUDE_CODE_OAUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")):
                fail("claude", "Brak CLAUDE_CODE_OAUTH_TOKEN (sekret nieustawiony lub pusty). "
                               "Na serwerze nie ma sesji z keychaina — wygeneruj token: claude setup-token.")

            model = os.environ.get("RINVO_MODEL", "").strip() or DEFAULT_MODEL
            if czy_mail(transkrypcja):
                # mail = niezaufane dane: bez Bash. Skrypty (render, daty) uruchamia przetworz.py.
                narzedzia = ["--tools", "Read,Write,Edit", "--allowedTools", "Read,Write,Edit"]
            else:
                narzedzia = ["--allowedTools", "Read,Write,Edit,Bash"]
            claude_cmd = [
                "claude", "--print", prompt,
                "--model", model,
                *narzedzia,
                "--dangerously-skip-permissions",
            ]

            print("Uruchamiam analizę Claude (do 30 min)…")
            with open(log_path, "w", encoding="utf-8") as lf:
                lf.write(f"=== przetworz.py ===\n")
                lf.write(f"Transkrypcja: {transkrypcja}\n")
                lf.write(f"Klient: {klient}\n")
                lf.write(f"Start: {datetime.now().isoformat()}\n\n")

            try:
                with open(log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"{'='*60}\n=== claude --print ===\n{'='*60}\n\n")
                    lf.flush()
                    r = subprocess.run(
                        claude_cmd,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=lf,
                        stderr=lf,
                        timeout=30 * 60,
                    )
            except subprocess.TimeoutExpired:
                fail("claude", "Przekroczono limit 30 minut.")

            if r.returncode != 0:
                # claude zwykle pisze przyczynę (np. "Not logged in", "401") na stdout
                cause = tail_log(log_path, 1)[:200]
                fail("claude", f"Kod wyjścia: {r.returncode}. Przyczyna: {cause}. Log: {log_path}")

        # e) render.py
        if not wynik_path.exists():
            fail("render", f"Brak wynik.json po analizie: {wynik_path}")

        print("  render.py…")
        r = run_step(
            ["python3", "-I", "render.py", str(wynik_path), "--transkrypcja", transkrypcja],
            log_path, "render.py", timeout=120
        )
        if r.returncode != 0:
            fail("render", f"render.py kod {r.returncode}. Log: {log_path}")

        # daty.py
        print("  daty.py…")
        r = run_step(
            ["python3", "-I", "daty.py", str(wynik_path)],
            log_path, "daty.py", timeout=60
        )
        if r.returncode != 0:
            fail("daty", f"daty.py kod {r.returncode}. Log: {log_path}")

        # linear_sync.py
        print("  linear_sync.py…")
        sync_result = subprocess.run(
            ["python3", "linear_sync.py", str(wynik_path), "--klient", klient,
             "--zrodlo", transkrypcja],
            capture_output=True,
            text=True,
            timeout=180,
        )
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(f"\n{'='*60}\n=== linear_sync.py ===\n{'='*60}\n")
            lf.write(sync_result.stdout)
            lf.write(sync_result.stderr)
        sync_stdout = sync_result.stdout
        print(sync_result.stdout, end="")
        if sync_result.returncode != 0:
            fail("linear_sync", f"Kod {sync_result.returncode}. Log: {log_path}")

        # e2) testy oczekiwań — jeśli plik istnieje
        testy_wynik = None
        oczekiwania_path = Path("testy/oczekiwania") / f"{klient}-{nazwa}.json"
        if oczekiwania_path.exists():
            print("  uruchom.py (oczekiwania)…")
            testy_result = subprocess.run(
                ["python3", "testy/uruchom.py", str(wynik_path), str(oczekiwania_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n{'='*60}\n=== uruchom.py ===\n{'='*60}\n")
                lf.write(testy_result.stdout)
                lf.write(testy_result.stderr)
            print(testy_result.stdout, end="")
            last_line = testy_result.stdout.strip().splitlines()[-1] if testy_result.stdout.strip() else ""
            if last_line.startswith(("PASS", "FAIL")):
                testy_wynik = last_line

        # f) Slack — zawsze, niezależnie od liczby nowych zgłoszeń
        meta_maila = wczytaj_meta_maila(transkrypcja) if czy_mail(transkrypcja) else None
        summary = build_slack_summary(klient, wynik_path, sync_stdout, testy_wynik=testy_wynik,
                                      model=model, meta_maila=meta_maila)
        _log(log_path, f"\n{'='*60}\n=== Slack ===\n{'='*60}\n")
        slack_ok, slack_err = send_slack(summary, log_path=log_path)
        if slack_ok:
            print("  Slack: wysłano.")
        else:
            print(f"  Slack: BŁĄD — {slack_err}", file=sys.stderr)
        print(f"\n{summary}")

        # g) rejestr
        registry[h] = {
            "klient": klient,
            "transkrypcja": transkrypcja,
            "przetworzone": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_registry(registry)
        print(f"\nGotowe. Log: {log_path}")

    except Exception as exc:
        fail("nieoczekiwany błąd", str(exc))
    finally:
        release_lock()


if __name__ == "__main__":
    main()
