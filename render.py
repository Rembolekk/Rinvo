"""Generuje raport.html z wynik.json (wynik komendy /analizuj).

Użycie:
  python -I render.py WYNIK_JSON [--transkrypcja PLIK] [--out RAPORT_HTML]

--transkrypcja  sprawdza, czy każdy cytat występuje dosłownie w transkrypcji;
                jeśli nie, kończy się błędem (kod 2) i nie zapisuje raportu.
--out           domyślnie raport.html obok WYNIK_JSON.

Skrypt nie zawiera żadnych nazw firm ani osób: wszystko pochodzi z JSON.
Schemat JSON opisuje komenda ~/.claude/commands/analizuj.md.
"""
import argparse, html, json, os, re, sys

STATUS = {"zrob_teraz": "zrób teraz", "czeka": "czeka", "backlog": "backlog", "nigdy": "nigdy"}
SECTIONS = [
    (1, "Do zrobienia teraz", "Zadania po stronie naszego zespołu, z właścicielem."),
    (2, "Czeka na klienta", "Dane, decyzje i potwierdzenia, na które czekamy. Podano datę i limit przypomnień, jeśli padły w rozmowie."),
    (3, "Backlog produktowy", "Pomysły i prośby o funkcje. Odróżniamy nową funkcję od zmiany istniejącej."),
    (4, "Zakazy i ograniczenia", "Czego dla tego klienta nie robimy albo czego nie robimy przed określonym terminem."),
    (5, "Ryzyka handlowe", "Co może zagrozić współpracy lub budżetowi."),
]
REQUIRED = ["id", "sekcja", "typ", "tytul", "wlasciciel", "termin", "warunek", "status", "cytat"]

e = lambda s: html.escape(str(s))
norm = lambda s: re.sub(r"\s+", " ", s).strip()


def validate(d):
    errs, ids = [], set()
    for i, p in enumerate(d.get("pozycje", [])):
        pid = p.get("id", f"#{i}")
        for k in REQUIRED:
            if k not in p:
                errs.append(f"{pid}: brak pola '{k}'")
        if p.get("id") in ids:
            errs.append(f"{pid}: zduplikowane id")
        ids.add(p.get("id"))
        if p.get("sekcja") not in (1, 2, 3, 4, 5):
            errs.append(f"{pid}: sekcja musi być 1–5")
        if p.get("status") not in STATUS:
            errs.append(f"{pid}: nieznany status '{p.get('status')}'")
        if not p.get("cytat"):
            errs.append(f"{pid}: brak cytatu")
        if not isinstance(p.get("wnioski", []), list):
            errs.append(f"{pid}: 'wnioski' musi być listą")
    if not d.get("pozycje"):
        errs.append("brak listy 'pozycje'")
    return errs


def verify_quotes(d, transcript):
    tr = norm(transcript.replace("**", ""))
    missing = []
    for p in d["pozycje"]:
        for q in p["cytat"]:
            if norm(q) not in tr:
                missing.append(f"{p['id']}: {q}")
    for z in d.get("zmiany_zdania", []):
        if z.get("cytat") and norm(z["cytat"]) not in tr:
            missing.append(f"zmiana '{z.get('temat')}': {z['cytat']}")
    return missing


def wnioski(ws):
    if not ws:
        return ""
    return '<ul class="infer">' + "".join(f'<li><span class="wn">wniosek</span>{e(w)}</li>' for w in ws) + "</ul>"


def card(p):
    meta = [("Właściciel", p["wlasciciel"]), ("Termin", p["termin"]), ("Warunek", p["warunek"])]
    if "przypomnienie" in p:
        r = p["przypomnienie"]
        txt = f'{r.get("data", "nie ustalono")} · limit: {r.get("limit", "nie ustalono")}'
        if r.get("uwagi"):
            txt += f' · {r["uwagi"]}'
        meta.append(("Przypomnienie", txt))
    rows = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in meta)
    tags = f'<span class="tag st-{e(p["status"])}">{e(STATUS[p["status"]])}</span><span class="tag">{e(p["typ"])}</span>'
    if p.get("rodzaj"):
        tags += f'<span class="tag kind">{e(p["rodzaj"])}</span>'
    ch = f'<p class="change">Zmiana zdania: {e(p["zmiana_zdania"])}</p>' if p.get("zmiana_zdania") else ""
    opis = f'<p class="desc">{e(p["opis"])}</p>' if p.get("opis") else ""
    quotes = "".join(f"<blockquote>„{e(q)}”</blockquote>" for q in p["cytat"])
    return f'''<article class="card" id="{e(p["id"])}">
<header><span class="pid">{e(p["id"])}</span><h3>{e(p["tytul"])}</h3></header>
<div class="tags">{tags}</div>{opis}{ch}{wnioski(p.get("wnioski"))}<dl>{rows}</dl>
<details><summary>Cytat ({len(p["cytat"])})</summary>{quotes}</details></article>'''


