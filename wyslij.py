#!/usr/bin/env python3
"""wyslij.py – wysyłka zatwierdzonych maili do klienta.

Użycie:
  python3 wyslij.py            # wysyła szkice zgłoszeń z etykietą „Wyślij”
  python3 wyslij.py --sucho    # pokazuje, co by zrobił; nic nie wysyła i nie zmienia

Jedyna czynność człowieka: etykieta „Wyślij” na zgłoszeniu ze szkicem (komentarz „Szkic maila do klienta”).
Przed KAŻDĄ wysyłką działają bezpieczniki w kodzie (ops/zasady.json → wysylka):
  1. nigdy dwa razy ten sam szkic (historia wysyłek w karcie + etykieta „Wysłano”),
  2. odbiorca tylko z kontaktów karty z potwierdzonym kontaktem (nigdy z treści szkicu),
  3. strażnik zakazów z karty (np. „nie przypominać Kasi o pliku”, „nie kontaktować się z Olą”, „nie wysyłać wzoru”),
  4. filtr treści (identyfikatory, nazwy narzędzi, słowo „zakaz”, inny klient, obcy adres e-mail),
  5. limit maili do jednego klienta dziennie,
  6. tylko dni robocze 8:00–18:00 czasu polskiego (poza tym szkic czeka),
  7. nieobecność osoby kontaktowej z karty: mail czeka do jej powrotu, a Slack dostaje informację.
Zablokowane: etykieta „Do weryfikacji”, zdjęcie „Wyślij”, komentarz z powodem, Slack. Oczekujące (okno, limit, urlop):
etykieta zostaje, mail wyjdzie, gdy warunek ustąpi (Slack tylko raz na powód).
Logika nie zna sieci: zależy od obiektu „środowiska” (Linear, poczta, Slack, karta, czas), więc testy podstawiają atrapy.
"""

import argparse
import hashlib
import re
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import slack_widok as sw
from maile import slack_bezpiecznie

NAGLOWEK_SZKICU = "**Szkic maila do klienta**"
NAGLOWEK_ZBIORCZEGO = "**Szkic zbiorczy:**"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# ── szkic w komentarzu ────────────────────────────────────────────────────────

def format_komentarza_szkicu(odbiorca, temat, tresc, identyfikatory):
    return (f"{NAGLOWEK_SZKICU}\n\n**Do:** {odbiorca}\n**Temat:** {temat}\n**Zgłoszenia:** {', '.join(identyfikatory)}\n\n"
            f"---\n{tresc.strip()}\n---\n\n_Aby wysłać: dodaj etykietę „Wyślij”. Szkic możesz poprawić, dodając nowy komentarz "
            f"w tym samym układzie; wysłany zostanie najnowszy._")


def format_komentarza_zbiorczego(glowny):
    return f"{NAGLOWEK_ZBIORCZEGO} treść maila jest w zgłoszeniu {glowny}. Etykietę „Wyślij” dodaj tam."


def parsuj_szkic(komentarze):
    """Najnowszy komentarz ze szkicem → {"do","temat","zgloszenia","tresc"} albo None.
    Komentarz zbiorczy (wskazujący inne zgłoszenie) → {"zbiorczy": "RIN-x"}."""
    for k in sorted(komentarze, key=lambda c: c.get("createdAt", ""), reverse=True):
        body = (k.get("body") or "").strip()
        if body.startswith(NAGLOWEK_ZBIORCZEGO):
            m = re.search(r"zgłoszeniu (RIN-\d+)", body)
            return {"zbiorczy": m.group(1) if m else "?"}
        if not body.startswith(NAGLOWEK_SZKICU):
            continue
        do = re.search(r"^\*\*Do:\*\*\s*(.+)$", body, re.M)
        temat = re.search(r"^\*\*Temat:\*\*\s*(.+)$", body, re.M)
        zgl = re.search(r"^\*\*Zgłoszenia:\*\*\s*(.+)$", body, re.M)
        tresc = re.search(r"^---\n(.*?)\n---\s*$", body, re.M | re.S)
        if not (do and temat and tresc):
            continue
        return {"do": do.group(1).strip(), "temat": temat.group(1).strip(),
                "zgloszenia": re.findall(r"RIN-\d+", zgl.group(1)) if zgl else [],
                "tresc": tresc.group(1).strip()}
    return None


