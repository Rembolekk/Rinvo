#!/usr/bin/env python3
"""generuj_strony.py – statyczne strony dla ludzi (GitHub Pages): wszystko o kliencie i o prośbach produktowych w jednym miejscu.

Użycie:
  python3 generuj_strony.py                 # zapisuje index.html, klienci/<klient>.html, glos-klientow.html w katalogu głównym
  python3 generuj_strony.py --dzien 2026-10-14

Zwykły Python i HTML, bez modelu i bez zapytań do sieci: czyta karty klientów (ops/klienci), wyniki rozmów i maili (wyniki/),
prośby produktowe (ops/produkt/prosby.json), stan Lineara (ops/.stan_linear.json) i dziennik zdarzeń agenta
(ops/.zdarzenia.json). Adresy e-mail kontaktów NIE trafiają na strony (repozytorium jest publiczne).
"""

import argparse
import html
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import slack_widok as sw
import stan_linear
import zakazy_czas
import zasady
import zdarzenia

e = lambda s: html.escape(str(s if s is not None else ""))       # noqa: E731

STANY_ZAMKNIETE = {"Done", "Canceled", "Cancelled", "Duplicate"}
STANY_AKTYWNE = {"Todo", "In Progress", "In Review"}
TEMATY_RYZYKA = {"konkurencja": "Konkurencja", "grozba_rezygnacji": "Groźba rezygnacji", "cena_budzet": "Cena i budżet",
                 "jakosc_bota": "Jakość bota", "rozliczenia": "Rozliczenia", "inne": "Inne"}
SWIATLO = {"czerwone": ("Czerwone", "Powtarzające się ryzyko albo sprawa po terminie"),
           "zolte": ("Żółte", "Coś wymaga człowieka"),
           "zielone": ("Zielone", "Reszta: bez ryzyk i spraw po terminie")}
NAZWY_ZDARZEN = {"pr_otwarty": "Agent otworzył poprawkę (PR)", "pr_scalony": "Poprawka agenta scalona (PR)",
                 "pr_oddany": "Agent oddał poprawkę człowiekowi (PR)", "material": "Materiał dla klienta",
                 "notatka": "Notatka przed spotkaniem (wewnętrzna)"}

CSS = """
:root{--bg:#fff;--ink:#202124;--mut:#70757a;--line:#eceef0;--acc:#2b59c3;--ok:#2e8b57;--warn:#d99a00;--bad:#c2410c;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#141516;--ink:#e8eaed;--mut:#9aa0a6;--line:#2a2c2e;--acc:#8ab4f8;--ok:#6fcf97;--warn:#f2c14e;--bad:#f28b6a;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:40px 20px 56px}
nav{font-size:.85rem;margin:0 0 36px} nav a{color:var(--mut);text-decoration:none;margin-right:18px} nav a:hover{color:var(--ink)}
h1{font-size:1.5rem;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:.78rem;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:44px 0 12px}
h3{font-size:1rem;font-weight:600;margin:0 0 6px}
a{color:var(--acc);text-decoration:none} a:hover{text-decoration:underline}
.meta,.sub{color:var(--mut);margin:0 0 14px}
.gora{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 32px;margin:0 0 8px}
.glowne{font-size:2rem;line-height:1.25;font-weight:600;margin:0;letter-spacing:-.015em}
.agenci{color:var(--mut);font-size:.95rem;margin:0}
.podpis{color:var(--mut);font-size:.78rem;margin:2px 0 0;text-align:right}
table{width:100%;border-collapse:collapse}
.klienci{margin-top:36px}
th{font-weight:500;font-size:.78rem;color:var(--mut);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:14px 10px;border-bottom:1px solid var(--line);vertical-align:baseline}
th.n,td.n{text-align:right;font-variant-numeric:tabular-nums}
td.n.zero{color:var(--mut)} td.uwaga{color:var(--mut);font-size:.92rem}
.tabela{overflow-x:auto}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;vertical-align:baseline;margin-right:10px;cursor:help}
.dot.czerwone{background:var(--bad)} .dot.zolte{background:var(--warn)} .dot.zielone{background:var(--ok)}
.now3{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:28px}
.panel{padding:0 0 18px;margin:0 0 18px;border-bottom:1px solid var(--line)}
ul{margin:0;padding-left:18px} li{margin:0 0 8px}
.tag{font-size:.74rem;color:var(--mut);border:1px solid var(--line);border-radius:99px;padding:0 8px;margin-left:6px;white-space:nowrap}
.tag.bad{color:var(--bad);border-color:currentColor} .tag.ok{color:var(--ok);border-color:currentColor} .tag.warn{color:var(--warn);border-color:currentColor}
blockquote{margin:6px 0 0;padding:2px 12px;border-left:2px solid var(--line);color:var(--mut);font-size:.92rem}
.tl{list-style:none;padding:0;margin:0} .tl li{display:grid;grid-template-columns:92px 1fr;gap:4px 14px;padding:12px 0;border-bottom:1px solid var(--line);margin:0}
.tl time{color:var(--mut);font-size:.85rem} @media (max-width:560px){.tl li{grid-template-columns:1fr}.glowne{font-size:1.6rem}.podpis{text-align:left}}
.kind{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin-right:8px}
.empty{color:var(--mut)} details summary{cursor:pointer;color:var(--mut);font-size:.9rem}
summary.jedna{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
footer{margin-top:56px;color:var(--mut);font-size:.78rem}
"""


# ── dane ──────────────────────────────────────────────────────────────────────

def _json(p, domyslnie):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else domyslnie


