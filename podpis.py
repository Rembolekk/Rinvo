"""podpis.py – każdy komentarz automatu zaczyna się od „Agent:”.

Agent działa na tokenach właściciela (Linear, GitHub), więc komentarze wyglądają jak napisane przez człowieka. Prefiks
„Agent:” mówi czytelnikowi, że to robota automatu. Docelowo agent ma własne konto bota z osobnymi uprawnieniami (README).
"""

import re

PREFIKS = "Agent:"


def podpisz_agenta(tekst):
    """„Agent:” na początku komentarza (raz). „Agent przejął” → „Agent: przejął”."""
    t = str(tekst or "").lstrip()
    if t.startswith(PREFIKS):
        return t
    m = re.match(r"^Agent\s+", t)
    if m:
        return f"{PREFIKS} {t[m.end():]}"
    return f"{PREFIKS} {t}"


def bez_podpisu(tekst):
    """Komentarz bez prefiksu „Agent:” (do rozpoznawania nagłówków szkiców i oddań)."""
    return re.sub(r"^\s*Agent:\s*", "", str(tekst or ""), count=1)