def hash_szkicu(temat, tresc, email):
    norm = " ".join(f"{temat}\n{tresc}".split()).lower()
    return hashlib.sha256(f"{email.lower()}|{norm}".encode("utf-8")).hexdigest()[:24]


# ── czas ──────────────────────────────────────────────────────────────────────

def lokalnie(teraz, W):
    return teraz.astimezone(ZoneInfo(W["strefa"]))


def okno_wysylki(teraz, W):
    """(czy można teraz wysyłać, opis okna)."""
    t = lokalnie(teraz, W)
    opis = f"dni robocze {W['godziny']['od']}:00–{W['godziny']['do']}:00 czasu polskiego"
    if t.weekday() not in W["dni_robocze"] or t.date().isoformat() in W["swieta"]:
        return False, opis
    return W["godziny"]["od"] <= t.hour < W["godziny"]["do"], opis


def nieobecnosc(kontakt, dzien):
    """Aktualna nieobecność kontaktu (słownik z polami od, do) albo None. dzien: date."""
    for n in kontakt.get("nieobecnosci", []):
        if date.fromisoformat(n["od"]) <= dzien <= date.fromisoformat(n["do"]):
            return n
    return None


# ── bezpieczniki ──────────────────────────────────────────────────────────────

def znajdz_odbiorce(karta, imie):
    """Kontakt z karty o tym imieniu, z potwierdzonym kontaktem i adresem. Adres bierzemy WYŁĄCZNIE stąd."""
    for k in (karta or {}).get("kontakty", []):
        if k.get("imie") == imie and k.get("potwierdzony") is True and EMAIL_RE.fullmatch(k.get("email", "") or ""):
            return k
    return None


def _warianty_nazwy(slug_klienta, nazwa=None):
    w = {slug_klienta, slug_klienta.replace("-", " "), slug_klienta.replace("-", "")}
    if nazwa:
        w |= {nazwa, nazwa.replace("-", " ")}
    return {x.lower() for x in w if x}


def filtr_tresci(temat, tresc, karta, W, inni_klienci=()):
    """Powody, dla których szkicu nie wolno wysłać (pusta lista = czysty). inni_klienci: [(slug, nazwa), ...]."""
    tekst = f"{temat}\n{tresc}"
    niski = tekst.lower()
    F = W["filtr_tresci"]
    powody = []
    for slowo in F["zabronione_slowa"]:
        if slowo.lower() in niski:
            powody.append(f"treść zawiera „{slowo}”")
    for wzorzec in F["zabronione_wzorce"]:
        m = re.search(wzorzec, tekst, re.IGNORECASE if wzorzec.startswith("\\bRIN") else 0)
        if m:
            powody.append(f"treść zawiera wewnętrzne oznaczenie „{m.group(0)}”")
    dozwolone = {(k.get("email") or "").lower() for k in (karta or {}).get("kontakty", [])}
    for adres in {a.lower() for a in EMAIL_RE.findall(tekst)}:
        if adres not in dozwolone:
            powody.append("treść zawiera adres e-mail spoza karty klienta")
            break
    for slug_i, nazwa_i in inni_klienci:
        for w in _warianty_nazwy(slug_i, nazwa_i):
            if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", niski):
                powody.append("treść wspomina innego klienta")
                break
        else:
            continue
        break
    return list(dict.fromkeys(powody))


def _pasuje_imie(osoba, imie_pelne):
    token = re.sub(r"[^\w]", "", osoba or "").lower()
    pierwsze = (imie_pelne or "").split()[0].lower() if imie_pelne else ""
    stem = token[:-1] if len(token) >= 3 else token
    return bool(stem) and pierwsze.startswith(stem)


