#!/usr/bin/env python3
"""maile.py – drugie źródło danych: maile od klienta (Gmail przez IMAP).

Użycie:
  python3 maile.py                      # pobierz nowe maile od znanych nadawców
  python3 maile.py --lista plik.txt     # dodatkowo zapisz ścieżki nowych maili (po jednej w linii)
  python3 maile.py --dni 30             # okno wyszukiwania (domyślnie 14 dni)
  python3 maile.py --sucho              # nic nie zapisuje i nie wysyła na Slacka

Zasady:
  * Skrzynka jest otwierana TYLKO DO ODCZYTU (IMAP EXAMINE, a treść pobierana przez BODY.PEEK).
    Skrypt niczego nie wysyła, nie usuwa, nie oznacza i nie przenosi.
  * Treść pobieramy wyłącznie od nadawców znanych z kart klientów (pole "kontakty") albo z domeny
    klienta (pole "domeny"). Od nieznanego nadawcy nie pobieramy treści: liczymy mail i przy pierwszym
    wystąpieniu adresu wysyłamy na Slacka "pominięto mail od nieznanego nadawcy <adres>".
  * Nadawca z domeny klienta, którego nie ma w kontaktach: mail jest czytany, a nadawca trafia do
    kontaktów jako "nowy, bez prawa decyzji" (potwierdza go człowiek, ustawiając potwierdzony: true).
    Ogólne domeny pocztowe (gmail.com, wp.pl…) nigdy nie są domeną klienta.
  * Maile automatyczne (List-Unsubscribe, Auto-Submitted, Precedence: bulk/list/junk, adresy
    noreply/notifications…) są pomijane całkowicie i po cichu.
  * Nieznani nadawcy: jedna linijka na przebieg („pominięto N maili od nieznanych nadawców”), bez adresów.
    Osobny alert z adresem tylko dla nadawcy z domeny klienta.
  * Przy pierwszym uruchomieniu data włączenia trafia do rejestru; wcześniejsze maile są ignorowane.
  * Rejestr ops/.maile.json: Message-ID trafia do "przetworzone" dopiero PO udanym przetworzeniu
    (przetworz.py). Do tego czasu mail jest "oczekujący": nieudana analiza jest ponawiana (maks. 3 próby),
    potem alert na Slacka i status "porzucony".
  * Mail → ops/maile/<klient>/<data>-<slug>.md (bez cytowanych wiadomości i stopki).

Klucze (GMAIL_ADDRESS, GMAIL_APP_PASSWORD) z .env albo ze środowiska; czyszczone z niewidocznych
znaków (sekrety.py), nigdy nie wypisywane.
"""

import argparse
import email
import hashlib
import imaplib
import json
import os
import re
import ssl
import sys
import unicodedata
from datetime import date, datetime, timedelta
from email.policy import default as POLITYKA
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from sekrety import czysc, wyczysc_srodowisko
import higiena

IMAP_HOST = "imap.gmail.com"
REJESTR_PATH = Path("ops/.maile.json")
MAILE_DIR = Path("ops/maile")
KLIENCI_DIR = Path("ops/klienci")

# Ogólne domeny pocztowe: nigdy nie wskazują firmy klienta, liczy się tylko pełny adres.
DOMENY_OGOLNE = {
    "gmail.com", "googlemail.com", "wp.pl", "onet.pl", "o2.pl", "outlook.com", "hotmail.com",
    "live.com", "yahoo.com", "interia.pl", "interia.eu", "icloud.com", "me.com", "proton.me",
    "protonmail.com", "op.pl", "poczta.fm", "gazeta.pl", "tlen.pl", "vp.pl", "onet.eu", "wp.eu",
}

STATUS_NOWY = "nowy, bez prawa decyzji"

MAX_PROB = 3   # tyle razy próbujemy przetworzyć mail, potem „porzucony”

# nagłówki pobierane dla każdego maila (tylko nagłówki: treść dopiero od znanych nadawców)
NAGLOWKI_IMAP = ("FROM MESSAGE-ID DATE SUBJECT LIST-UNSUBSCRIBE AUTO-SUBMITTED PRECEDENCE X-AUTOREPLY X-AUTORESPOND "
                 "AUTHENTICATION-RESULTS IN-REPLY-TO REFERENCES")

_ADRES_AUTOMATU = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|^notifications?([-_+.]|$)|^notify([-_+.]|$)|"
    r"^mailer-daemon$|^postmaster$|^bounces?([-_+.]|$))", re.I)