def wczytaj_dane(root=".", dzis=None):
    root = Path(root)
    Z = zasady.wczytaj_zasady(root / "ops/zasady.json") if (root / "ops/zasady.json").exists() else zasady.wczytaj_zasady()
    klienci = {}
    for p in sorted((root / "ops/klienci").glob("*/karta.json")):
        slug = p.parent.name
        wyniki = []
        for w in sorted((root / "wyniki" / slug).glob("*/wynik.json")):
            dane = _json(w, {})
            wyniki.append({"folder": w.parent.name, "raport": f"wyniki/{slug}/{w.parent.name}/raport.html"
                           if (w.parent / "raport.html").exists() else None, "dane": dane})
        klienci[slug] = {"slug": slug, "karta": _json(p, {}), "wyniki": wyniki}
    return {"Z": Z, "klienci": klienci, "stan": stan_linear.wczytaj(root / "ops/.stan_linear.json"),
            "zdarzenia": zdarzenia.wczytaj(root / "ops/.zdarzenia.json"), "prosby": _json(root / "ops/produkt/prosby.json", {}),
            "dzis": dzis or datetime.now(ZoneInfo("Europe/Warsaw")).date(), "root": root,
            "sygnaly_stan": _json(root / "ops/.sygnaly.json", None),
            "propozycje": _json(root / "ops/produkt/propozycje.json", {}),
            "przetworzone": _json(root / "ops/.przetworzone.json", {}),
            "widok_url": (_json(root / Z.get("dla_czlowieka", {}).get("widok", {}).get("plik", "ops/widok_dla_mnie.json"), {}) or {}).get("url")}


def nazwa_klienta(klient):
    """Nazwa do wyświetlania: pole „nazwa” z karty, a bez niego slug z dużymi literami."""
    return klient["karta"].get("nazwa") or klient["slug"].replace("-", " ").title()


def bez_prefiksu(tytul):
    t = str(tytul or "")
    return t.split("] ", 1)[1] if t.startswith("[") and "] " in t else t


def wymaga_ciebie_etykiety(dane):
    """Etykiety spraw dla człowieka: te same, po których filtruje widok „Dla mnie dziś” (ops/zasady.json → dla_czlowieka.widok)."""
    return set(dane["Z"].get("dla_czlowieka", {}).get("widok", {}).get("etykiety") or
               [dane["Z"]["etykiety"]["czlowiek"], dane["Z"]["etykiety"]["weryfikacja"], dane["Z"]["etykiety"]["szkic"]])


def sprawy_klienta(dane, slug):
    """Zgłoszenia klienta z pliku stanu Lineara, podzielone na: czlowiek, agent, czeka (otwarte) oraz zamkniete."""
    E = dane["Z"]["etykiety"]
    czlowiek_et = wymaga_ciebie_etykiety(dane)
    wynik = {"czlowiek": [], "agent": [], "czeka": [], "backlog": [], "inne": [], "zamkniete": []}
    for ident, z in sorted(dane["stan"]["zgloszenia"].items(), key=lambda kv: int(kv[0].split("-")[1])):
        if not z["tytul"].startswith(f"[{slug}]"):
            continue
        z = {**z, "id": ident}
        if z["stan"] in STANY_ZAMKNIETE:
            wynik["zamkniete"].append(z)
            continue
        et = set(z["etykiety"])
        if et & czlowiek_et:                      # te same sprawy, które pokazuje widok „Dla mnie dziś” w Linearze
            wynik["czlowiek"].append(z)
        elif E["czeka"] in et:
            wynik["czeka"].append(z)
        elif z["stan"] == "Backlog":
            wynik["backlog"].append(z)
        elif E["agent"] in et:
            wynik["agent"].append(z)
        else:
            wynik["inne"].append(z)          # otwarte bez etykiety routingu: liczą się tylko do „po terminie”
    return wynik


def po_terminie(z, dzis):
    return bool(z.get("termin")) and z["stan"] not in STANY_ZAMKNIETE and date.fromisoformat(z["termin"]) < dzis


def ryzyka_klienta(klient):
    """[(temat, [wpisy])] posortowane od największej liczby wystąpień."""
    r = klient["karta"].get("ryzyka") or {}
    return sorted(((t, sorted(w, key=lambda x: x.get("data", ""))) for t, w in r.items() if w), key=lambda x: (-len(x[1]), x[0]))


def wystapienia(wpisy):
    """Ile razy ryzyko się pojawiło: liczba różnych źródeł (rozmów albo maili), a nie liczba cytatów."""
    return len({w.get("zrodlo") or w.get("data") for w in wpisy})


def swiatlo(dane, klient):
    """(kolor, powody): czerwone = powtarzające się ryzyko albo sprawa po terminie; żółte = coś wymaga człowieka; zielone = reszta."""
    s = sprawy_klienta(dane, klient["slug"])
    powody = []
    for temat, wpisy in ryzyka_klienta(klient):
        if wystapienia(wpisy) >= 2:
            powody.append(f"ryzyko „{TEMATY_RYZYKA.get(temat, temat)}” pojawiło się już {wystapienia(wpisy)} razy")
    spozn = [z for k in ("czlowiek", "agent", "czeka", "backlog", "inne") for z in s[k] if po_terminie(z, dane["dzis"])]
    if spozn:
        powody.append(f"po terminie: {len(spozn)}")
    if powody:
        return "czerwone", powody
    if s["czlowiek"]:
        return "zolte", [f"wymaga człowieka: {len(s['czlowiek'])}"]
    return "zielone", []


# ── elementy HTML ─────────────────────────────────────────────────────────────

def _link_zgloszenia(z):
    return f'<a href="{e(z["url"])}">{e(bez_prefiksu(z["tytul"]))}</a> <span class="tag">{e(z["id"])}</span>'


def _lista_zgloszen(lista, dzis, pusto="Nic."):
    if not lista:
        return f'<p class="empty">{e(pusto)}</p>'
    wiersze = []
    for z in lista:
        dod = f' <span class="tag {"bad" if po_terminie(z, dzis) else ""}">termin {e(z["termin"])}</span>' if z.get("termin") else ""
        regr = ' <span class="tag bad">regresja</span>' if "Regresja" in z.get("etykiety", []) else ""
        wiersze.append(f"<li>{_link_zgloszenia(z)} <span class=\"tag\">{e(z['stan'])}</span>{regr}{dod}</li>")
    return "<ul>" + "".join(wiersze) + "</ul>"


MIESIACE_PL = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]