def straznik_zakazow(karta, odbiorca, temat, tresc, W):
    """Powody wynikające z zakazów w karcie (wzorce w ops/zasady.json → wysylka.wzorce_zakazow)."""
    tekst = f"{temat}\n{tresc}".lower()
    powody = []
    for z in (karta or {}).get("zakazy", []):
        for r in W["wzorce_zakazow"]:
            m = re.search(r["tytul"], z.get("tytul", ""), re.IGNORECASE)
            if not m:
                continue
            typ = r["blokuje"]
            if typ == "adresat" and _pasuje_imie(m.group("osoba"), odbiorca["imie"]):
                powody.append(f"zakaz {z['id']}: {z['tytul']} (adresat: {odbiorca['imie']})")
            elif typ == "przypomnienie" and _pasuje_imie(m.group("osoba"), odbiorca["imie"]):
                if any(s in tekst for s in r["slowa_przypomnienia"]):
                    reszta = [w[:4].lower() for w in re.findall(r"\w+", m.group("reszta") or "") if len(w) >= 4]
                    if not reszta or any(w in tekst for w in reszta):
                        powody.append(f"zakaz {z['id']}: {z['tytul']} (mail jest przypomnieniem)")
            elif typ == "slowa" and any(s in tekst for s in r["slowa"]):
                powody.append(f"zakaz {z['id']}: {z['tytul']} (treść o wzorze)")
    return list(dict.fromkeys(powody))


def czy_duplikat(karta, identyfikatory, skrot):
    for w in (karta or {}).get("historia_wysylek", []):
        if w.get("hash") == skrot or set(identyfikatory) & set(w.get("zgloszenia", [])):
            return w
    return None


def wysylki_w_dniu(karta, dzien):
    return sum(1 for w in (karta or {}).get("historia_wysylek", []) if str(w.get("data", ""))[:10] == dzien.isoformat())


# ── obsługa jednego zgłoszenia ────────────────────────────────────────────────

def klient_z_tytulu(tytul):
    m = re.match(r"^\[([^\]]+)\]", tytul or "")
    return m.group(1) if m else None


def _slack(s, sekcje):
    s.slack.wyslij(sw.tekst_zapasowy(sekcje), sw.bloki(sekcje))


def wstrzymaj(s, zg, powody, grupa=None):
    """Blokada: Do weryfikacji, zdjęcie Wyślij, komentarz z powodem, Slack."""
    E = s.Z["etykiety"]
    powod = "; ".join(powody)
    if getattr(s, "sucho", False):
        return {"status": "wstrzymane", "powod": powod, "zgloszenie": zg["identifier"]}
    for g in (grupa or [zg]):
        s.linear.dodaj_etykiete(g, E["weryfikacja"])
        s.linear.usun_etykiete(g, E["wyslij"])
    s.linear.komentarz(zg, f"**Wysyłka wstrzymana**\n\n{powod}\n\nPo poprawieniu szkicu dodaj etykietę „Wyślij” jeszcze raz.")
    _slack(s, [f":no_entry: Wysyłka wstrzymana: {slack_bezpiecznie(powod, 200)} ({sw.link(zg.get('url'), zg.get('title'))})"])
    return {"status": "wstrzymane", "powod": powod, "zgloszenie": zg["identifier"]}


def czekaj(s, zg, karta, klient, powod):
    """Oczekiwanie (okno, limit, urlop, błąd poczty): bez zmian w Linearze; Slack raz na powód."""
    if getattr(s, "sucho", False):
        return {"status": "czeka", "powod": powod, "zgloszenie": zg["identifier"]}
    oczek = karta.setdefault("wysylki_oczekujace", {})
    if oczek.get(zg["identifier"]) != powod:
        oczek[zg["identifier"]] = powod
        s.zapisz_karte(klient, karta)
        _slack(s, [f":hourglass_flowing_sand: Wysyłka wstrzymana: {slack_bezpiecznie(powod, 200)} ({sw.link(zg.get('url'), zg.get('title'))})"])
    return {"status": "czeka", "powod": powod, "zgloszenie": zg["identifier"]}


