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
  * Rejestr ops/.maile.json: ten sam Message-ID nigdy nie jest przetwarzany dwa razy.
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


def czysc_tresc(tekst):
    """Usuwa cytowane wcześniejsze wiadomości i stopkę; zostawia to, co klient napisał nowego."""
    linie = tekst.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # 1) pierwszy nagłówek cytatu ucina resztę (Gmail zawija go na dwie linie, więc sprawdzamy też parę)
    for i, linia in enumerate(linie):
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

    zalaczniki = []
    for czesc in msg.iter_attachments():
        nazwa = czesc.get_filename()
        if nazwa:
            zalaczniki.append(_jedna_linia(nazwa))

    cialo = msg.get_body(preferencelist=("plain", "html"))
    tekst = ""
    if cialo is not None:
        tekst = cialo.get_content()
        if cialo.get_content_type() == "text/html":
            tekst = html_do_tekstu(tekst)

    return {
        "message_id": _jedna_linia(msg.get("Message-ID", "")),
        "od_imie": _jedna_linia(imie),
        "od_adres": normalizuj_adres(adres),
        "do": _jedna_linia(msg.get("To", "")),
        "data": data,
        "temat": _jedna_linia(msg.get("Subject", "")) or "(bez tematu)",
        "zalaczniki": zalaczniki,
        "tresc": czysc_tresc(tekst),
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
    tresc = meta["tresc"] or "(pusta treść)"
    sciezka.write_text(
        f"# Mail: {meta['temat']}\n\n"
        f"- **Od:** {od}\n"
        f"- **Do:** {meta['do']}\n"
        f"- **Data:** {meta['data'].strftime('%Y-%m-%d %H:%M')}\n"
        f"- **Temat:** {meta['temat']}\n"
        f"- **Załączniki:** {zal}\n\n"
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
    return meta


# ── rejestr ───────────────────────────────────────────────────────────────────

def wczytaj_rejestr(path=REJESTR_PATH):
    if Path(path).exists():
        r = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        r = {}
    r.setdefault("przetworzone", {})   # Message-ID → {klient, plik, data}
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

def _naglowek_nadawcy(surowe_naglowki):
    msg = email.message_from_bytes(surowe_naglowki, policy=POLITYKA)
    imie, adres = parseaddr(str(msg.get("From", "")))
    mid = _jedna_linia(msg.get("Message-ID", ""))
    if not mid:
        # brak Message-ID: stabilny zastępczy identyfikator z nagłówków
        mid = "brak-id:" + _hash(surowe_naglowki.decode("utf-8", "replace"))
    return _jedna_linia(imie), normalizuj_adres(adres), mid


def przetworz_skrzynke(skrzynka, karty, rejestr, slack, dzis, katalog_maili=MAILE_DIR):
    """skrzynka ma: uids(), naglowki(uid) → bajty, tresc(uid) → bajty (pełny mail).

    Zwraca {"nowe": [(klient, sciezka, temat)], "nieznani": n, "nowe_kontakty": [adres],
            "zmienione_karty": {klient}}. Treść pobierana jest tylko od znanych nadawców.
    """
    wynik = {"nowe": [], "nieznani": 0, "nowe_kontakty": [], "zmienione_karty": set()}
    for uid in skrzynka.uids():
        imie, adres, mid = _naglowek_nadawcy(skrzynka.naglowki(uid))
        if mid in rejestr["przetworzone"]:
            continue

        kl = klasyfikuj_nadawce(adres, karty)
        if kl["typ"] == "nieznany":
            klucz = _hash(adres)
            wpis = rejestr["nieznani"].setdefault(klucz, {"liczba": 0, "ids": []})
            if _hash(mid) in wpis["ids"]:
                continue
            pierwszy = wpis["liczba"] == 0
            wpis["liczba"] += 1
            wpis["ids"].append(_hash(mid))
            wynik["nieznani"] += 1
            if pierwszy:
                slack(f"pominięto mail od nieznanego nadawcy {adres}")
            continue

        # znany nadawca (kontakt albo domena klienta): dopiero teraz pobieramy treść
        meta = parsuj_wiadomosc(skrzynka.tresc(uid))
        klient = kl["klient"]
        if kl["typ"] == "domena":
            dodaj_kontakt_z_domeny(karty[klient], meta["od_adres"] or adres,
                                   meta["od_imie"] or imie, dzis)
            wynik["nowe_kontakty"].append(meta["od_adres"] or adres)
            wynik["zmienione_karty"].add(klient)
            slack(f"nowy nadawca z domeny klienta {klient}: {meta['od_adres'] or adres} dodany do kontaktów "
                  f"jako „{STATUS_NOWY}”. Jego maile mogą dodawać informacje, ale nie uchylają zakazów "
                  f"ani nie zmieniają decyzji. Potwierdź go w ops/klienci/{klient}/karta.json "
                  f"(potwierdzony: true).")

        sciezka = zapisz_mail_md(klient, meta, katalog_maili)
        rejestr["przetworzone"][mid] = {
            "klient": klient, "plik": sciezka.as_posix(), "data": meta["data"].date().isoformat()}
        wynik["nowe"].append((klient, sciezka, meta["temat"]))
    return wynik


# ── IMAP (tylko odczyt) ───────────────────────────────────────────────────────

_MIESIACE = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _data_imap(d):
    return f"{d.day:02d}-{_MIESIACE[d.month - 1]}-{d.year}"   # bez locale: IMAP wymaga angielskich skrótów


class SkrzynkaIMAP:
    """Gmail IMAP otwarty read-only. Używa wyłącznie SELECT readonly, SEARCH i FETCH BODY.PEEK."""

    def __init__(self, adres, haslo, dni=14):
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
        self.dni = dni

    def uids(self):
        od = _data_imap(date.today() - timedelta(days=self.dni))
        typ, dane = self.m.uid("SEARCH", None, "SINCE", od)
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
        return self._pobierz(uid, "BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID DATE SUBJECT)]")

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
        skrzynka = SkrzynkaIMAP(adres, haslo, args.dni)
        wynik = przetworz_skrzynke(skrzynka, karty, rejestr, slack, date.today().isoformat())
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
                "".join(f"{p.as_posix()}\n" for _, p, _ in wynik["nowe"]), encoding="utf-8")

    print(f"Nowe maile: {len(wynik['nowe'])} | pominięci nieznani nadawcy: {wynik['nieznani']} "
          f"| nowe kontakty z domeny: {len(wynik['nowe_kontakty'])}")
    for klient, sciezka, temat in wynik["nowe"]:
        print(f"  [{klient}] {sciezka}  ({temat})")


if __name__ == "__main__":
    main()
