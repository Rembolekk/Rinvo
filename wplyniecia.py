#!/usr/bin/env python3
"""wplyniecia.py – kiedy rozmowa albo mail WPŁYNĘŁY do systemu.

Czas poprawki liczymy od wpłynięcia źródła do scalenia poprawki, a nie od daty rozmowy z nazwy pliku. Wpłynięcie to czas commita,
w którym plik transkrypcji albo maila trafił do repozytorium (najnowsze dodanie pliku), zapisany w rejestrze ops/.przetworzone.json
(pole „wplynelo”, ISO z strefą). Rejestr jest źródłem prawdy dla stron (w CI repozytorium bywa płytkie, więc git nie wystarcza).

Użycie: python3 wplyniecia.py   # uzupełnia brakujące „wplynelo” w ops/.przetworzone.json z historii gita
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REJESTR = Path("ops/.przetworzone.json")


def czas_z_gita(sciezka, root="."):
    """ISO czas commita, w którym plik został (ostatnio) dodany do repozytorium; None, gdy git nie zna pliku."""
    try:
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cI", "--", str(sciezka)], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    linie = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    return linie[0] if r.returncode == 0 and linie else None


def czas_wplyniecia(sciezka, root="."):
    """Czas commita pliku, a gdy go nie ma (plik jeszcze niezacommitowany): teraz (UTC)."""
    return czas_z_gita(sciezka, root) or datetime.now(timezone.utc).isoformat(timespec="seconds")


def uzupelnij(rejestr_path=REJESTR, root="."):
    """Dopisuje „wplynelo” wpisom rejestru, które go nie mają (z historii gita). Zwraca liczbę uzupełnionych."""
    p = Path(rejestr_path)
    if not p.exists():
        return 0
    rejestr = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    for wpis in rejestr.values():
        if not wpis.get("wplynelo") and wpis.get("transkrypcja"):
            czas = czas_z_gita(wpis["transkrypcja"], root)
            if czas:
                wpis["wplynelo"] = czas
                n += 1
    if n:
        p.write_text(json.dumps(rejestr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return n


def mapa(rejestr):
    """{ścieżka źródła: ISO czas wpłynięcia} z rejestru (wpisy bez „wplynelo” są pomijane)."""
    return {w["transkrypcja"]: w["wplynelo"] for w in (rejestr or {}).values() if w.get("transkrypcja") and w.get("wplynelo")}


def main():
    print(f"Uzupełniono wpłynięcia: {uzupelnij()}")


if __name__ == "__main__":
    sys.exit(main())