def render(d, verified):
    P = d["pozycje"]
    S = {k: [p for p in P if p["sekcja"] == k] for k in range(1, 6)}
    m = d.get("spotkanie", {})
    zmiany = d.get("zmiany_zdania", [])
    konflikty = d.get("konflikty_dat", [])

    tiles = "".join(f'<a class="tile" href="#s{k}"><b>{len(S[k])}</b><span>{e(t)}</span></a>' for k, t, _ in SECTIONS)
    tiles += f'<a class="tile alt" href="#zmiany"><b>{len(zmiany)}</b><span>Zmiany zdania</span></a>'
    tiles += f'<a class="tile alt" href="#konflikty"><b>{len(konflikty)}</b><span>Konflikty dat</span></a>'

    changes = "".join(
        f'<li><b>{e(z.get("temat", ""))}</b>' + (f' <a href="#{e(z["pozycja"])}">{e(z["pozycja"])}</a>' if z.get("pozycja") else "") +
        f'<br><span class="was">{e(z.get("przed", ""))}</span> → <span class="now">{e(z.get("po", ""))}</span>' +
        (f'<blockquote>„{e(z["cytat"])}”</blockquote>' if z.get("cytat") else "") + "</li>"
        for z in zmiany) or "<li>Nie wykryto zmian zdania.</li>"
    conf = "".join(
        f'<li>{e(c.get("opis", ""))} <span class="refs">' + " ".join(f'<a href="#{e(i)}">{e(i)}</a>' for i in c.get("pozycje", [])) + "</span>" + wnioski(c.get("wnioski")) + "</li>"
        for c in konflikty) or "<li>Nie wykryto konfliktów dat.</li>"

    secs = ""
    for k, t, sub in SECTIONS:
        body = "".join(card(p) for p in S[k]) or '<p class="sub">Brak pozycji.</p>'
        secs += f'<section id="s{k}"><h2><span class="num">{k}</span>{e(t)} <small>{len(S[k])}</small></h2><p class="sub">{e(sub)}</p><div class="grid">{body}</div></section>'
    mail = d.get("szkic_maila", "").strip() or "(brak szkicu maila w wynik.json)"
    secs += f'''<section id="s6"><h2><span class="num">6</span>Szkic maila podsumowującego do klienta</h2>
<p class="sub">Zawiera tylko ustalenia z rozmowy.</p>
<div class="mail"><button type="button" id="copy">Kopiuj</button><pre id="mailtxt">{e(mail)}</pre></div></section>'''

    ver = d.get("weryfikacja", {})
    ver_items = ver.get("usuniete_bez_cytatu", []) + ver.get("zastapione_lub_scalone", []) + ver.get("pominiete", [])
    verh = "".join(f"<li>{e(x)}</li>" for x in ver_items)
    usun = len(ver.get("usuniete_bez_cytatu", []))
    ver_txt = (f"Wszystkie {len(P)} pozycji mają dosłowny cytat, sprawdzony automatycznie z transkrypcją."
               if verified else f"{len(P)} pozycji. Cytatów nie porównano automatycznie z transkrypcją.")
    ver_txt += f" Usunięte z powodu braku cytatu: {usun}."
    n_wn = sum(len(p.get("wnioski", [])) for p in P) + sum(len(c.get("wnioski", [])) for c in konflikty)
    ver_txt += f" Wnioski, czyli stwierdzenia niewynikające wprost z cytatu, oznaczono etykietą „wniosek” ({n_wn})."

    title = m.get("tytul", "Analiza rozmowy z klientem")
    meta_bits = [b for b in [
        f'Spotkanie {m.get("data", "")}{", " + m["godziny"] if m.get("godziny") else ""}' if m.get("data") else "",
        "Uczestnicy: " + ", ".join(m["uczestnicy"]) if m.get("uczestnicy") else "",
        f'Raport z {d["wygenerowano"]}' if d.get("wygenerowano") else "",
    ] if b]

    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raport: {e(title)}</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mut:#62615c;--line:#e3e1db;--acc:#2f5bd3;--accbg:#e8eefc;