def slack_bezpiecznie(tekst, limit=120):
    """Tekst z maila/transkrypcji bez znaków sterujących Slacka (<@U…>, <!channel>, linki)."""
    t = re.sub(r"\s+", " ", str(tekst or "")).strip()[:limit]
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def czy_automatyczny(msg, adres):
    """Mail automatyczny (newsletter, powiadomienie, autoresponder): pomijamy go całkowicie i po cichu."""
    if msg.get("List-Unsubscribe") is not None:
        return True
    auto = str(msg.get("Auto-Submitted", "")).strip().lower()
    if auto and auto != "no":
        return True
    if str(msg.get("Precedence", "")).strip().lower() in ("bulk", "list", "junk"):
        return True
    lokalna = normalizuj_adres(adres).partition("@")[0]
    return bool(_ADRES_AUTOMATU.search(lokalna))


def okno_od(dzis, dni, wlaczono):
    """Od kiedy szukamy maili: nie wcześniej niż data włączenia (nie czytamy historii skrzynki)."""
    od = dzis - timedelta(days=dni)
    if wlaczono:
        od = max(od, date.fromisoformat(wlaczono))
    return od


# ── nadawca: kontakt, domena, nieznany ────────────────────────────────────────

def normalizuj_adres(adres):
    return czysc(adres).lower()


def domena_adresu(adres):
    return normalizuj_adres(adres).rpartition("@")[2]


def domeny_klienta(karta):
    """Domeny klienta z karty, bez ogólnych domen pocztowych (błąd w karcie nie otwiera drzwi)."""
    return {d.strip().lower() for d in karta.get("domeny", [])
            if d and d.strip().lower() not in DOMENY_OGOLNE}


def domena_pasuje(domena, domeny):
    return any(domena == d or domena.endswith("." + d) for d in domeny)


def znajdz_kontakt(karta, adres):
    adres = normalizuj_adres(adres)
    for k in karta.get("kontakty", []):
        if normalizuj_adres(k.get("email", "")) == adres:
            return k
    return None


def kontakt_ma_prawo_decyzji(kontakt):
    """Kontakt dodany automatycznie z domeny klienta nie ma prawa decyzji do potwierdzenia."""
    if not kontakt:
        return False
    return kontakt.get("potwierdzony", True) is not False


def klasyfikuj_nadawce(adres, karty):
    """Zwraca {"typ": "kontakt"|"domena"|"nieznany", "klient", "kontakt"}.

    kontakt  – adres jest w polu "kontakty" którejś karty (pełny adres)
    domena   – adresu nie ma w kontaktach, ale domena jest domeną klienta (nie ogólną)
    nieznany – reszta (w tym każdy adres z ogólnej domeny pocztowej spoza kontaktów)
    """
    adres = normalizuj_adres(adres)
    if "@" not in adres:
        return {"typ": "nieznany", "klient": None, "kontakt": None}
    for klient, karta in karty.items():
        kontakt = znajdz_kontakt(karta, adres)
        if kontakt:
            return {"typ": "kontakt", "klient": klient, "kontakt": kontakt}
    dom = domena_adresu(adres)
    if dom not in DOMENY_OGOLNE:
        for klient, karta in karty.items():
            if domena_pasuje(dom, domeny_klienta(karta)):
                return {"typ": "domena", "klient": klient, "kontakt": None}
    return {"typ": "nieznany", "klient": None, "kontakt": None}


def dodaj_kontakt_z_domeny(karta, adres, imie, dzis):
    """Dopisuje nadawcę z domeny klienta jako kontakt bez prawa decyzji (do potwierdzenia)."""
    kontakt = {
        "imie": imie or adres.split("@")[0],
        "email": normalizuj_adres(adres),
        "rola": "nowy kontakt z domeny klienta, do potwierdzenia przez człowieka",
        "zakres_decyzji": "brak",
        "potwierdzony": False,
        "status": STATUS_NOWY,
        "dodano": dzis,
    }
    karta.setdefault("kontakty", []).append(kontakt)
    return kontakt


# ── treść: bez cytatów i stopki ───────────────────────────────────────────────

_NAGLOWKI_CYTATU = [
    re.compile(r"^On .{5,200} wrote:\s*$", re.I),
    re.compile(r"^(W dniu|Dnia) .{5,200}(napisał|napisała|napisał\(a\)|pisze)[^\n]{0,80}:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*(Original Message|Oryginalna wiadomość|Wiadomość oryginalna|"
               r"Forwarded message|Przekazana wiadomość)\b.*$", re.I),
    re.compile(r"^_{8,}\s*$"),
    re.compile(r"^(From|Od):\s.+$", re.I),     # nagłówek Outlooka po linii z kreskami
]
_STOPKA_MOBILNA = re.compile(
    r"^(Wysłano z|Wysłane z|Sent from|Pobierz aplikację|Get Outlook|Wysłano za pomocą)\b", re.I)