def data_po_polsku(iso):
    """„2026-10-15T14:00:00+00:00” → „15 października 2026, 16:00” (czas polski); „brak danych”, gdy nie da się odczytać."""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("Europe/Warsaw")) if dt.tzinfo else dt
    except (TypeError, ValueError):
        return "brak danych"
    return f"{dt.day} {MIESIACE_PL[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def strona(tytul, tresc, dane, poziom=0, opis="", h1=True):
    pre = "../" * poziom
    zapisano = data_po_polsku(dane["stan"].get("zapisano"))
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(tytul)}</title><meta name="robots" content="noindex"><style>{CSS}</style></head><body><div class="wrap">
<nav><a href="{pre}index.html">Klienci</a><a href="{pre}glos-klientow.html">Głos klientów</a></nav>
{f'<h1>{e(tytul)}</h1>' if h1 else ''}{f'<p class="meta">{e(opis)}</p>' if opis else ''}
{tresc}
<footer>Dane fikcyjne, demo · zaktualizowano {e(zapisano)}</footer>
</div></body></html>
"""


# ── strona główna ─────────────────────────────────────────────────────────────

TEMATY_UWAGA = {"konkurencja": ("konkurencja", "wraca"), "grozba_rezygnacji": ("groźba rezygnacji", "wraca"), "cena_budzet": ("temat ceny", "wraca"),
                "jakosc_bota": ("jakość bota", "wraca"), "rozliczenia": ("rozliczenia", "wracają"), "inne": ("ryzyko", "wraca")}


def forma_liczby(n, jeden, kilka, wiele):
    """Polska odmiana po liczebniku: 1 → jeden, 2–4 (poza 12–14) → kilka, reszta → wiele."""
    if n == 1:
        return jeden
    return kilka if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else wiele


def uwaga_klienta(dane, klient):
    """Jedno krótkie zdanie o tym, co pali: powtarzające się ryzyko („konkurencja wraca drugi raz”), a w razie braku sprawy po terminie. Puste, gdy nic."""
    for temat, wpisy in ryzyka_klienta(klient):
        n = wystapienia(wpisy)
        if n >= 2:
            nazwa, czasownik = TEMATY_UWAGA.get(temat, (TEMATY_RYZYKA.get(temat, temat).lower(), "wraca"))
            return f"{nazwa} {czasownik} {'drugi' if n == 2 else str(n) + '.'} raz"
    s = sprawy_klienta(dane, klient["slug"])
    spozn = [z for k in ("czlowiek", "agent", "czeka", "backlog", "inne") for z in s[k] if po_terminie(z, dane["dzis"])]
    if spozn:
        n = len(spozn)
        return f"{n} {forma_liczby(n, 'sprawa', 'sprawy', 'spraw')} po terminie"
    return ""


def wiersz_klienta(dane, slug, nazwa, href, kolor, tytul_kropki, s, uwaga):
    def liczba(n):
        return f'<td class="n{" zero" if n == 0 else ""}">{n}</td>'
    return (f'<tr><td><span class="dot {kolor}" title="{e(tytul_kropki)}"></span><a href="{e(href)}">{e(nazwa)}</a></td>'
            f'{liczba(len(s["czlowiek"]))}{liczba(len(s["agent"]))}{liczba(len(s["czeka"]))}<td class="uwaga">{e(uwaga) if uwaga else "—"}</td></tr>')


def sprawy_dla_czlowieka(dane):
    """Wszystkie otwarte sprawy dla człowieka: tyle, ile pokazuje widok „Dla mnie dziś” (te same etykiety)."""
    et = wymaga_ciebie_etykiety(dane)
    return [i for i, z in dane["stan"]["zgloszenia"].items() if z["stan"] not in STANY_ZAMKNIETE and set(z["etykiety"]) & et]


def zdanie_agentow(st):
    z = st["zamkniete"]
    zam = f"{z} {forma_liczby(z, 'sprawa zamknięta', 'sprawy zamknięte', 'spraw zamkniętych')}"
    if not st["pomiary"]:
        return f"Agenci w tym tygodniu: {zam}, jeszcze bez scalonej poprawki"
    sredni = sum((p["czas"] for p in st["pomiary"]), timedelta()) / len(st["pomiary"])
    return f"Agenci w tym tygodniu: {zam}, poprawka średnio w {formatuj_czas(sredni)} od wpłynięcia rozmowy"


def strona_index(dane):
    n = len(sprawy_dla_czlowieka(dane))
    if n == 0:
        glowne = "Dziś nic nie wymaga Ciebie"
    else:
        zd = f"{n} {forma_liczby(n, 'sprawie', 'sprawach', 'sprawach')}"
        link = f'<a href="{e(dane["widok_url"])}">{zd}</a>' if dane.get("widok_url") else zd
        glowne = f"Dziś potrzebujemy Cię w {link}"
    st = statystyki_agentow(dane)
    wiersze = []
    for slug, k in sorted(dane["klienci"].items(), key=lambda kv: nazwa_klienta(kv[1]).casefold()):
        kolor, powody = swiatlo(dane, k)
        opis_koloru = f"{SWIATLO[kolor][0]}: " + ("; ".join(powody) if powody else SWIATLO[kolor][1])
        wiersze.append(wiersz_klienta(dane, slug, nazwa_klienta(k), f"klienci/{slug}.html", kolor, opis_koloru, sprawy_klienta(dane, slug), uwaga_klienta(dane, k)))
    sp = sprawy_klienta(dane, "produkt")
    if any(sp[k] for k in ("czlowiek", "agent", "czeka")):                       # propozycje produktowe: zgłoszenia „[produkt] …”
        kol = "zolte" if sp["czlowiek"] else "zielone"
        wiersze.append(wiersz_klienta(dane, "produkt", "Produkt", "glos-klientow.html", kol, f"{SWIATLO[kol][0]}: {SWIATLO[kol][1]}", sp, ""))
    tabela = ('<div class="tabela"><table class="klienci"><thead><tr><th>Klient</th><th class="n">Wymaga Ciebie</th><th class="n">U agentów</th>'
              '<th class="n">Czeka na klienta</th><th>Uwaga</th></tr></thead><tbody>' + "".join(wiersze) + "</tbody></table></div>") if wiersze else \
        '<p class="empty">Brak klientów.</p>'
    szczegoly = ""
    if st["pomiary"]:
        def poprawka(pm):
            lacze = f'<a href="{e(pm["url"])}">{e(pm["tytul"])}</a>' if str(pm.get("url", "")).startswith("http") else e(pm["tytul"])
            return f'<tr><td>{lacze} <span class="tag">{e(pm["zgloszenie"])}</span></td><td class="n">{e(formatuj_czas(pm["czas"]))}</td></tr>'
        szczegoly = ('<details style="margin-top:28px"><summary>Poprawki scalone w tym tygodniu</summary><div class="tabela"><table><thead><tr><th>Poprawka</th>'
                     '<th class="n">Od wpłynięcia rozmowy</th></tr></thead><tbody>' + "".join(poprawka(pm) for pm in sorted(st["pomiary"], key=lambda x: x["czas"]))
                     + "</tbody></table></div></details>")
    gora = (f'<div class="gora"><p class="glowne">{glowne}</p><div><p class="agenci">{e(zdanie_agentow(st))}</p>'
            f'<p class="podpis">od wpłynięcia rozmowy do wdrożonej poprawki</p></div></div>')
    return strona("Klienci", gora + tabela + szczegoly, dane, 0, h1=False)


# ── strona klienta ────────────────────────────────────────────────────────────

def os_czasu(dane, klient):
    """Wpisy [(ISO czas, rodzaj, tytuł HTML, szczegóły HTML)] od najnowszych."""
    wpisy, slug = [], klient["slug"]
    for w in klient["wyniki"]:
        d = w["dane"]
        sp = d.get("spotkanie") or {}
        data = sp.get("data") or d.get("wygenerowano") or ""
        zrodlo = str(d.get("zrodlo", ""))
        rodzaj = "Mail" if "/maile/" in zrodlo else "Rozmowa"
        tytul = sp.get("tytul") or w["folder"]
        lacze = f'<a href="../{e(w["raport"])}">{e(tytul)}</a>' if w["raport"] else e(tytul)
        poz = d.get("pozycje") or []
        wpisy.append((data, rodzaj, lacze, f"pozycji w raporcie: {len(poz)}" + (f", zmian zdania: {len(d.get('zmiany_zdania') or [])}" if d.get("zmiany_zdania") else "")))
        for z in d.get("zmiany_zdania") or []:
            wpisy.append((data, "Zmiana zdania", e(z.get("temat", "")),
                          f'{e(z.get("przed", ""))} → <b>{e(z.get("po", ""))}</b>' + (f'<blockquote>{e(z["cytat"])}</blockquote>' if z.get("cytat") else "")))
    for h in klient["karta"].get("historia_wysylek") or []:
        wpisy.append((str(h.get("data", "")), "Wysłany mail", e(h.get("temat", "")),
                      f'do: {e(h.get("do", ""))}' + (" · zaproszenie .ics" if h.get("zaproszenie_ics") else "")
                      + (f' · załączniki: {e(", ".join(h["zalaczniki"]))}' if h.get("zalaczniki") else "")))
    for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):          # regresje: naprawiona sprawa wróciła
        for klucz, wpis in (klient["karta"].get(sekcja) or {}).items():
            for r in (wpis.get("regresje") or []) if isinstance(wpis, dict) else []:
                wpisy.append((str(r.get("data", "")), "Regresja", f'<a href="{e(wpis.get("url", "#"))}">{e(wpis.get("tytul", klucz))}</a>',
                              f'<span class="tag bad">regresja</span> wróciło w źródle {e(Path(str(r.get("zrodlo", ""))).name)}'
                              + (f'<blockquote>{e(r["cytat"])}</blockquote>' if r.get("cytat") else "")))
    prs = defaultdict(list)
    for z in dane["zdarzenia"]:
        if z.get("klient") != slug:
            continue
        if z["typ"].startswith("pr_"):
            prs[z.get("url") or z.get("zgloszenie")].append(z)
            continue
        url = z.get("url") or ""
        lacze = f'<a href="../{e(url)}">{e(z.get("tytul", ""))}</a>' if url else e(z.get("tytul", ""))
        rodzaj = "Notatka" if z["typ"] == "notatka" else "Materiał"
        wpisy.append((z["data"], rodzaj, lacze, f'{e(NAZWY_ZDARZEN.get(z["typ"], z["typ"]))} · zgłoszenie {e(z.get("zgloszenie", ""))}'))
    for url, ev in prs.items():                      # jedna pozycja na PR, z końcowym statusem
        ev = sorted(ev, key=lambda x: x["data"])
        scalony = next((x for x in ev if x["typ"] == "pr_scalony"), None)
        if scalony:
            status, kiedy = "scalona", scalony["data"]
        elif ev[-1]["typ"] == "pr_oddany":
            status, kiedy = "oddana człowiekowi", ev[-1]["data"]
        else:
            status, kiedy = "otwarta", ev[-1]["data"]
        lacze = f'<a href="{e(url)}">{e(ev[-1].get("tytul", ""))}</a>' if str(url).startswith("http") else e(ev[-1].get("tytul", ""))
        wpisy.append((kiedy, "Poprawka agenta", lacze, f'PR <b>{e(status)}</b> · zgłoszenie {e(ev[-1].get("zgloszenie", ""))}'))
    return sorted(wpisy, key=lambda w: w[0], reverse=True)


def strona_klienta(dane, klient):
    k, slug, dzis = klient["karta"], klient["slug"], dane["dzis"]
    s = sprawy_klienta(dane, slug)
    kolor, powody = swiatlo(dane, klient)
    nazwa_sw = SWIATLO[kolor][0]
    opis_sw = f"{nazwa_sw}: " + ("; ".join(powody) if powody else SWIATLO[kolor][1])
    czesci = [f'<p class="sub"><span class="dot {kolor}" title="{e(opis_sw)}"></span>{e("; ".join(powody)) if powody else "Bez uwag"}</p>']

    czesci.append("<h2>Teraz</h2><div class=\"now3\">"
                  f'<div><h3>Wymaga Ciebie <span class="tag">{len(s["czlowiek"])}</span></h3>{_lista_zgloszen(s["czlowiek"], dzis, "Nic nie czeka na człowieka.")}</div>'
                  f'<div><h3>U agentów <span class="tag">{len(s["agent"])}</span></h3>{_lista_zgloszen(s["agent"], dzis, "Agenci nie mają teraz zadań.")}</div>'
                  f'<div><h3>Czeka na klienta <span class="tag">{len(s["czeka"])}</span></h3>{_lista_zgloszen(s["czeka"], dzis, "Nie czekamy na klienta.")}</div></div>'
                  + (f'<p class="sub">W backlogu: {len(s["backlog"])} (prośby produktowe i pomysły: <a href="../glos-klientow.html">Głos klientów</a>).</p>' if s["backlog"] else ""))

    ot = os_czasu(dane, klient)
    czesci.append("<h2>Oś czasu</h2>" + ("<ul class=\"tl\">" + "".join(
        f'<li><time>{e(str(d)[:10])}</time><div><span class="kind">{e(r)}</span>{t}<div class="sub" style="margin:2px 0 0">{sz}</div></div></li>'
        for d, r, t, sz in ot) + "</ul>" if ot else '<p class="empty">Brak wpisów.</p>'))

    zak, wygasle = zakazy_czas.stan_zakazow(k, dzis, slug, dane.get("root", "."))
    czesci.append(f"<h2>Zakazy aktywne ({len(zak)})</h2>" + ("".join(
        f'<div class="panel"><h3>{e(z.get("id", ""))}: {e(z.get("tytul", ""))}'
        + (f' <span class="tag warn">do {e(zakazy_czas.okres_zakazu(z, slug, dane.get("root", "."), dzis)["do"].isoformat())}</span>'
           if zakazy_czas.okres_zakazu(z, slug, dane.get("root", "."), dzis) else "") + '</h3>'
        + (f'<p class="sub" style="margin:4px 0">{e(z["opis"])}</p>' if z.get("opis") else "")
        + "".join(f"<blockquote>{e(c)}</blockquote>" for c in (z.get("cytat") or [])[:2]) + "</div>" for z in zak) if zak else '<p class="empty">Brak aktywnych zakazów.</p>'))
    czesci.append(f"<h2>Wygasłe zakazy ({len(wygasle)})</h2>" + ("".join(
        f'<div class="panel"><h3>{e(z.get("id", ""))}: {e(z.get("tytul", ""))} <span class="tag">wygasł {e(z.get("wygasl", ""))}</span></h3>'
        + (f'<p class="sub" style="margin:4px 0">Okres: {e((z.get("okres") or {}).get("od", ""))} – {e((z.get("okres") or {}).get("do", ""))}'
           f' ({e((z.get("okres") or {}).get("skad", ""))})</p>' if z.get("okres") else "")
        + "".join(f"<blockquote>{e(c)}</blockquote>" for c in (z.get("cytat") or [])[:2]) + "</div>" for z in wygasle)
        if wygasle else '<p class="empty">Żaden zakaz czasowy jeszcze nie wygasł.</p>'))
    hist = k.get("historia_zakazow") or []
    czesci.append(f"<h2>Uchylone zakazy ({len(hist)})</h2>" + ("".join(
        f'<div class="panel"><h3>{e(z.get("id", ""))}: {e(z.get("tytul", ""))} <span class="tag ok">uchylony {e(z.get("kiedy", ""))}</span></h3>'
        + "".join(f"<blockquote>{e(c)}</blockquote>" for c in (z.get("cytat") or [])[:1])
        + (f'<p class="sub" style="margin:6px 0 0">Uchylenie: „{e(z["uchylony"])}”</p>' if z.get("uchylony") else "") + "</div>" for z in hist)
        if hist else '<p class="empty">Żaden zakaz nie został uchylony.</p>'))

    ryz = ryzyka_klienta(klient)
    czesci.append(f"<h2>Ryzyka ({len(ryz)})</h2>" + ("".join(
        f'<div class="panel"><h3>{e(TEMATY_RYZYKA.get(t, t))} <span class="tag {"bad" if wystapienia(w) >= 2 else "warn"}">{wystapienia(w)} {"wystąpienie" if wystapienia(w) == 1 else "wystąpienia" if wystapienia(w) < 5 else "wystąpień"}</span></h3>'
        f'<p class="sub" style="margin:4px 0">{e(", ".join(sorted({x.get("data", "") for x in w})))}</p>'
        + "".join(f"<blockquote>{e(x.get('cytat', ''))}</blockquote>" for x in w) + "</div>" for t, w in ryz) if ryz else '<p class="empty">Brak zapisanych ryzyk.</p>'))

    kont = k.get("kontakty") or []
    dec = k.get("decydenci") or []
    wiersze = []
    for c in kont:
        nieob = "; ".join(f"nieobecność {n['od']} – {n['do']}" for n in c.get("nieobecnosci", []))
        wiersze.append(f"<li><b>{e(c.get('imie', ''))}</b>, {e(c.get('rola', ''))} <span class=\"tag {'ok' if c.get('potwierdzony') else 'warn'}\">"
                       f"{e('kontakt potwierdzony' if c.get('potwierdzony') else 'niepotwierdzony')}</span>"
                       + (f" <span class=\"tag\">{e(nieob)}</span>" if nieob else "") + "</li>")
    czesci.append("<h2>Kontakty i decydenci</h2><div class=\"panel\"><h3>Kontakty</h3>"
                  + (f"<ul>{''.join(wiersze)}</ul>" if wiersze else '<p class="empty">Brak potwierdzonych kontaktów w karcie.</p>')
                  + "<h3 style=\"margin-top:12px\">Decydenci</h3>"
                  + ("<ul>" + "".join(f"<li><b>{e(d.get('imie', ''))}</b>, {e(d.get('rola', ''))}</li>" for d in dec) + "</ul>" if dec else '<p class="empty">Brak.</p>')
                  + "</div>")
    return strona(nazwa_klienta(klient), "".join(czesci), dane, 1)


# ── głos klientów ─────────────────────────────────────────────────────────────

def status_prosby(dane, klucz_funkcji):
    """„zrobione”, „u agenta” albo „backlog” z powiązanych zgłoszeń w stanie Lineara (klucz funkcji → sprawy z wyników → karta)."""
    E = dane["Z"]["etykiety"]
    ident = set()
    for slug, k in dane["klienci"].items():
        klucze = set()
        for w in k["wyniki"]:
            for p in (w["dane"].get("pozycje") or []):
                if p.get("klucz_funkcji") == klucz_funkcji and p.get("klucz_sprawy"):
                    klucze.add(p["klucz_sprawy"])
        for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):
            for kl, wpis in (k["karta"].get(sekcja) or {}).items():
                if kl in klucze and isinstance(wpis, dict) and wpis.get("identifier"):
                    ident.add(wpis["identifier"])
    zgl = [dane["stan"]["zgloszenia"][i] for i in sorted(ident) if i in dane["stan"]["zgloszenia"]]
    if zgl and all(z["stan"] == "Done" for z in zgl):
        return "zrobione", sorted(ident)
    if any(z["stan"] in STANY_AKTYWNE and E["agent"] in z["etykiety"] for z in zgl):
        return "u agenta", sorted(ident)
    return "backlog", sorted(ident)


def prosby_posortowane(dane):
    wynik = []
    for klucz, p in (dane["prosby"] or {}).items():
        prosby = p.get("prosby") or []
        klienci = sorted({x.get("klient", "") for x in prosby})
        daty = sorted(x.get("data", "") for x in prosby if x.get("data"))
        status, ident = status_prosby(dane, klucz)
        wynik.append({"klucz": klucz, "tytul": p.get("tytul", klucz), "klienci": klienci, "prosby": prosby,
                      "pierwsza": daty[0] if daty else "", "ostatnia": daty[-1] if daty else "", "status": status, "zgloszenia": ident})
    # stabilnie: najpierw tytuł, potem najnowsza prośba, potem liczba próśb, na końcu liczba klientów (najważniejsza)
    wynik.sort(key=lambda x: x["tytul"])
    wynik.sort(key=lambda x: x["ostatnia"], reverse=True)
    wynik.sort(key=lambda x: len(x["prosby"]), reverse=True)
    wynik.sort(key=lambda x: len(x["klienci"]), reverse=True)
    return wynik


def _tekst_prosby(x, klient=None):
    return " ".join([x["tytul"]] + [p.get("cytat", "") for p in x["prosby"] if klient in (None, p.get("klient"))]).lower()


def sygnaly(dane):
    """Sygnały w głosie klientów, od najsilniejszego (maks. G.max_sygnalow), oraz reszta próśb.

    Typy: "uratuje" (prośba klienta z aktywnym ryzykiem utraty dotyczy tego, co oferuje konkurencja z ryzyka),
    "wielu" (prosi co najmniej 2 klientów), "powtarza" (ten sam klient w co najmniej 2 różnych rozmowach lub mailach).
    Zwraca (sygnały, pozostałe); każdy sygnał: klucz, tytul, typy, powod, klienci, cytat, status, zgloszenia."""
    G = dane["Z"].get("glos", {})
    wynik, reszta = [], []
    for x in prosby_posortowane(dane):
        typy, powody, ocalony = [], [], None
        for slug in x["klienci"]:                                  # (1) może uratować klienta
            klient = dane["klienci"].get(slug)
            if not klient:
                continue
            ryzyka = [r for t, w in ryzyka_klienta(klient) if t in G.get("tematy_ryzyka_utraty", []) for r in w]
            tekst_ryzyka = " ".join(r.get("cytat", "") for r in ryzyka).lower()
            tekst_prosby = _tekst_prosby(x, slug)
            for nazwa, slowa in G.get("tematy_konkurencji", {}).items():
                if ryzyka and any(r in tekst_ryzyka for r in slowa["ryzyko"]) and any(r in tekst_prosby for r in slowa["prosba"]):
                    ocalony = (slug, nazwa)
                    break
            if ocalony:
                break
        if ocalony:
            typy.append("uratuje")
            powody.append(f"może uratować klienta {nazwa_klienta(dane['klienci'][ocalony[0]])}: ma aktywne ryzyko utraty, a prośba dotyczy tego, "
                          f"co oferuje konkurencja ({ocalony[1]})")
        if len(x["klienci"]) >= G.get("min_klientow", 2):
            typy.append("wielu")
            powody.append(f"prosi {len(x['klienci'])} klientów: " + ", ".join(nazwa_klienta(dane["klienci"][k]) if k in dane["klienci"] else k for k in x["klienci"]))
        for slug in x["klienci"]:
            zrodla = {p.get("zrodlo") for p in x["prosby"] if p.get("klient") == slug}
            if len(zrodla) >= G.get("min_zrodel_klienta", 2):
                typy.append("powtarza")
                powody.append(f"{nazwa_klienta(dane['klienci'][slug]) if slug in dane['klienci'] else slug} prosi w {len(zrodla)} różnych rozmowach lub mailach")
                break
        if typy:
            # najważniejszy cytat: od klienta zagrożonego, inaczej najnowszy
            wybor = [p for p in x["prosby"] if ocalony and p.get("klient") == ocalony[0]] or sorted(x["prosby"], key=lambda p: p.get("data", ""))[-1:]
            wynik.append({**x, "typy": typy, "powod": "; ".join(powody[:2]), "cytat": wybor[-1] if wybor else None, "ocalony": ocalony})
        else:
            reszta.append(x)
    wynik.sort(key=lambda g: ("uratuje" in g["typy"], "wielu" in g["typy"], "powtarza" in g["typy"], len(g["klienci"]), len(g["prosby"]), g["ostatnia"]), reverse=True)
    limit = G.get("max_sygnalow", 5)
    return wynik[:limit], reszta + wynik[limit:]


def klucze_sygnalow(lista):
    """Pary „klucz|typ” – nowy sygnał to taka, której jeszcze nie widziano."""
    return {f"{g['klucz']}|{t}" for g in lista for t in g["typy"]}


def nowe_sygnaly(lista, stan):
    """Sygnały, które po raz pierwszy spełniają warunek (zob. klucze_sygnalow). stan None = pierwsze uruchomienie (baza bez ogłaszania)."""
    if stan is None:
        return []
    widziane = set(stan.get("widziane", []))
    return [g for g in lista if any(f"{g['klucz']}|{t}" not in widziane for t in g["typy"])]


def _nazwy_klientow(dane, slugi):
    return ", ".join(nazwa_klienta(dane["klienci"][k]) if k in dane["klienci"] else k for k in slugi)


def dlaczego_sygnal(dane, g):
    """Krótko, dlaczego to sygnał: „może uratować klienta Grupa Auto Tama, konkurencja to ma”, „prosi 2 klientów”, „… prosi w 2 rozmowach lub mailach”."""
    czesci = []
    if "uratuje" in g["typy"] and g.get("ocalony"):
        slug = g["ocalony"][0]
        czesci.append(f"może uratować klienta {nazwa_klienta(dane['klienci'][slug]) if slug in dane['klienci'] else slug}, konkurencja to ma")
    if "wielu" in g["typy"]:
        czesci.append(f"prosi {len(g['klienci'])} klientów")
    if "powtarza" in g["typy"]:
        for slug in g["klienci"]:
            zrodla = {p.get("zrodlo") for p in g["prosby"] if p.get("klient") == slug}
            if len(zrodla) >= dane["Z"].get("glos", {}).get("min_zrodel_klienta", 2):
                czesci.append(f"{nazwa_klienta(dane['klienci'][slug]) if slug in dane['klienci'] else slug} prosi w {len(zrodla)} rozmowach lub mailach")
                break
    return "; ".join(czesci[:2]) or g["powod"]


def wiersz_sygnalu(dane, g):
    prop = (dane.get("propozycje") or {}).get(g["klucz"])
    if prop:                                                  # każdy sygnał linkuje do propozycji produktowej (propozycje.py)
        pdf = f'{dane["Z"]["propozycje"]["katalog"]}/{g["klucz"]}.pdf'          # względem katalogu głównego stron
        propozycja = f'<a href="{e(pdf)}">Propozycja</a><span class="tag">{e(str(prop.get("status", "")).replace("_", " "))}</span>'
    else:
        propozycja = '<span class="empty">w przygotowaniu</span>'
    c = g["cytat"] or {}
    cytat = (f'<tr><td colspan="4" style="border-bottom:1px solid var(--line);padding-top:0"><details><summary>Cytat klienta</summary>'
             f'<blockquote>{e(c.get("cytat", ""))}<br><small>{e(_nazwy_klientow(dane, [c["klient"]]) if c.get("klient") else "")}, {e(c.get("data", ""))}</small></blockquote>'
             f'</details></td></tr>') if c.get("cytat") else ""
    return (f'<tr class="sygnal"><td><b>{e(g["tytul"])}</b></td><td>{e(dlaczego_sygnal(dane, g))}</td><td class="n">{len(g["klienci"])}</td><td>{propozycja}</td></tr>'
            + cytat)


def strona_glos(dane):
    sygn, reszta = sygnaly(dane)
    n = len(sygn)
    if n == 0:
        zdanie = "Brak sygnałów wartych decyzji"
    else:
        zdanie = f"{n} {forma_liczby(n, 'sygnał wart', 'sygnały warte', 'sygnałów wartych')} decyzji"
    tabela = ('<div class="tabela"><table class="klienci"><thead><tr><th>Funkcja</th><th>Dlaczego to sygnał</th><th class="n">Klientów</th><th>Propozycja</th></tr></thead><tbody>'
              + "".join(wiersz_sygnalu(dane, g) for g in sygn) + "</tbody></table></div>") if sygn else \
        '<p class="empty">Na razie żadnych sygnałów: wszystkie prośby są pojedyncze.</p>'
    pozostale = ""
    if reszta:
        tytuly = ", ".join(x["tytul"] for x in reszta)
        wiersze = "".join(f'<li><b>{e(x["tytul"])}</b> <span class="tag">{e(_nazwy_klientow(dane, x["klienci"]))}</span>'
                          f'<blockquote>{e((x["prosby"][-1] if x["prosby"] else {}).get("cytat", ""))}</blockquote></li>' for x in reszta)
        pozostale = (f'<details style="margin-top:36px"><summary class="jedna">Pozostałe pojedyncze prośby ({len(reszta)}): {e(tytuly)}</summary>'
                     f'<ul style="margin-top:12px">{wiersze}</ul></details>')
    gora = f'<div class="gora"><p class="glowne">{e(zdanie)}</p></div>'
    return strona("Głos klientów", gora + tabela + pozostale, dane, 0, h1=False)


# ── agenci w tym tygodniu ─────────────────────────────────────────────────────

def czas_zrodla(dane, klient_slug, zrodla):
    """Najwcześniejszy moment WPŁYNIĘCIA źródła do systemu (rozmowy albo maila): czas commita zapisany w rejestrze ops/.przetworzone.json
    (pole „wplynelo”), a nie data rozmowy z nazwy pliku. None, gdy żadne źródło nie ma zapisanego wpłynięcia."""
    import wplyniecia
    mapa = wplyniecia.mapa(dane.get("przetworzone"))
    momenty = []
    for z in zrodla:
        txt = mapa.get(Path(str(z)).as_posix())
        if txt:
            try:
                momenty.append(_jako_czas(txt))
            except ValueError:
                pass
    return min(momenty) if momenty else None


def _jako_czas(txt):
    return datetime.fromisoformat(txt.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Warsaw"))


def formatuj_czas(td):
    minuty = int(td.total_seconds() // 60)
    d, reszta = divmod(minuty, 1440)
    h, m = divmod(reszta, 60)
    if d:
        return f"{d} d {h} h"
    return f"{h} h {m} min" if h else f"{m} min"


def statystyki_agentow(dane):
    """Ostatnie 7 dni: liczba zamkniętych spraw, średni i najkrótszy czas od źródła do scalenia poprawki (z kart, zdarzeń i Lineara)."""
    dzis = dane["dzis"]
    od = datetime(dzis.year, dzis.month, dzis.day, tzinfo=ZoneInfo("Europe/Warsaw")) - timedelta(days=7)
    do = datetime(dzis.year, dzis.month, dzis.day, tzinfo=ZoneInfo("Europe/Warsaw")) + timedelta(days=1)
    zamkniete = [i for i, z in dane["stan"]["zgloszenia"].items()
                 if z["stan"] == "Done" and z.get("zamknieto") and od <= _jako_czas(z["zamknieto"]) < do]
    sprawy = {}
    for slug, k in dane["klienci"].items():
        for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):
            for wpis in (k["karta"].get(sekcja) or {}).values():
                if isinstance(wpis, dict) and wpis.get("identifier"):
                    sprawy[wpis["identifier"]] = (slug, wpis.get("zrodla") or [])
    pomiary = []
    for z in dane["zdarzenia"]:
        if z["typ"] != "pr_scalony" or z.get("zgloszenie") not in sprawy:
            continue
        scalono = _jako_czas(z["data"])
        slug, zrodla = sprawy[z["zgloszenie"]]
        start = czas_zrodla(dane, slug, zrodla)
        if start and od <= scalono < do and scalono >= start:
            pomiary.append({"zgloszenie": z["zgloszenie"], "tytul": z.get("tytul", ""), "url": z.get("url"), "czas": scalono - start})
    return {"zamkniete": len(zamkniete), "scalone": len(pomiary), "pomiary": pomiary}


# ── powiadomienie o nowych sygnałach ──────────────────────────────────────────

def linie_nowych_sygnalow(nowe, dane):
    baza = dane["Z"].get("strony", {}).get("url_bazowy", "").rstrip("/")
    url = f"{baza}/glos-klientow.html" if baza else "glos-klientow.html"
    return [f":bulb: Nowy sygnał w głosie klientów: {sw.link(url, g['tytul'], 60)}, {g['powod'].split(':')[0] if g['powod'].startswith('prosi') else g['powod']}"
            for g in nowe]


def powiadom_o_sygnalach(dane, wyslij=None, root="."):
    """Jedna linijka na Slacku dla każdego NOWEGO sygnału (pierwszy raz spełnia warunek), nie codziennie. Stan w ops/.sygnaly.json.
    Pierwsze uruchomienie (brak pliku) tylko zapisuje bazę. Stan rośnie dopiero po udanej wysyłce, więc nieudane powiadomienie wróci.
    Zwraca listę wysłanych linijek."""
    plik = Path(root) / "ops/.sygnaly.json"
    sygn, _ = sygnaly(dane)
    stan = dane.get("sygnaly_stan")
    teraz = {"widziane": sorted(set((stan or {}).get("widziane", [])) | klucze_sygnalow(sygn)),
             "zainicjowano": (stan or {}).get("zainicjowano") or dane["dzis"].isoformat()}
    nowe = nowe_sygnaly(sygn, stan)
    wyslane = []
    if nowe and wyslij is not None:
        linie = linie_nowych_sygnalow(nowe, dane)
        if wyslij("\n".join(linie), linie):
            wyslane = linie
        else:
            teraz["widziane"] = sorted(set((stan or {}).get("widziane", [])))        # nie oznaczaj: spróbujemy przy następnym przebiegu
    elif nowe:
        teraz["widziane"] = sorted(set((stan or {}).get("widziane", [])))
    if stan is None or teraz != stan:
        plik.parent.mkdir(parents=True, exist_ok=True)
        plik.write_text(json.dumps(teraz, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return wyslane


def wyslij_slack(tekst, linie):
    """Wysyła wiadomość Slack (jeśli jest webhook). True przy sukcesie."""
    import os
    if not os.environ.get("SLACK_WEBHOOK_URL"):
        return False
    from przetworz import send_slack
    ok, _ = send_slack(tekst, blocks=sw.bloki(linie))
    return bool(ok)


# ── zapis ─────────────────────────────────────────────────────────────────────

def buduj(dane):
    """{ścieżka względna: HTML}."""
    strony = {"index.html": strona_index(dane), "glos-klientow.html": strona_glos(dane)}
    for slug, k in dane["klienci"].items():
        strony[f"klienci/{slug}.html"] = strona_klienta(dane, k)
    return strony


def zapisz(strony, root="."):
    root = Path(root)
    (root / "klienci").mkdir(parents=True, exist_ok=True)
    zmienione = 0
    for sciezka, tresc in strony.items():
        p = root / sciezka
        if not p.exists() or p.read_text(encoding="utf-8") != tresc:
            p.write_text(tresc, encoding="utf-8")
            zmienione += 1
    return zmienione


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Generuje statyczne strony (GitHub Pages).")
    ap.add_argument("--dzien", help="udawany dzisiejszy dzień RRRR-MM-DD")
    ap.add_argument("--bez-slacka", action="store_true", help="nie ogłaszaj nowych sygnałów na Slacku (stan sygnałów też się nie zmienia)")
    args = ap.parse_args()
    dane = wczytaj_dane(".", date.fromisoformat(args.dzien) if args.dzien else None)
    strony = buduj(dane)
    n = zapisz(strony)
    print(f"Strony: {len(strony)} ({n} zmienionych): " + ", ".join(sorted(strony)))
    if not args.bez_slacka:
        for l in powiadom_o_sygnalach(dane, wyslij_slack):
            print("Slack:", l)


if __name__ == "__main__":
    main()