def obsluz_zgloszenie(s, zg):
    Z, W, E = s.Z, s.Z["wysylka"], s.Z["etykiety"]
    etykiety = set(zg.get("labels", []))
    if E["wyslano"] in etykiety:                                     # już wysłane: tylko sprzątamy „Wyślij”
        s.linear.usun_etykiete(zg, E["wyslij"])
        return {"status": "pominiete", "powod": "już wysłano", "zgloszenie": zg["identifier"]}

    klient = klient_z_tytulu(zg.get("title")) or ""
    karta = s.wczytaj_karte(klient)
    szkic = parsuj_szkic(s.linear.komentarze(zg))
    if szkic is None:
        return wstrzymaj(s, zg, ["brak szkicu maila w komentarzach zgłoszenia"])
    if "zbiorczy" in szkic:
        return wstrzymaj(s, zg, [f"to jest szkic zbiorczy: etykietę „Wyślij” dodaj w zgłoszeniu {szkic['zbiorczy']}"])

    identyfikatory = list(dict.fromkeys(szkic["zgloszenia"] or [zg["identifier"]]))
    if zg["identifier"] not in identyfikatory:
        return wstrzymaj(s, zg, ["szkic nie należy do tego zgłoszenia"])
    grupa = [zg] + [g for g in (s.linear.zgloszenie_po_numerze(int(i.split("-")[1])) for i in identyfikatory
                                if i != zg["identifier"]) if g]

    # 1) duplikaty (historia w karcie, etykieta Wysłano na zgłoszeniach grupy)
    odbiorca = znajdz_odbiorce(karta, szkic["do"])
    # 2) odbiorca tylko z karty
    if odbiorca is None:
        return wstrzymaj(s, zg, [f"odbiorca „{szkic['do']}” nie jest potwierdzonym kontaktem w karcie klienta"], grupa)
    skrot = hash_szkicu(szkic["temat"], szkic["tresc"], odbiorca["email"])
    dup = czy_duplikat(karta, identyfikatory, skrot)
    if dup or any(E["wyslano"] in g.get("labels", []) for g in grupa):
        return wstrzymaj(s, zg, ["ten szkic już wysłano" + (f" ({str(dup.get('data', ''))[:10]})" if dup else "")], grupa)
    # 3) strażnik zakazów, 4) filtr treści
    powody = straznik_zakazow(karta, odbiorca, szkic["temat"], szkic["tresc"], W)
    powody += filtr_tresci(szkic["temat"], szkic["tresc"], karta, W, s.inni_klienci(klient))
    if powody:
        return wstrzymaj(s, zg, powody, grupa)

    # oczekiwanie: urlop → okno → limit dzienny
    teraz = s.teraz()
    dzien = lokalnie(teraz, W).date()
    nieob = nieobecnosc(odbiorca, dzien)
    if nieob:
        wraca = date.fromisoformat(nieob["do"]) + timedelta(days=1)
        return czekaj(s, zg, karta, klient, f"{odbiorca['imie']} jest nieobecna do {nieob['do']}, mail wyjdzie po powrocie (od {wraca.isoformat()})")
    ok, opis = okno_wysylki(teraz, W)
    if not ok:
        return czekaj(s, zg, karta, klient, f"poza oknem wysyłki ({opis}); mail wyjdzie w najbliższym oknie")
    if wysylki_w_dniu(karta, dzien) >= W["max_dziennie_na_klienta"]:
        return czekaj(s, zg, karta, klient, f"limit {W['max_dziennie_na_klienta']} maili dziennie do klienta; mail wyjdzie jutro")

    if getattr(s, "sucho", False):
        return {"status": "wyslalby", "zgloszenie": zg["identifier"], "do": odbiorca["imie"], "temat": szkic["temat"]}

    # wysyłka
    try:
        message_id = s.poczta.wyslij(odbiorca["email"], odbiorca["imie"], szkic["temat"], szkic["tresc"])
    except Exception as exc:  # noqa: BLE001
        return czekaj(s, zg, karta, klient, f"błąd poczty: {slack_bezpiecznie(str(exc), 120)}; ponowimy przy następnym przebiegu")

    # historia ZANIM ruszymy Linear: nawet gdy dalsze kroki padną, drugi raz nie wyślemy
    karta.setdefault("historia_wysylek", []).append({
        "data": lokalnie(teraz, W).isoformat(timespec="seconds"), "message_id": message_id, "do": odbiorca["imie"],
        "temat": szkic["temat"], "zgloszenia": identyfikatory, "hash": skrot})
    karta.get("wysylki_oczekujace", {}).pop(zg["identifier"], None)
    s.zapisz_karte(klient, karta)

    data_txt = lokalnie(teraz, W).strftime("%Y-%m-%d %H:%M")
    for g in grupa:
        s.linear.dodaj_etykiete(g, E["wyslano"])
        s.linear.usun_etykiete(g, E["wyslij"])
        s.linear.usun_etykiete(g, E["szkic"])
    s.linear.komentarz(zg, f"Wysłano {data_txt}")
    _slack(s, [f":email: Wysłano do {odbiorca['imie']}: {slack_bezpiecznie(szkic['temat'], 120)}"])
    return {"status": "wyslane", "zgloszenie": zg["identifier"], "do": odbiorca["imie"], "message_id": message_id}