_ZAMKNIECIE = re.compile(
    r"^(Pozdrawiam|Pozdrowienia|Z poważaniem|Z wyrazami szacunku|Serdecznie|Z pozdrowieniami|"
    r"Dziękuję i pozdrawiam|Best regards|Kind regards|Regards|Thanks|Thank you)\b[\s,.!]*", re.I)


def czysc_tresc(tekst, zachowaj_przekazane=False):
    """Usuwa cytowane wcześniejsze wiadomości i stopkę; zostawia to, co klient napisał nowego.
    zachowaj_przekazane: wiadomość przekazana (Fwd) – przekazana treść jest właśnie informacją, więc jej nie ucinamy."""
    linie = tekst.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if zachowaj_przekazane:
        linie = [l.lstrip().lstrip(">").lstrip() if l.lstrip().startswith(">") else l for l in linie]

    # 1) pierwszy nagłówek cytatu ucina resztę (Gmail zawija go na dwie linie, więc sprawdzamy też parę)
    for i, linia in enumerate([] if zachowaj_przekazane else linie):
        nastepna = linie[i + 1].strip() if i + 1 < len(linie) else ""
        para = (linia.strip() + " " + nastepna).strip()
        zdanie_cytatu = any(w.match(linia.strip()) or w.match(para) for w in _NAGLOWKI_CYTATU[:2])
        separator = any(w.match(linia) for w in _NAGLOWKI_CYTATU[2:4])
        # "From:/Od:" cytuje tylko, gdy zaraz po nim jest Sent/Wysłano/To/Do (nagłówek, nie zdanie)
        naglowek_outlook = bool(_NAGLOWKI_CYTATU[4].match(linia)) and bool(
            re.match(r"^(Sent|Wysłano|Date|Data|To|Do):", nastepna, re.I))
        if zdanie_cytatu or separator or naglowek_outlook:
            linie = linie[:i]
            break

    # 2) linie cytowane znakiem ">"
    if not zachowaj_przekazane:
        linie = [l for l in linie if not l.lstrip().startswith(">")]

    # 3) separator stopki "-- " i stopki mobilne
    for i, linia in enumerate(linie):
        if re.match(r"^--\s?$", linia.rstrip("\n")) or _STOPKA_MOBILNA.match(linia.strip()):
            linie = linie[:i]
            break

    # 4) formuła zamykająca + krótki podpis pod nią (imię, telefon, firma): to stopka
    niepuste = [i for i, l in enumerate(linie) if l.strip()]
    for pos, i in enumerate(niepuste):
        if _ZAMKNIECIE.match(linie[i].strip()) and len(niepuste) - pos - 1 <= 8:
            linie = linie[:i]
            break

    wynik = "\n".join(linie).strip()
    return re.sub(r"\n{3,}", "\n\n", wynik)


class _HtmlDoTekstu(HTMLParser):
    BLOKI = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.czesci = []
        self._pomin = 0     # script/style/blockquote/gmail_quote

    def handle_starttag(self, tag, attrs):
        klasa = dict(attrs).get("class", "") or ""
        if tag in ("script", "style", "blockquote") or "gmail_quote" in klasa:
            self._pomin += 1
        elif tag in self.BLOKI and not self._pomin:
            self.czesci.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "blockquote") and self._pomin:
            self._pomin -= 1
        elif tag in self.BLOKI and not self._pomin:
            self.czesci.append("\n")

    def handle_data(self, data):
        if not self._pomin:
            self.czesci.append(data)


def html_do_tekstu(html_tresc):
    p = _HtmlDoTekstu()
    p.feed(html_tresc)
    return re.sub(r"[ \t]+\n", "\n", "".join(p.czesci))


# ── parsowanie wiadomości ─────────────────────────────────────────────────────

def _jedna_linia(tekst):
    return re.sub(r"\s+", " ", czysc_widoczne(str(tekst or ""))).strip()


def czysc_widoczne(tekst):
    """Usuwa znaki sterujące i niewidoczne z nagłówków (nie dotyka zwykłych spacji)."""
    return "".join(c for c in tekst if c in " \t" or unicodedata.category(c) not in ("Cc", "Cf", "Zl", "Zp"))


