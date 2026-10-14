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
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mut:#62615c;--line:#e3e1db;--acc:#2f5bd3;--accbg:#e8eefc;
--ok:#0f7a43;--okbg:#e2f4ea;--warn:#9a5b00;--warnbg:#fdf0d9;--bad:#b42318;--badbg:#fde7e5;--back:#5b4bb7;--backbg:#ece9fb;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;--mut:#a3a29b;--line:#34332f;--acc:#8aa8ff;--accbg:#232c45;
--ok:#6fd39c;--okbg:#173326;--warn:#f3b75a;--warnbg:#382a12;--bad:#ff8a80;--badbg:#3d1d1a;--back:#b3a8ff;--backbg:#2a2545;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:1.55rem;margin:0 0 4px;letter-spacing:-.01em} h2{font-size:1.2rem;margin:30px 0 10px} h3{font-size:1rem;margin:0}
.meta,.sub{color:var(--mut);margin:0 0 18px} nav{margin:0 0 18px;font-size:.9rem} nav a{margin-right:14px}
a{color:var(--acc)} .demo{display:inline-block;font-size:.78rem;font-weight:600;color:var(--warn);background:var(--warnbg);padding:2px 10px;border-radius:99px;margin-bottom:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
a.card{text-decoration:none;color:inherit;display:block} a.card:hover{border-color:var(--acc)}
.card header{display:flex;gap:10px;align-items:center;margin-bottom:8px}
.dot{width:14px;height:14px;border-radius:50%;flex:none} .dot.czerwone{background:var(--bad)} .dot.zolte{background:#e0a100} .dot.zielone{background:var(--ok)}
.nums{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px} .num{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:4px 10px;font-size:.82rem;color:var(--mut)}
.num b{font-size:1.1rem;color:var(--ink);margin-right:4px}
.why{font-size:.83rem;color:var(--mut);margin:6px 0 0}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.panel h3{margin-bottom:8px} ul{margin:0;padding-left:20px} li{margin:0 0 8px}
.now3{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.tag{display:inline-block;font-size:.72rem;padding:1px 8px;border-radius:99px;background:var(--bg);border:1px solid var(--line);color:var(--mut);margin-left:4px}
.tag.bad{background:var(--badbg);color:var(--bad);border-color:transparent} .tag.ok{background:var(--okbg);color:var(--ok);border-color:transparent}
.tag.warn{background:var(--warnbg);color:var(--warn);border-color:transparent} .tag.back{background:var(--backbg);color:var(--back);border-color:transparent}
blockquote{margin:6px 0 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--mut);font-style:italic;font-size:.88rem}
.tl{list-style:none;padding:0;margin:0} .tl li{display:grid;grid-template-columns:92px 1fr;gap:4px 12px;padding:10px 0;border-bottom:1px solid var(--line);margin:0}
.tl time{color:var(--mut);font-size:.85rem} @media (max-width:520px){.tl li{grid-template-columns:1fr}}
.kind{font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--back);margin-right:6px}
.empty{color:var(--mut)} footer{margin-top:36px;color:var(--mut);font-size:.85rem}
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
            "sygnaly_stan": _json(root / "ops/.sygnaly.json", None)}


def nazwa_klienta(klient):
    """Nazwa do wyświetlania: pole „nazwa” z karty, a bez niego slug z dużymi literami."""
    return klient["karta"].get("nazwa") or klient["slug"].replace("-", " ").title()


def bez_prefiksu(tytul):
    t = str(tytul or "")
    return t.split("] ", 1)[1] if t.startswith("[") and "] " in t else t


def sprawy_klienta(dane, slug):
    """Zgłoszenia klienta z pliku stanu Lineara, podzielone na: czlowiek, agent, czeka (otwarte) oraz zamkniete."""
    E = dane["Z"]["etykiety"]
    czlowiek_et = {E["czlowiek"], E["weryfikacja"], E["zablokowane"]}
    wynik = {"czlowiek": [], "agent": [], "czeka": [], "backlog": [], "inne": [], "zamkniete": []}
    for ident, z in sorted(dane["stan"]["zgloszenia"].items(), key=lambda kv: int(kv[0].split("-")[1])):
        if not z["tytul"].startswith(f"[{slug}]"):
            continue
        z = {**z, "id": ident}
        if z["stan"] in STANY_ZAMKNIETE:
            wynik["zamkniete"].append(z)
            continue
        et = set(z["etykiety"])
        if E["czeka"] in et:
            wynik["czeka"].append(z)
        elif z["stan"] == "Backlog":
            wynik["backlog"].append(z)
        elif et & czlowiek_et:
            wynik["czlowiek"].append(z)
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
        wiersze.append(f"<li>{_link_zgloszenia(z)} <span class=\"tag\">{e(z['stan'])}</span>{dod}</li>")
    return "<ul>" + "".join(wiersze) + "</ul>"