def uruchom(s):
    wyniki = []
    for zg in s.linear.z_etykieta(s.Z["etykiety"]["wyslij"]):
        try:
            wyniki.append(obsluz_zgloszenie(s, zg))
        except Exception as exc:  # noqa: BLE001  (jedno zgłoszenie nie zatrzymuje reszty)
            wyniki.append({"status": "blad", "powod": slack_bezpiecznie(str(exc), 160), "zgloszenie": zg["identifier"]})
    return wyniki


# ── środowisko produkcyjne i main ─────────────────────────────────────────────

def zbuduj_srodowisko(sucho=False):
    import json
    import os
    from datetime import timezone
    from pathlib import Path

    import linear_sync
    import zasady
    from agent_srodowisko import LinearAgent, Poczta, SlackAgent
    from przetworz import load_env
    from sekrety import wyczysc_srodowisko

    load_env()
    wyczysc_srodowisko()
    Z = zasady.wczytaj_zasady()

    class Srodowisko:
        pass

    s = Srodowisko()
    s.Z, s.sucho = Z, sucho
    s.linear = LinearAgent(linear_sync.load_api_key(), Z)
    s.slack = SlackAgent()
    s.poczta = Poczta(Z["wysylka"])
    s.teraz = lambda: datetime.now(timezone.utc)
    s.wczytaj_karte = linear_sync.load_karta
    s.zapisz_karte = linear_sync.save_karta

    def inni(klient):
        out = []
        for p in sorted(Path("ops/klienci").glob("*/karta.json")):
            if p.parent.name != klient:
                out.append((p.parent.name, json.loads(p.read_text(encoding="utf-8")).get("klient")))
        return out

    s.inni_klienci = inni
    return s


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Wysyła zatwierdzone maile do klientów (etykieta Wyślij).")
    ap.add_argument("--sucho", action="store_true", help="nic nie wysyłaj i nie zmieniaj")
    args = ap.parse_args()
    s = zbuduj_srodowisko(args.sucho)
    wyniki = uruchom(s)
    for w in wyniki:
        print(f"{w['zgloszenie']}: {w['status']}" + (f" ({w['powod']})" if w.get("powod") else ""))
    if not wyniki:
        print("Brak zgłoszeń z etykietą Wyślij.")
    if any(w["status"] == "blad" for w in wyniki):
        sys.exit(1)


if __name__ == "__main__":
    main()