def parsuj_wiadomosc(raw):
    """raw: bajty .eml → słownik z polami potrzebnymi do zapisu."""
    msg = email.message_from_bytes(raw, policy=POLITYKA)
    imie, adres = parseaddr(str(msg.get("From", "")))
    try:
        data = parsedate_to_datetime(str(msg.get("Date", "")))
    except (TypeError, ValueError):
        data = None
    if data is None:
        data = datetime.now().astimezone()

    zalaczniki, zablokowane = [], []
    for czesc in msg.iter_attachments():
        nazwa = czesc.get_filename()
        if nazwa:
            nazwa = _jedna_linia(nazwa)
            try:
                rozmiar = len(czesc.get_payload(decode=True) or b"")        # tylko rozmiar: załącznika nie otwieramy
            except Exception:  # noqa: BLE001
                rozmiar = 0
            klasa = higiena.klasa_zalacznika(nazwa, rozmiar)
            if klasa == "ok":
                zalaczniki.append(nazwa)
            else:
                zablokowane.append((nazwa, klasa))

    cialo = msg.get_body(preferencelist=("plain", "html"))
    tekst = ""
    if cialo is not None:
        tekst = cialo.get_content()
        if cialo.get_content_type() == "text/html":
            tekst = html_do_tekstu(tekst)

    temat = _jedna_linia(msg.get("Subject", "")) or "(bez tematu)"
    przek = higiena.przekazany(temat, tekst)
    adres_n = normalizuj_adres(adres)
    return {
        "message_id": _jedna_linia(msg.get("Message-ID", "")),
        "od_imie": _jedna_linia(imie),
        "od_adres": adres_n,
        "do": _jedna_linia(msg.get("To", "")),
        "data": data,
        "temat": temat,
        "zalaczniki": zalaczniki,
        "zalaczniki_zablokowane": zablokowane,
        "tresc": czysc_tresc(tekst, zachowaj_przekazane=przek),
        "przekazany": przek,
        # nagłówek Authentication-Results: potwierdza DKIM/SPF dla domeny NADAWCY (From), nie kogoś w kopii
        "uwierzytelnienie": "tak" if higiena.uwierzytelnienie(str(msg.get("Authentication-Results", "")), domena_adresu(adres_n)) else "nie",
        "in_reply_to": _jedna_linia(msg.get("In-Reply-To", "")),
        "references": _jedna_linia(msg.get("References", "")),
        "naglowki_auto": {k: str(msg.get(k, "")) for k in ("Auto-Submitted", "X-Autoreply", "X-Autorespond", "Precedence")},
    }


_ZAMIANY = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "đ": "d"})


def slug(temat):
    t = re.sub(r"^((re|fwd?|odp|pd|fw)\s*:\s*)+", "", temat.strip(), flags=re.I)
    t = unicodedata.normalize("NFKD", t.translate(_ZAMIANY))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50].strip("-")
    return t or "bez-tematu"


def zapisz_mail_md(klient, meta, katalog=MAILE_DIR):
    """Zapisuje mail jako ops/maile/<klient>/<data>-<slug>.md i zwraca ścieżkę."""
    folder = Path(katalog) / klient
    folder.mkdir(parents=True, exist_ok=True)
    baza = f"{meta['data'].date().isoformat()}-{slug(meta['temat'])}"
    sciezka = folder / f"{baza}.md"
    n = 2
    while sciezka.exists():
        sciezka = folder / f"{baza}-{n}.md"
        n += 1
    od = f"{meta['od_imie']} <{meta['od_adres']}>" if meta["od_imie"] else meta["od_adres"]
    zal = ", ".join(meta["zalaczniki"]) if meta["zalaczniki"] else "brak"
    dodatkowe = ""
    if meta.get("zalaczniki_zablokowane"):
        dodatkowe += ("- **Załączniki zablokowane:** " + ", ".join(f"{n} ({p})" for n, p in meta["zalaczniki_zablokowane"])
                      + " (nie otwierano; to NIE jest dowód dostarczenia pliku)\n")
    if meta.get("uwierzytelnienie") == "nie":
        dodatkowe += "- **Uwierzytelnienie:** niepotwierdzone (brak DKIM/SPF pass dla domeny nadawcy)\n"
    if meta.get("przekazany"):
        dodatkowe += "- **Przekazany:** tak (treść przekazana to informacja, nie decyzja)\n"
    if meta.get("odpowiedz_na"):
        o = meta["odpowiedz_na"]
        dodatkowe += f"- **Odpowiedź na nasz mail:** {o['temat']} (zgłoszenia: {', '.join(o['zgloszenia'])})\n"
    tresc = meta["tresc"] or "(pusta treść)"
    mid_linia = f"- **Message-ID:** {meta['message_id']}\n" if meta.get("message_id") else ""
    sciezka.write_text(
        f"# Mail: {meta['temat']}\n\n"
        f"- **Od:** {od}\n"
        f"- **Do:** {meta['do']}\n"
        f"- **Data:** {meta['data'].strftime('%Y-%m-%d %H:%M')}\n"
        f"- **Temat:** {meta['temat']}\n"
        f"- **Załączniki:** {zal}\n"
        f"{dodatkowe}"
        f"{mid_linia}\n"
        f"## Treść\n\n{tresc}\n",
        encoding="utf-8")
    return sciezka


