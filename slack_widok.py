#!/usr/bin/env python3
"""slack_widok.py – wspólne klocki krótkich wiadomości na Slacku (Block Kit przez webhook).

Zasady wyglądu: do przeczytania w 10 sekund; tytuł do 60 znaków jako link (bez prefiksu klienta);
bez technicznych nazw (identyfikatory, klucze spraw) w tekście, tylko w linkach; to samo nie powtarza się
w kilku miejscach. Tekst z maili i rozmów jest zawsze oczyszczany ze znaczników Slacka.
"""

import re

from maile import slack_bezpiecznie

LIMIT_POZYCJI = 5

SLOWA_DOMYSLNE = {
    "pieniadze": "pieniądze", "do_klienta": "klient", "zakaz": "zakaz", "decyzja_zastrzezona": "decyzja",
    "nieodwracalne": "decyzja", "produkt": "decyzja", "nadpisanie": "decyzja",
    "pewnosc_niska": "weryfikacja", "brak_kryteriow": "weryfikacja",
}


def forma(n, jedna, kilka, wiele):
    """Polska odmiana po liczebniku: 1 → jedna, 2–4 (poza 12–14) → kilka, reszta → wiele."""
    if n == 1:
        return jedna
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return kilka
    return wiele


def krotki_tytul(tytul, limit=60):
    """Tytuł bez prefiksu klienta „[klient] ”, do limit znaków (z wielokropkiem), oczyszczony dla Slacka."""
    t = re.sub(r"^\[[^\]]+\]\s*", "", str(tytul or "")).strip()
    t = re.sub(r"\s+", " ", t)
    if len(t) > limit:
        t = t[: limit - 1].rstrip() + "…"
    return slack_bezpiecznie(t, limit + 10)


def link(url, tytul, limit=60):
    t = krotki_tytul(tytul, limit)
    return f"<{url}|{t}>" if url else t


def widok_linear_url(urle, team="RIN"):
    """Link do widoku wszystkich otwartych zgłoszeń zespołu, zbudowany z dowolnego linku do zgłoszenia."""
    for u in urle:
        m = re.match(r"^(https://linear\.app/[^/]+)/issue/", u or "")
        if m:
            return f"{m.group(1)}/team/{team}/active"
    return None


def slowo_powodu(przypisanie, etykiety, Z):
    """Jedno słowo powodu: pieniądze, klient, zakaz, decyzja albo weryfikacja.

    Najpierw identyfikatory reguł zapisane w karcie; dla starszych wpisów dopasowanie po tekście powodu;
    na końcu etykiety zgłoszenia."""
    slowa = {**SLOWA_DOMYSLNE, **{k: v for k, v in Z.get("slowa_powodow", {}).items() if not k.startswith("_")}}
    reguly = list((przypisanie or {}).get("reguly") or [])
    if not reguly:
        for tekst in (przypisanie or {}).get("powody", []):
            for nazwa, r in Z.get("czlowiek_gdy", {}).items():
                if r.get("powod") and tekst.startswith(r["powod"]):
                    reguly.append(nazwa)
                    break
            else:
                if tekst == Z.get("produkt", {}).get("powod_czlowieka"):
                    reguly.append("produkt")
                elif tekst == Z.get("agent", {}).get("powod_braku_kryteriow"):
                    reguly.append("brak_kryteriow")
    for r in reguly:
        if r in slowa:
            return slowa[r]
    et = set(etykiety or [])
    if Z["etykiety"]["weryfikacja"] in et:
        return "weryfikacja"
    return "decyzja"


def linia_pozycji(url, tytul, klient=None, powod=None, dodatek=None):
    """Jedna linijka: • <link do tytułu> · klient · powód."""
    czesci = [link(url, tytul)]
    if klient:
        czesci.append(slack_bezpiecznie(klient, 40))
    if dodatek:
        czesci.append(dodatek)
    if powod:
        czesci.append(powod)
    return "• " + " · ".join(czesci)


def ogranicz(linie, limit=LIMIT_POZYCJI, reszta_tekst="… i {n} więcej (w Linearze)"):
    """Maksymalnie limit linijek; reszta jako jedna linijka."""
    if len(linie) <= limit:
        return list(linie)
    return list(linie[:limit]) + [reszta_tekst.format(n=len(linie) - limit)]


def bloki(sekcje, kontekst=None):
    """Sekcje mrkdwn (pierwsza = zdanie na górze) + opcjonalna szara linijka kontekstu → Block Kit."""
    b = [{"type": "section", "text": {"type": "mrkdwn", "text": s}} for s in sekcje if s]
    if kontekst:
        b.append({"type": "context", "elements": [{"type": "mrkdwn", "text": kontekst}]})
    return b


def tekst_zapasowy(sekcje, kontekst=None):
    """Ta sama treść jako zwykły tekst (powiadomienia, terminal, testy)."""
    return "\n\n".join(s for s in list(sekcje) + ([kontekst] if kontekst else []) if s)
