#!/usr/bin/env python3
"""klucze.py – wygasanie kluczy i tokenów: ostrzeżenie w „Uwadze” porannego podsumowania na 7 dni przed.

  * token GitHub (AGENT_GITHUB_TOKEN): data z nagłówka odpowiedzi API github-authentication-token-expiration
    (np. „2026-11-13 12:00:00 UTC”); sprawdzamy ją jednym lekkim zapytaniem do repozytorium agenta,
  * pozostałe sekrety: data wygaśnięcia wpisana ręcznie w ops/zasady.json → klucze.daty ({"CLAUDE_CODE_OAUTH_TOKEN": "2027-01-31"}).
"""

import re
import ssl
import urllib.request
from datetime import date


def data_z_naglowka(tekst):
    """„2026-11-13 12:00:00 UTC” → date albo None."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(tekst or ""))
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def pobierz_naglowek_github(token, repo, naglowek="github-authentication-token-expiration", otworz=None):
    """Wartość nagłówka wygaśnięcia tokenu albo None (brak tokenu, błąd sieci, token bez daty wygaśnięcia). Token nie trafia do logów."""
    if not token:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "rinvo-agent"})
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        with (otworz or urllib.request.urlopen)(req, timeout=20, **({} if otworz else {"context": ctx})) as r:
            return r.headers.get(naglowek)
    except Exception:  # noqa: BLE001  (brak sieci albo token odrzucony: pomijamy ostrzeżenie, nic nie wypisujemy)
        return None


def wygasajace(Z, naglowek_github, dzis):
    """[{"nazwa", "data", "dni"}] kluczy wygasających w ciągu klucze.dni_przed dni (albo już wygasłych), od najbliższego."""
    K = Z["klucze"]
    wpisy = []
    d = data_z_naglowka(naglowek_github)
    if d:
        wpisy.append(("token GitHub agenta", d))
    for nazwa, tekst in (K.get("daty") or {}).items():
        dd = data_z_naglowka(tekst)
        if dd:
            wpisy.append((nazwa, dd))
    wynik = [{"nazwa": n, "data": dd, "dni": (dd - dzis).days} for n, dd in wpisy if (dd - dzis).days <= K["dni_przed"]]
    return sorted(wynik, key=lambda x: (x["dni"], x["nazwa"]))


def linie_uwagi(lista):
    out = []
    for k in lista:
        if k["dni"] < 0:
            out.append(f":key: {k['nazwa']} wygasł {k['data'].strftime('%d.%m')}: odnów go.")
        elif k["dni"] == 0:
            out.append(f":key: {k['nazwa']} wygasa dziś: odnów go.")
        else:
            out.append(f":key: {k['nazwa']} wygasa za {k['dni']} {'dzień' if k['dni'] == 1 else 'dni'} ({k['data'].strftime('%d.%m')}): odnów go.")
    return out