def strona(tytul, tresc, dane, poziom=0, opis=""):
    pre = "../" * poziom
    zapisano = dane["stan"].get("zapisano") or "brak"
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(tytul)}</title><meta name="robots" content="noindex"><style>{CSS}</style></head><body><div class="wrap">
<span class="demo">dane fikcyjne, demo</span>
<nav><a href="{pre}index.html">Klienci</a><a href="{pre}glos-klientow.html">Głos klientów</a></nav>
<h1>{e(tytul)}</h1>{f'<p class="meta">{e(opis)}</p>' if opis else ''}
{tresc}
<footer>Dane fikcyjne, demo. Strona wygenerowana automatycznie; stan Lineara z {e(zapisano)}. Adresy e-mail kontaktów celowo nie są publikowane.</footer>
</div></body></html>
"""


# ── strona główna ─────────────────────────────────────────────────────────────

def strona_index(dane):
    karty = []
    for slug, k in sorted(dane["klienci"].items()):
        kolor, powody = swiatlo(dane, k)
        s = sprawy_klienta(dane, slug)
        nazwa, opis_koloru = SWIATLO[kolor]
        karty.append(f"""<a class="card" href="klienci/{e(slug)}.html"><header><span class="dot {kolor}" title="{e(nazwa)}"></span>
<h3>{e(nazwa_klienta(k))}</h3><span class="tag">{e(nazwa)}</span></header>
<div class="nums"><span class="num"><b>{len(s['agent'])}</b>u agentów</span><span class="num"><b>{len(s['czlowiek'])}</b>u człowieka</span>
<span class="num"><b>{len(s['czeka'])}</b>czeka na klienta</span></div>
<p class="why">{e('; '.join(powody) if powody else opis_koloru)}</p></a>""")
    legenda = " · ".join(f'<span class="dot {k}" style="display:inline-block;vertical-align:middle"></span> {e(v[0])}: {e(v[1])}'
                         for k, v in SWIATLO.items())
    tresc = (f'<div class="grid">{"".join(karty) or "<p class=empty>Brak klientów.</p>"}</div><p class="sub" style="margin-top:18px">{legenda}</p>'
             + sekcja_agentow(dane))
    return strona("Klienci", tresc, dane, 0, "Jedno miejsce na wszystko o kliencie: sprawy, rozmowy, zakazy, ryzyka i kontakty.")


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
    czesci = [f'<p><span class="dot {kolor}" style="display:inline-block;vertical-align:middle"></span> <b>{e(nazwa_sw)}</b>'
              f'{": " + e("; ".join(powody)) if powody else ""}</p>']

    czesci.append("<h2>Teraz</h2><div class=\"now3\">"
                  f'<div class="panel"><h3>Wymaga człowieka ({len(s["czlowiek"])})</h3>{_lista_zgloszen(s["czlowiek"], dzis, "Nic nie czeka na człowieka.")}</div>'
                  f'<div class="panel"><h3>U agentów ({len(s["agent"])})</h3>{_lista_zgloszen(s["agent"], dzis, "Agenci nie mają teraz zadań.")}</div>'
                  f'<div class="panel"><h3>Czeka na klienta ({len(s["czeka"])})</h3>{_lista_zgloszen(s["czeka"], dzis, "Nie czekamy na klienta.")}</div></div>'
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
    return strona(nazwa_klienta(klient), "".join(czesci), dane, 1, f"Klient: {slug}")


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
            wynik.append({**x, "typy": typy, "powod": "; ".join(powody[:2]), "cytat": wybor[-1] if wybor else None})
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


def _karta_prosby(x):
    return f'<span class="tag">{len(x["klienci"])} {"klient" if len(x["klienci"]) == 1 else "klientów"}</span>'


def strona_glos(dane):
    sygn, reszta = sygnaly(dane)
    kolory = {"zrobione": "ok", "u agenta": "warn", "backlog": "back"}

    def zgl_html(x):
        return " ".join(f'<a class="tag" href="{e(dane["stan"]["zgloszenia"].get(i, {}).get("url", "#"))}">{e(i)}</a>' for i in x["zgloszenia"])

    karty = []
    for g in sygn:
        c = g["cytat"] or {}
        karty.append(f"""<div class="panel"><h3>{e(g['tytul'])} <span class="tag {kolory[g['status']]}">{e(g['status'])}</span></h3>
