#!/usr/bin/env python3
"""przetworz.py – automat przetwarzania transkrypcji od początku do końca.

Użycie:
  python3 przetworz.py ops/transkrypcje/<klient>/<plik>.md
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
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


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
            os.environ.setdefault(key.strip(), val.strip())


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
    parts = Path(transkrypcja).parts
    for i, part in enumerate(parts):
        if part == "transkrypcje" and i + 1 < len(parts):
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

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
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

def build_slack_summary(klient, wynik_path, sync_stdout, testy_wynik=None, model=None):
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

    lines = [f":white_check_mark: *[{klient}]* Rozmowa z {data} przetworzona"]
    lines.append(
        f"Zrób teraz: {len(s1)} | Czeka: {len(s2)} | Ryzyka: {len(s5)} | "
        f"Nowe w Linear: {nowe} | Pominięte: {pominieto}"
    )

    if blocked:
        lines.append(f":no_entry: Zablokowane przez zakaz: {len(blocked)}")
    if niska:
        lines.append(f":warning: Do weryfikacji (pewność niska): {len(niska)}")
    # Show reopened only when linear_sync actually processed updates (not pominięte)
    if n_aktualizacji > 0:
        reopened = [a for a in aktualizacje if a.get("nowy_status") == "zrob_teraz"]
        if reopened:
            lines.append(f":arrows_counterclockwise: Wznowione sprawy: {len(reopened)}")
    if ostrzezenia:
        lines.append(f":clock1: Brak faktów czasowych dla {len(ostrzezenia)} pozycji z cytatami o czasie")
    if any("Powtarzające się ryzyko" in ln for ln in sync_stdout.splitlines()):
        lines.append(":rotating_light: Powtarzające się ryzyko — sprawdź Linear")
    if model:
        lines.append(f":robot_face: Model analizy: {model}")
    if testy_wynik:
        icon = ":white_check_mark:" if testy_wynik.startswith("PASS") else ":x:"
        lines.append(f"{icon} Testy oczekiwań: {testy_wynik}")

    # Links for sekcja 1 items (read karta.json for URLs)
    karta_path = Path("ops") / "klienci" / klient / "karta.json"
    if karta_path.exists():
        try:
            karta = json.loads(karta_path.read_text(encoding="utf-8"))
            otwarte = karta.get("otwarte_sprawy", {})
            for p in s1[:5]:
                klucz = p.get("klucz_sprawy", "")
                if klucz in otwarte and isinstance(otwarte[klucz], dict):
                    info = otwarte[klucz]
                    url = info.get("url", "")
                    ident = info.get("identifier", klucz)
                    if url:
                        lines.append(f"  • <{url}|{ident}> {p['tytul'][:60]}")
            if len(s1) > 5:
                lines.append(f"  … i {len(s1) - 5} więcej")
        except Exception:
            pass

    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    load_env()

    parser = argparse.ArgumentParser(
        description="Przetwarza transkrypcję od początku do końca."
    )
    parser.add_argument("transkrypcja", nargs="?",
                        help="Ścieżka do pliku transkrypcji .md")
    parser.add_argument("--wymus", action="store_true",
                        help="Pomiń rejestr i przetworz ponownie")
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
        send_slack(
            f":x: *[{klient}]* przetworz.py — błąd w `{step}`\n{msg}\nLog: `{log_path}`",
            log_path=log_path,
        )
        release_lock()
        sys.exit(1)

    try:
        print(f"Przetwarzam: {transkrypcja}  (klient: {klient})")
        print(f"Log: {log_path}")

        # d) claude --print
        cmd_file = Path(".claude/commands/analizuj.md")
        if not cmd_file.exists():
            fail("claude", f"Brak pliku komendy: {cmd_file}")

        raw = cmd_file.read_text(encoding="utf-8")
        # Strip YAML frontmatter
        prompt = re.sub(r"^---\n.*?\n---\n", "", raw, count=1, flags=re.DOTALL)
        prompt = prompt.replace("$ARGUMENTS", transkrypcja).strip()

        env = os.environ.copy()
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "64000"

        model = os.environ.get("RINVO_MODEL", "").strip() or DEFAULT_MODEL
        claude_cmd = [
            "claude", "--print", prompt,
            "--model", model,
            "--allowedTools", "Read,Write,Edit,Bash",
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
                    stdout=lf,
                    stderr=lf,
                    timeout=30 * 60,
                )
        except subprocess.TimeoutExpired:
            fail("claude", "Przekroczono limit 30 minut.")

        if r.returncode != 0:
            fail("claude", f"Kod wyjścia: {r.returncode}. Log: {log_path}")

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
            ["python3", "linear_sync.py", str(wynik_path), "--klient", klient],
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
        summary = build_slack_summary(klient, wynik_path, sync_stdout, testy_wynik=testy_wynik, model=model)
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