--now:#0f7a43;--nowbg:#e2f4ea;--wait:#9a5b00;--waitbg:#fdf0d9;--back:#5b4bb7;--backbg:#ece9fb;--no:#b42318;--nobg:#fde7e5;color-scheme:light}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;--mut:#a3a29b;--line:#34332f;--acc:#8aa8ff;--accbg:#232c45;
--now:#6fd39c;--nowbg:#173326;--wait:#f3b75a;--waitbg:#382a12;--back:#b3a8ff;--backbg:#2a2545;--no:#ff8a80;--nobg:#3d1d1a;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:1.6rem;margin:0 0 4px;letter-spacing:-.01em}}
.meta{{color:var(--mut);margin:0 0 24px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:28px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;text-decoration:none;color:inherit;display:flex;flex-direction:column}}
.tile b{{font-size:1.7rem;line-height:1.1}} .tile span{{color:var(--mut);font-size:.85rem}}
.tile.alt b{{color:var(--acc)}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:20px}}
.panel h2{{font-size:1.1rem;margin:0 0 10px}}
.panel ol,.panel ul{{margin:0;padding-left:20px}} .panel li{{margin:0 0 12px}}
.was{{text-decoration:line-through;color:var(--mut)}} .now{{color:var(--now);font-weight:600}}
.refs a,.panel li>a{{font:600 .75rem ui-monospace,Consolas,monospace;background:var(--accbg);color:var(--acc);padding:1px 6px;border-radius:5px;text-decoration:none;margin-left:2px}}
section{{margin-top:36px}}
h2{{display:flex;align-items:center;gap:10px;font-size:1.3rem;margin:0}}
h2 small{{color:var(--mut);font-weight:500;font-size:.95rem}}
.num{{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--ink);color:var(--bg);font-size:.9rem}}
.sub{{color:var(--mut);margin:4px 0 14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
@media (max-width:420px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;scroll-margin-top:16px}}
.card:target{{outline:2px solid var(--acc)}}
.card header{{display:flex;gap:10px;align-items:baseline}}
.card h3{{font-size:1rem;margin:0;line-height:1.35}}
.pid{{font:600 .75rem ui-monospace,Consolas,monospace;color:var(--mut);flex:none}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}}
.tag{{font-size:.72rem;padding:2px 8px;border-radius:99px;background:var(--bg);border:1px solid var(--line);color:var(--mut)}}
.tag.kind{{background:var(--accbg);color:var(--acc);border-color:transparent}}
.st-zrob_teraz{{background:var(--nowbg);color:var(--now);border-color:transparent;font-weight:600}}
.st-czeka{{background:var(--waitbg);color:var(--wait);border-color:transparent;font-weight:600}}
.st-backlog{{background:var(--backbg);color:var(--back);border-color:transparent;font-weight:600}}
.st-nigdy{{background:var(--nobg);color:var(--no);border-color:transparent;font-weight:600}}
.desc{{margin:6px 0}}
.infer{{list-style:none;margin:6px 0;padding:0;font-size:.86rem;color:var(--mut)}}
.infer li{{margin:3px 0 !important}}
.wn{{display:inline-block;font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--back);background:var(--backbg);border-radius:4px;padding:0 5px;margin-right:6px}}
.change{{margin:6px 0;font-size:.88rem;color:var(--wait);background:var(--waitbg);padding:6px 10px;border-radius:8px}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:8px 0;font-size:.88rem}}
dt{{color:var(--mut)}} dd{{margin:0}}
details summary{{cursor:pointer;color:var(--acc);font-size:.85rem}}
blockquote{{margin:8px 0 0;padding:6px 10px;border-left:3px solid var(--line);color:var(--mut);font-style:italic;font-size:.88rem}}
.mail{{position:relative;background:var(--card);border:1px solid var(--line);border-radius:12px}}
.mail pre{{margin:0;padding:18px 20px;white-space:pre-wrap;font:14px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;overflow-x:auto}}
#copy{{position:absolute;top:10px;right:10px;font:inherit;font-size:.82rem;padding:5px 12px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}}
footer{{margin-top:40px;color:var(--mut);font-size:.85rem}}
</style></head><body><div class="wrap">
<h1>{e(title)}</h1>
<p class="meta">{e(" · ".join(meta_bits))}</p>
<div class="tiles">{tiles}</div>
<div class="panel" id="zmiany"><h2>Zmiany zdania wykryte w rozmowie</h2><ol>{changes}</ol></div>
<div class="panel" id="konflikty"><h2>Konflikty i zależności dat</h2><ol>{conf}</ol></div>
{secs}
<footer><div class="panel"><h2>Weryfikacja</h2><p>{e(ver_txt)}</p>{"<ul>" + verh + "</ul>" if verh else ""}</div>
Źródło: {e(d.get("zrodlo", ""))} · dane: wynik.json</footer>
</div>
<script>
document.getElementById('copy').addEventListener('click',function(){{
  var b=this,t=document.getElementById('mailtxt').innerText;
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){{b.textContent='Skopiowano';}},function(){{
    var r=document.createRange();r.selectNodeContents(document.getElementById('mailtxt'));var s=getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Zaznaczono — Ctrl+C';}});
  setTimeout(function(){{b.textContent='Kopiuj';}},2500);
}});
</script></body></html>"""


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="wynik.json → raport.html")
    ap.add_argument("wynik")
    ap.add_argument("--transkrypcja")
    ap.add_argument("--out")
    a = ap.parse_args()

    d = json.load(open(a.wynik, encoding="utf-8"))
    errs = validate(d)
    if errs:
        print("BŁĘDY W wynik.json:", *errs, sep="\n  ", file=sys.stderr)
        sys.exit(1)
    verified = False
    if a.transkrypcja:
        missing = verify_quotes(d, open(a.transkrypcja, encoding="utf-8").read())
        if missing:
            print("CYTATY NIEDOSŁOWNE (popraw lub usuń pozycje):", *missing, sep="\n  ", file=sys.stderr)
            sys.exit(2)
        verified = True
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.wynik)), "raport.html")
    open(out, "w", encoding="utf-8").write(render(d, verified))
    counts = {t: sum(1 for p in d["pozycje"] if p["sekcja"] == k) for k, t, _ in SECTIONS}
    print(f"OK: {out}")
    print(f"Cytaty sprawdzone z transkrypcją: {'tak' if verified else 'nie'}")
    for t, n in counts.items():
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