def czy_mail(sciezka):
    return "maile" in Path(str(sciezka)).parts


def wczytaj_meta_maila(sciezka):
    """Czyta nagłówek zapisanego maila (.md): od_adres, od_imie, data (RRRR-MM-DD), temat."""
    try:
        tekst = Path(sciezka).read_text(encoding="utf-8")
    except OSError:
        return {}
    meta = {}
    m = re.search(r"^- \*\*Od:\*\* (.*)$", tekst, re.M)
    if m:
        imie, adres = parseaddr(m.group(1))
        meta["od_imie"], meta["od_adres"] = imie, normalizuj_adres(adres)
    m = re.search(r"^- \*\*Data:\*\* (\d{4}-\d{2}-\d{2})", tekst, re.M)
    if m:
        meta["data"] = m.group(1)
    m = re.search(r"^- \*\*Temat:\*\* (.*)$", tekst, re.M)
    if m:
        meta["temat"] = m.group(1).strip()
    m = re.search(r"^- \*\*Message-ID:\*\* (.+)$", tekst, re.M)
    if m:
        meta["message_id"] = m.group(1).strip()
    meta["uwierzytelnienie"] = "nie" if re.search(r"^- \*\*Uwierzytelnienie:\*\* niepotwierdzone", tekst, re.M) else "tak"
    meta["przekazany"] = bool(re.search(r"^- \*\*Przekazany:\*\* tak", tekst, re.M))
    m = re.search(r"^- \*\*Załączniki zablokowane:\*\* (.+?) \(nie otwierano", tekst, re.M)
    meta["zalaczniki_zablokowane"] = [x.strip() for x in m.group(1).split("), ")] if m else []
    m = re.search(r"^- \*\*Odpowiedź na nasz mail:\*\* (.+) \(zgłoszenia: ([^)]*)\)$", tekst, re.M)
    if m:
        meta["odpowiedz_na"] = {"temat": m.group(1).strip(), "zgloszenia": [x.strip() for x in m.group(2).split(",") if x.strip()]}
    m = re.search(r"## Treść\n\n(.*)\Z", tekst, re.S)
    meta["tresc"] = m.group(1).strip() if m else ""
    return meta


# ── rejestr ───────────────────────────────────────────────────────────────────

def wczytaj_rejestr(path=REJESTR_PATH):
    if Path(path).exists():
        r = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        r = {}
    r.setdefault("przetworzone", {})   # Message-ID → {klient, plik, data}: tylko PO udanym przetworzeniu
    r.setdefault("oczekujace", {})     # Message-ID → {klient, plik, data, proby, status: oczekuje|porzucony}
    r.setdefault("nieznani", {})       # sha256(adres)[:16] → {liczba, ids} (bez adresów: repo bywa publiczne)
    return r