<p class="sub" style="margin:4px 0"><b>Dlaczego:</b> {e(g['powod'])}</p>
<p class="sub" style="margin:4px 0">Klienci: {e(', '.join(nazwa_klienta(dane['klienci'][k]) if k in dane['klienci'] else k for k in g['klienci']))}
· pierwsza prośba {e(g['pierwsza'])}, ostatnia {e(g['ostatnia'])} {zgl_html(g)}</p>
<blockquote>{e(c.get('cytat', ''))}<br><small>{e(c.get('klient', ''))}, {e(c.get('data', ''))}</small></blockquote></div>""")
    wstep = "".join(karty) or '<p class="empty">Na razie żadnych sygnałów: wszystkie prośby są pojedyncze.</p>'
    wiersze = "".join(
        f'<li><b>{e(x["tytul"])}</b> <span class="tag {kolory[x["status"]]}">{e(x["status"])}</span> '
        f'<span class="tag">{e(", ".join(nazwa_klienta(dane["klienci"][k]) if k in dane["klienci"] else k for k in x["klienci"]))}</span>'
        f'<blockquote>{e((x["prosby"][-1] if x["prosby"] else {}).get("cytat", ""))}</blockquote></li>' for x in reszta)
    pozostale = (f'<details><summary><b>Pozostałe ({len(reszta)})</b></summary><ul style="margin-top:10px">{wiersze}</ul></details>'
                 if reszta else "")
    return strona("Głos klientów", f"<h2 style=\"margin-top:0\">Sygnały ({len(sygn)})</h2>{wstep}{pozostale}", dane, 0,
                  "Tylko sygnały, najsilniejszy pierwszy: może uratować klienta, prosi co najmniej 2 klientów albo ten sam klient prosi w co najmniej 2 rozmowach lub mailach.")


# ── agenci w tym tygodniu ─────────────────────────────────────────────────────

def _godz_poczatku(wynik):
    m = re.match(r"\s*(\d{1,2}):(\d{2})", str((wynik.get("spotkanie") or {}).get("godziny", "")))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def czas_zrodla(dane, klient_slug, zrodla):
    """Najwcześniejszy moment źródła (rozmowy albo maila): data z nazwy pliku + godzina spotkania z wyniku, gdy jest."""
    najwczesniej = None
    for z in zrodla:
        d = zakazy_czas.data_z_nazwy(z)
        if not d:
            continue
        h = m_ = 0
        for w in dane["klienci"].get(klient_slug, {}).get("wyniki", []):
            if str(w["dane"].get("zrodlo", "")).endswith(Path(z).name):
                h, m_ = _godz_poczatku(w["dane"])
        moment = datetime(d.year, d.month, d.day, h, m_, tzinfo=ZoneInfo("Europe/Warsaw"))
        najwczesniej = moment if najwczesniej is None or moment < najwczesniej else najwczesniej
    return najwczesniej


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


def sekcja_agentow(dane):
    st = statystyki_agentow(dane)
    if not st["pomiary"]:
        szczegoly = "<p class=\"empty\">W tym tygodniu agenci nie scalili jeszcze żadnej poprawki.</p>"
    else:
        lacznie = sum((p["czas"] for p in st["pomiary"]), timedelta())
        sredni = lacznie / len(st["pomiary"])
        naj = min(st["pomiary"], key=lambda p: p["czas"])
        lacze = f'<a href="{e(naj["url"])}">{e(naj["tytul"])}</a>' if str(naj.get("url", "")).startswith("http") else e(naj["tytul"])
        szczegoly = (f'<div class="nums"><span class="num"><b>{st["scalone"]}</b>poprawek scalonych</span>'
                     f'<span class="num"><b>{e(formatuj_czas(sredni))}</b>średnio od źródła do scalenia</span>'
                     f'<span class="num"><b>{e(formatuj_czas(naj["czas"]))}</b>najkrócej</span></div>'
                     f'<p class="sub" style="margin:8px 0 0">Najszybsza: {lacze} <span class="tag">{e(naj["zgloszenie"])}</span></p>')
    return (f'<h2>Agenci w tym tygodniu</h2><div class="panel"><div class="nums"><span class="num"><b>{st["zamkniete"]}</b>zamkniętych spraw (7 dni)</span></div>'
            f'{szczegoly}<p class="why">Czas liczony od najwcześniejszego źródła sprawy (rozmowa lub mail, z kart klientów) do scalenia poprawki (dziennik zdarzeń). '
            f'Zamknięte sprawy z Lineara.</p></div>')


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