def zapisz_rejestr(rejestr, path=REJESTR_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(rejestr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hash(tekst):
    return hashlib.sha256(tekst.encode("utf-8")).hexdigest()[:16]


# ── karty klientów ────────────────────────────────────────────────────────────

def wczytaj_karty(katalog=KLIENCI_DIR):
    karty = {}
    for p in sorted(Path(katalog).glob("*/karta.json")):
        karty[p.parent.name] = json.loads(p.read_text(encoding="utf-8"))
    return karty


def zapisz_karte(klient, karta, katalog=KLIENCI_DIR):
    p = Path(katalog) / klient / "karta.json"
    p.write_text(json.dumps(karta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── główna logika (bez sieci: testowalna na plikach .eml) ─────────────────────

def analizuj_naglowki(surowe_naglowki):
    """Z samych nagłówków: imię, adres, Message-ID, data (RRRR-MM-DD albo None), czy automatyczny."""
    msg = email.message_from_bytes(surowe_naglowki, policy=POLITYKA)
    imie, adres = parseaddr(str(msg.get("From", "")))
    mid = _jedna_linia(msg.get("Message-ID", ""))
    if not mid:
        # brak Message-ID: stabilny zastępczy identyfikator z nagłówków
        mid = "brak-id:" + _hash(surowe_naglowki.decode("utf-8", "replace"))
    try:
        data = parsedate_to_datetime(str(msg.get("Date", ""))).date().isoformat()
    except (TypeError, ValueError):
        data = None
    auto = {k: str(msg.get(k, "")) for k in ("Auto-Submitted", "X-Autoreply", "X-Autorespond", "Precedence")}
    return {"imie": _jedna_linia(imie), "adres": normalizuj_adres(adres), "mid": mid, "data": data,
            "automatyczny": czy_automatyczny(msg, adres),
            # autoodpowiedź (nie newsletter): od znanego kontaktu nie analizujemy treści, ale daty nieobecności zapisujemy w karcie
            "autoodpowiedz": msg.get("List-Unsubscribe") is None and higiena.autoodpowiedz(auto, str(msg.get("Subject", "")))}


def _zapisz_nieobecnosc(meta, klient, adres, mid, karty, rejestr, wynik):
    """Autoodpowiedź znanego kontaktu: z dat w treści (daty.py) dopisuje nieobecność w karcie. Mail nie jest analizowany."""
    okres = higiena.nieobecnosc_z_autoodpowiedzi(meta["tresc"], meta["data"].date())
    if okres and higiena.dopisz_nieobecnosc(karty[klient], adres, okres, mid):
        wynik["zmienione_karty"].add(klient)
        wynik["nieobecnosci"].append((klient, adres, okres["od"].isoformat(), okres["do"].isoformat()))
    rejestr["przetworzone"][mid] = {"klient": klient, "plik": "", "data": meta["data"].date().isoformat(), "autoodpowiedz": True}
    wynik["autoodpowiedzi"] += 1


def _obsluz_autoodpowiedz(raw, klient, adres, mid, karty, rejestr, wynik):
    _zapisz_nieobecnosc(parsuj_wiadomosc(raw), klient, adres, mid, karty, rejestr, wynik)


def przetworz_skrzynke(skrzynka, karty, rejestr, slack, dzis, katalog_maili=MAILE_DIR):
    """skrzynka ma: uids(), naglowki(uid) → bajty, tresc(uid) → bajty (pełny mail).

    Zwraca {"nowe": [(klient, sciezka, temat)], "nieznani": n, "automatyczne": n, "nowe_kontakty": [...],
            "zmienione_karty": {klient}}.
    Treść pobierana jest tylko od znanych nadawców. Nowy mail trafia do rejestru jako "oczekujący";
    do "przetworzone" przenosi go dopiero przetworz.py po sukcesie. Slack: osobny alert tylko dla nadawcy
    z domeny klienta, a nieznanych nadawców podsumowuje jedna linijka na przebieg (bez adresów).
    """
    wynik = {"nowe": [], "nieznani": 0, "automatyczne": 0, "nowe_kontakty": [], "zmienione_karty": set(),
             "autoodpowiedzi": 0, "nieobecnosci": []}
    rejestr.setdefault("wlaczono", dzis)   # pierwszy przebieg: od dziś, bez historii skrzynki
    for uid in skrzynka.uids():
        nag = analizuj_naglowki(skrzynka.naglowki(uid))
        mid, adres = nag["mid"], nag["adres"]
        if mid in rejestr["przetworzone"] or mid in rejestr["oczekujace"]:
            continue
        if nag["data"] and nag["data"] < rejestr["wlaczono"]:
            continue                      # sprzed włączenia automatu
        kl = klasyfikuj_nadawce(adres, karty)
        if nag["automatyczny"]:
            if nag["autoodpowiedz"] and kl["typ"] == "kontakt":
                _obsluz_autoodpowiedz(skrzynka.tresc(uid), kl["klient"], adres, mid, karty, rejestr, wynik)
            else:
                wynik["automatyczne"] += 1    # po cichu: bez Slacka, bez rejestru, bez pobierania treści
            continue

        if kl["typ"] == "nieznany":
            wpis = rejestr["nieznani"].setdefault(_hash(adres), {"liczba": 0, "ids": []})
            if _hash(mid) in wpis["ids"]:
                continue
            wpis["liczba"] += 1
            wpis["ids"].append(_hash(mid))
            wynik["nieznani"] += 1
            continue

        # znany nadawca (kontakt albo domena klienta): dopiero teraz pobieramy treść
        meta = parsuj_wiadomosc(skrzynka.tresc(uid))
        meta["message_id"] = mid          # ten sam identyfikator co w nagłówku, także przy braku Message-ID
        klient = kl["klient"]
        # autoodpowiedź bez nagłówków (krótkie „jestem na urlopie…”): bez analizy treści, tylko nieobecność w karcie
        krotki = len(meta["tresc"].split()) <= 60
        if kl["typ"] == "kontakt" and (higiena.autoodpowiedz(meta["naglowki_auto"], meta["temat"], "")
                                       or (krotki and higiena.autoodpowiedz({}, "", meta["tresc"]))):
            _zapisz_nieobecnosc(meta, klient, adres, mid, karty, rejestr, wynik)
            continue
        wyslany = higiena.znajdz_wyslany(meta["in_reply_to"], meta["references"], karty)
        if wyslany:                       # odpowiedź na nasz wysłany mail: przypisanie do zgłoszeń z historii wysyłek
            meta["odpowiedz_na"] = {"temat": wyslany[1].get("temat", ""), "zgloszenia": list(wyslany[1].get("zgloszenia", []))}
        if meta["uwierzytelnienie"] == "nie":
            slack(f"mail od {adres} ({klient}) nie ma potwierdzonego DKIM/SPF dla domeny nadawcy. Zapisany, ale nic nie wznawia "
                  f"ani nie uchyla; jego pozycje trafią do „Do weryfikacji”.")
        if meta["zalaczniki_zablokowane"]:
            slack("mail od {} ({}) ma zablokowane załączniki: {}. Nie były otwierane ani używane jako dowód dostarczenia.".format(
                adres, klient, ", ".join(f"{n} ({p})" for n, p in meta["zalaczniki_zablokowane"])))
        if kl["typ"] == "domena":
            dodaj_kontakt_z_domeny(karty[klient], meta["od_adres"] or adres,
                                   meta["od_imie"] or nag["imie"], dzis)
            wynik["nowe_kontakty"].append(meta["od_adres"] or adres)
            wynik["zmienione_karty"].add(klient)
            slack(f"nowy nadawca z domeny klienta {klient}: {meta['od_adres'] or adres} dodany do kontaktów "
                  f"jako „{STATUS_NOWY}”. Jego maile mogą dodawać informacje, ale nie uchylają zakazów "
                  f"ani nie zmieniają decyzji. Potwierdź go w ops/klienci/{klient}/karta.json "
                  f"(potwierdzony: true).")

        sciezka = zapisz_mail_md(klient, meta, katalog_maili)
        rejestr["oczekujace"][mid] = {
            "klient": klient, "plik": sciezka.as_posix(), "data": meta["data"].date().isoformat(),
            "proby": 0, "status": "oczekuje"}
        wynik["nowe"].append((klient, sciezka, meta["temat"]))

    if wynik["nieznani"]:
        slack(f"pominięto {wynik['nieznani']} maili od nieznanych nadawców")
    return wynik


def do_przetworzenia(rejestr, slack, max_prob=MAX_PROB):
    """Lista maili do przetworzenia w tym przebiegu: nowe i ponawiane po nieudanej analizie.

    Każde wejście na listę to jedna próba (licznik rośnie od razu, więc awaria całego przebiegu
    też nie ponawia w nieskończoność). Mail, który wyczerpał próby, dostaje status "porzucony"
    i alert na Slacku (raz)."""
    lista = []
    for mid, wpis in rejestr["oczekujace"].items():
        if wpis.get("status") != "oczekuje":
            continue
        if wpis.get("proby", 0) >= max_prob:
            wpis["status"] = "porzucony"
            temat = wczytaj_meta_maila(wpis["plik"]).get("temat", "(bez tematu)")
            slack(f"mail „{slack_bezpiecznie(temat)}” ({wpis.get('klient', '?')}) porzucony po {max_prob} "
                  f"nieudanych próbach przetworzenia. Plik: {wpis['plik']}. Ponów ręcznie: workflow "
                  f"„Sprawdzanie maili” z polem sciezka.")
            continue
        wpis["proby"] = wpis.get("proby", 0) + 1
        lista.append(Path(wpis["plik"]))
    return lista


def oznacz_przetworzony(sciezka_md, rejestr_path=None):
    """Wywołuje przetworz.py po UDANYM przetworzeniu maila: Message-ID przechodzi do "przetworzone".
    Zwraca True, gdy rejestr zmieniono (starsze pliki maili bez Message-ID są pomijane)."""
    mid = wczytaj_meta_maila(sciezka_md).get("message_id")
    if not mid:
        return False
    sciezka_rejestru = Path(rejestr_path) if rejestr_path else REJESTR_PATH
    rejestr = wczytaj_rejestr(sciezka_rejestru)
    wpis = rejestr["oczekujace"].pop(mid, {})
    meta = wczytaj_meta_maila(sciezka_md)
    rejestr["przetworzone"][mid] = {
        "klient": wpis.get("klient") or Path(str(sciezka_md)).parent.name,
        "plik": Path(str(sciezka_md)).as_posix(), "data": meta.get("data", "")}
    zapisz_rejestr(rejestr, sciezka_rejestru)
    return True


# ── IMAP (tylko odczyt) ───────────────────────────────────────────────────────

_MIESIACE = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _data_imap(d):
    return f"{d.day:02d}-{_MIESIACE[d.month - 1]}-{d.year}"   # bez locale: IMAP wymaga angielskich skrótów


class SkrzynkaIMAP:
    """Gmail IMAP otwarty read-only. Używa wyłącznie SELECT readonly, SEARCH i FETCH BODY.PEEK."""

    def __init__(self, adres, haslo, od):
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        self.m = imaplib.IMAP4_SSL(IMAP_HOST, ssl_context=ctx)
        self.m.login(adres, haslo)
        typ, _ = self.m.select("INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError("nie udało się otworzyć INBOX w trybie tylko do odczytu")
        self.od = od

    def uids(self):
        typ, dane = self.m.uid("SEARCH", None, "SINCE", _data_imap(self.od))
        if typ != "OK" or not dane or not dane[0]:
            return []
        return dane[0].split()

    def _pobierz(self, uid, czesc):
        typ, dane = self.m.uid("FETCH", uid, f"({czesc})")
        if typ != "OK":
            return b""
        for el in dane:
            if isinstance(el, tuple):
                return el[1]
        return b""

    def naglowki(self, uid):
        return self._pobierz(uid, f"BODY.PEEK[HEADER.FIELDS ({NAGLOWKI_IMAP})]")

    def tresc(self, uid):
        return self._pobierz(uid, "BODY.PEEK[]")

    def zamknij(self):
        try:
            self.m.logout()
        except Exception:  # noqa: BLE001
            pass


# ── main ──────────────────────────────────────────────────────────────────────

def _wczytaj_env():
    env_path = Path(".env")
    if env_path.exists():
        for linia in env_path.read_text(encoding="utf-8").splitlines():
            klucz, _, wartosc = linia.strip().partition("=")
            klucz = czysc(klucz)
            if klucz and not klucz.startswith("#") and "=" in linia:
                os.environ.setdefault(klucz, czysc(wartosc) if klucz.startswith("GMAIL_") else wartosc.strip())
    wyczysc_srodowisko()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Pobiera maile od znanych nadawców (Gmail, tylko odczyt).")
    ap.add_argument("--lista", help="plik, do którego trafią ścieżki nowych maili")
    ap.add_argument("--dni", type=int, default=14, help="okno wyszukiwania w dniach")
    ap.add_argument("--sucho", action="store_true", help="nic nie zapisuje i nie wysyła na Slacka")
    args = ap.parse_args()

    _wczytaj_env()
    adres, haslo = os.environ.get("GMAIL_ADDRESS", ""), os.environ.get("GMAIL_APP_PASSWORD", "")
    if not adres or not haslo:
        print("BŁĄD: brak GMAIL_ADDRESS albo GMAIL_APP_PASSWORD (.env lub sekrety GitHuba).", file=sys.stderr)
        sys.exit(2)

    from przetworz import send_slack   # import tutaj: przetworz.py importuje maile.py

    def slack(tekst):
        print(f"Slack: {tekst}")
        if not args.sucho:
            send_slack(f":email: {tekst}")

    karty = wczytaj_karty()
    rejestr = wczytaj_rejestr()
    skrzynka = None
    try:
        dzis = date.today()
        # pierwszy przebieg zapisze datę włączenia w rejestrze; do tego czasu szukamy od dziś
        skrzynka = SkrzynkaIMAP(adres, haslo, okno_od(dzis, args.dni, rejestr.get("wlaczono") or dzis.isoformat()))
        wynik = przetworz_skrzynke(skrzynka, karty, rejestr, slack, dzis.isoformat())
        do_listy = do_przetworzenia(rejestr, slack)
    except (imaplib.IMAP4.error, OSError, RuntimeError) as exc:
        # komunikat bez haseł: tekst wyjątku IMAP nie zawiera danych logowania
        print(f"BŁĄD IMAP: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if skrzynka:
            skrzynka.zamknij()

    if not args.sucho:
        zapisz_rejestr(rejestr)
        for klient in wynik["zmienione_karty"]:
            zapisz_karte(klient, karty[klient])
        if args.lista:
            Path(args.lista).write_text(
                "".join(f"{p.as_posix()}\n" for p in do_listy), encoding="utf-8")

    print(f"Nowe maile: {len(wynik['nowe'])} | do przetworzenia (z ponowieniami): {len(do_listy)} "
          f"| automatyczne pominięte: {wynik['automatyczne']} | nieznani nadawcy: {wynik['nieznani']} "
          f"| nowe kontakty z domeny: {len(wynik['nowe_kontakty'])}")
    for p in do_listy:
        print(f"  {p}")


if __name__ == "__main__":
    main()
