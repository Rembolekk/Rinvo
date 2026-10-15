#!/usr/bin/env python3
"""higiena.py – utwardzanie przetwarzania: przypadki brzegowe rozmów i maili, w czystym Pythonie (bez modelu, bez sieci).

Co robi kod, a nie model:
  * odcisk rozmowy (data, godzina, uczestnicy) i wykrycie ponownej transkrypcji tej samej rozmowy,
  * ocena kompletności transkrypcji (bardzo krótka, bez wypowiedzi klienta, urwana w pół zdania),
  * rozmowa wewnętrzna (nikogo ze strony klienta) i nowy klient (karta zakładana z rozmowy),
  * maskowanie danych osobowych (telefony, PESEL, adresy e-mail spoza kontaktów, nazwiska klientów końcowych),
  * znaczniki pozycji: niepewność i żart, pomyłka mówcy, „sprawdź z nagraniem”, pozycje innego klienta,
    źródło starsze niż stan karty, polecenia dla systemu w treści,
  * maile: uwierzytelnienie nadawcy, autoodpowiedzi (nieobecność), załączniki (wykonywalne, archiwa, duże),
    wiadomości przekazane, odpowiedzi na nasze maile (krótkie potwierdzenia zamykają zgłoszenia).
Znaczniki trafiają do wynik.json (pola „flagi” pozycji i „kontrola” wyniku); routing (Do weryfikacji zamiast Dla agenta)
robią zasady.py i linear_sync.py. Tabela przypadków i testów: README, sekcja „Przypadki brzegowe”.
"""

import re
from collections import Counter
from datetime import date
from pathlib import Path

MIESIACE = {"stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7,
            "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12}

# znaczniki → krótki opis w opisach zgłoszeń i raportach; WERYFIKACJA = nie trafia do agenta
FLAGI_OPISY = {
    "niepelna_transkrypcja": "niepełna transkrypcja",
    "zrodlo_starsze": "źródło starsze niż stan karty",
    "mozliwa_pomylka_mowcy": "możliwa pomyłka mówcy",
    "inny_klient": "pozycja dotyczy innego klienta",
    "nowy_klient": "nowy klient: karta do potwierdzenia",
    "rozmowa_wewnetrzna": "rozmowa wewnętrzna",
    "niepewne": "niepewne lub żartobliwe sformułowanie: to nie zobowiązanie ani decyzja",
    "nieuwierzytelniony_mail": "mail bez potwierdzonego DKIM/SPF dla domeny nadawcy",
    "przekazany_mail": "treść przekazana: informacja, nie decyzja",
    "zalacznik_zablokowany": "załącznik zablokowany: nie jest dowodem dostarczenia",
    "polecenie_w_tresci": "w treści jest polecenie dla systemu (zignorowane)",
}
FLAGI_WERYFIKACJA = set(FLAGI_OPISY) - {"rozmowa_wewnetrzna"}
FLAGA_NAGRANIE = "sprawdz_z_nagraniem"


# ── nagłówek rozmowy, odcisk, mówcy ───────────────────────────────────────────

def _imie_pelne(s):
    return re.sub(r"\s+", " ", s.replace("*", "")).strip()


def parsuj_naglowek_rozmowy(tekst):
    """{"data": date|None, "start": "11:00"|None, "godziny": str|None, "uczestnicy": [{"imie","firma","zespol"}], "wspominani": [...]}."""
    wyn = {"data": None, "start": None, "godziny": None, "uczestnicy": [], "wspominani": []}
    gora = tekst.split("## Transkrypcja", 1)[0]
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MIESIACE) + r")\s+(\d{4})", gora)
    if m:
        try:
            wyn["data"] = date(int(m.group(3)), MIESIACE[m.group(2)], int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})", gora)
    if m:
        wyn["start"], wyn["godziny"] = m.group(1), f"{m.group(1)}–{m.group(2)}"
    blok = re.search(r"## Uczestnicy\s*\n(.*?)(?:\n## |\Z)", tekst, re.S)
    if blok:
        for l in blok.group(1).splitlines():
            m = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*(.*)$", l)
            if m:
                reszta = [x.strip() for x in m.group(2).strip().lstrip(",").split(",") if x.strip()]
                firma = reszta[-1] if reszta else ""
                wyn["uczestnicy"].append({"imie": _imie_pelne(m.group(1)), "firma": firma, "zespol": "rinvo" in firma.lower()})
        m = re.search(r"Wspominani[^:]*:(.*)", blok.group(1))
        if m:
            wyn["wspominani"] = [_imie_pelne(x) for x in re.findall(r"\*\*(.+?)\*\*", m.group(1))]
    return wyn


def odcisk_rozmowy(tekst):
    """Odcisk rozmowy: data, godzina początku i uczestnicy (bez kolejności). None, gdy nagłówka nie da się odczytać."""
    h = parsuj_naglowek_rozmowy(tekst)
    if not (h["data"] and h["start"] and h["uczestnicy"]):
        return None
    return f"{h['data'].isoformat()}|{h['start']}|" + ";".join(sorted(u["imie"].casefold() for u in h["uczestnicy"]))


def powtorna_transkrypcja(odcisk, hash_tekstu, rejestr):
    """Wpis rejestru tej samej rozmowy (ten sam odcisk) zapisanej innym tekstem; None, gdy to nowa rozmowa albo ten sam tekst."""
    if not odcisk:
        return None
    for h, wpis in rejestr.items():
        if h != hash_tekstu and isinstance(wpis, dict) and wpis.get("odcisk") == odcisk:
            return wpis
    return None


def wypowiedzi(tekst):
    """[(mówca, tekst wypowiedzi)] z linii „**Imię:** …” sekcji transkrypcji."""
    cialo = tekst.split("## Transkrypcja", 1)[-1]
    return [(m.group(1).strip(), m.group(2).strip()) for m in re.finditer(r"^\*\*([^*:]+):\*\*\s*(.*)$", cialo, re.M)]


def _pasuje_imie(mowca, pelne):
    a, b = mowca.casefold().strip(), pelne.casefold().strip()
    return a == b or b.startswith(a + " ") or a.startswith(b + " ") or a == b.split()[0]


def ocena_kompletnosci(tekst, min_slow=80):
    """Powody, dla których transkrypcja jest niepełna (pusta lista = pełna)."""
    powody = []
    cialo = tekst.split("## Transkrypcja", 1)[-1]
    slow = len(re.findall(r"\w+", cialo))
    if slow < min_slow:
        powody.append(f"bardzo krótka ({slow} słów)")
    h = parsuj_naglowek_rozmowy(tekst)
    klienci = [u for u in h["uczestnicy"] if not u["zespol"]]
    if klienci:
        slow_klienta = sum(len(re.findall(r"\w+", t)) for m, t in wypowiedzi(tekst) if any(_pasuje_imie(m, u["imie"]) for u in klienci))
        if slow_klienta < 5:
            powody.append("bez wypowiedzi klienta")
    ostatnia = next((l.strip() for l in reversed(cialo.strip().splitlines()) if l.strip()), "")
    ostatnia = re.sub(r"^\*\*[^*]+:\*\*\s*", "", ostatnia).rstrip("*_ ")
    if ostatnia and not re.search(r"[.?!…»”\")]$", ostatnia):
        powody.append("urwana w pół zdania na końcu")
    return powody


def rozmowa_wewnetrzna(tekst):
    """True, gdy nikt ze strony klienta nie uczestniczył (wszyscy uczestnicy z zespołu Rinvo)."""
    uczestnicy = parsuj_naglowek_rozmowy(tekst)["uczestnicy"]
    return bool(uczestnicy) and all(u["zespol"] for u in uczestnicy)


# ── nowy klient ───────────────────────────────────────────────────────────────

def nazwa_z_naglowka(tekst):
    """Nazwa klienta z tytułu rozmowy („# Hotele Bałtyk × Rinvo: call…” → „Hotele Bałtyk”) z polskimi znakami; None, gdy się nie da."""
    m = re.match(r"\s*#\s*(.+)", tekst or "")
    if not m:
        return None
    for czesc in re.split(r"\s+[×x]\s+", m.group(1).split(":", 1)[0]):
        czesc = czesc.strip()
        if czesc and "rinvo" not in czesc.casefold():
            return czesc
    return None


def karta_nowego_klienta(klient, tekst, nazwa=None):
    """Karta założona z rozmowy: kontakty NIEPOTWIERDZONE, decydenci jako wniosek (nic do wysyłki, nic dla agenta)."""
    h = parsuj_naglowek_rozmowy(tekst)
    kontakty = [{"imie": u["imie"], "email": "", "rola": u["firma"] or "uczestnik rozmowy", "zakres_decyzji": "brak",
                 "potwierdzony": False, "status": "z rozmowy, do potwierdzenia"} for u in h["uczestnicy"] if not u["zespol"]]
    return {"klient": klient, "nazwa": nazwa or nazwa_z_naglowka(tekst) or klient.replace("-", " ").title(), "nowy_klient": True,
            "decydenci": [], "decydenci_wniosek": [{"imie": k["imie"], "rola": "wniosek z rozmowy, do potwierdzenia"} for k in kontakty],
            "kontakty": kontakty, "domeny": [], "zakazy": [], "otwarte_sprawy": {}, "ryzyka": {}}


# ── maskowanie danych osobowych ───────────────────────────────────────────────

_TEL = re.compile(r"(?<!\d)(?<!\d\.)(?:\+?48[\s-]?)?(?:\d{3}[\s-]\d{3}[\s-]\d{3}|\d{9})(?!\d)(?!\.\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
_WIELKA = r"[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+"
_PAN = re.compile(r"\b(?:[Pp]an|[Pp]ani|[Pp]anem|[Pp]anią|[Pp]anu|[Pp]ana|[Pp]aństwo|[Pp]aństwa)\s+(" + _WIELKA + r"(?:[ -]" + _WIELKA + r")?)")


def pesel_ok(s):
    if not re.fullmatch(r"\d{11}", s):
        return False
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(c) * k for c, k in zip(s, w)) % 10) % 10 == int(s[-1])


def _tokeny_znane(znane):
    t = set()
    for n in znane or []:
        for x in re.findall(r"[^\W\d_]+", str(n)):
            t.add(x.casefold())
    return t


_TYTULY = {"pan", "pani", "panem", "panią", "panu", "pana", "państwo", "państwa"}
_KONCOWKI_ZNANE = ("", "a", "owi", "em", "iem", "u", "ie", "y", "ą", "ę", "e", "i", "ego", "emu", "ym")


def jest_znany(tok, znane_t):
    """Czy token (w dowolnej odmianie) należy do znanej osoby: Robert = Roberta, Robertem, Robertowi, Robercie; Tomek = Tomka."""
    t = tok.casefold()
    for k in znane_t:
        if k in _TYTULY or len(k) < 3:
            continue
        if t == k or (t.startswith(k) and t[len(k):] in _KONCOWKI_ZNANE):
            return True
        if k.endswith("ek") and t.startswith(k[:-2] + "k") and t[len(k) - 1:] in _KONCOWKI_ZNANE:
            return True
        if len(k) >= 5 and t.startswith(k[:-1]) and len(t) - len(k) <= 4:        # Robert → Robercie, Joanna → Joannie
            return True
    return False


def osoby_z_naglowka(tekst):
    """Osoby wymienione w nagłówku rozmowy (przed „## Transkrypcja”): wszystko, co pogrubione, czyli uczestnicy, wspominani
    i osoby z rolą w kontekście. Takie osoby nie są maskowane: to ludzie ze strony klienta i naszej."""
    gora = tekst.split("## Transkrypcja", 1)[0]
    return [_imie_pelne(x) for x in re.findall(r"\*\*(.+?)\*\*", gora)]


def nazwiska_koncowe(tekst, znane=()):
    """Nazwiska osób TRZECICH (klienci końcowi, goście, leady) po zwrotach „pan/pani/państwo …”. Bez osób znanych w dowolnej
    odmianie: uczestnicy, wspominani, osoby z nagłówka, kontakty i decydenci z karty."""
    znane_t = _tokeny_znane(list(znane) + osoby_z_naglowka(tekst))
    wynik = set()
    for m in _PAN.finditer(tekst):
        for tok in re.split(r"[ -]", m.group(1)):
            if not jest_znany(tok, znane_t):
                wynik.add(tok)
    return wynik


_KONCOWKI = ("iego", "ego", "iemu", "emu", "iem", "em", "ym", "im", "owi", "ami", "ach", "ą", "ę", "a", "u", "y", "i", "e")


def _wzorzec_nazwiska(n):
    """Wzorzec obejmujący odmianę nazwiska: „Kowalskiego” → Kowalsk + końcówka (Kowalski, Kowalskiego, Kowalskim…)."""
    pnie = n
    for k in _KONCOWKI:
        if n.endswith(k) and len(n) - len(k) >= 4:
            pnie = n[:-len(k)]
            break
    return r"(?<![\w])" + re.escape(pnie) + r"(?:iego|ego|iemu|emu|iem|em|ym|im|owi|ami|ach|ą|ę|a|u|y|i|e)?(?![\w])"


def maskuj(tekst, dozwolone_maile=(), nazwiska=()):
    """(zamaskowany tekst, Counter rodzajów). Telefony, PESEL, adresy e-mail spoza dozwolonych, nazwiska z zestawu."""
    licznik = Counter()
    dozwolone = {d.casefold() for d in dozwolone_maile}

    def mail(m):
        if m.group(0).casefold() in dozwolone:
            return m.group(0)
        licznik["e-mail"] += 1
        return "[e-mail]"

    def pesel(m):
        if pesel_ok(m.group(0)):
            licznik["PESEL"] += 1
            return "[PESEL]"
        return m.group(0)

    t = _EMAIL.sub(mail, tekst)
    t = _PESEL.sub(pesel, t)

    def tel(m):
        licznik["telefon"] += 1
        return "[telefon]"

    t = _TEL.sub(tel, t)
    for n in sorted(nazwiska, key=len, reverse=True):
        t, k = re.subn(_wzorzec_nazwiska(n), "[nazwisko]", t)
        licznik["nazwisko"] += k
    return t, licznik


def maskuj_zrodlo(tekst, dozwolone_maile=(), znane=()):
    """Maskowanie transkrypcji/maila z wykrytymi nazwiskami. Zwraca (tekst, nazwiska, licznik)."""
    h = parsuj_naglowek_rozmowy(tekst)
    znane_wszystkie = list(znane) + [u["imie"] for u in h["uczestnicy"]] + h["wspominani"]
    nazw = nazwiska_koncowe(tekst, znane_wszystkie)
    t, k = maskuj(tekst, dozwolone_maile, nazw)
    return t, nazw, k


def maskuj_wynik(wynik, tekst_zrodla, dozwolone_maile=(), znane=()):
    """Maskuje wszystkie napisy w wynik.json (poza kluczami i polem źródła). Zwraca Counter; ustawia wynik["kontrola"]["maskowanie"]."""
    h = parsuj_naglowek_rozmowy(tekst_zrodla)
    znane_wszystkie = list(znane) + [u["imie"] for u in h["uczestnicy"]] + h["wspominani"] + list((wynik.get("spotkanie") or {}).get("uczestnicy", [])) \
        + list((wynik.get("spotkanie") or {}).get("wspominani", []))
    nazw = nazwiska_koncowe(tekst_zrodla, znane_wszystkie)
    licznik = Counter()

    def idz(o, klucz=None):
        if isinstance(o, str):
            if klucz in ("zrodlo",):
                return o
            t, k = maskuj(o, dozwolone_maile, nazw)
            licznik.update(k)
            return t
        if isinstance(o, list):
            return [idz(x, klucz) for x in o]
        if isinstance(o, dict):
            return {k: (v if k == "kontrola" else idz(v, k)) for k, v in o.items()}
        return o

    for klucz in list(wynik):
        if klucz != "kontrola":
            wynik[klucz] = idz(wynik[klucz], klucz)
    kontrola = wynik.setdefault("kontrola", {})
    kontrola["maskowanie"] = {"liczba": sum(licznik.values()), "rodzaje": dict(licznik)}
    return licznik


# ── znaczniki pozycji ─────────────────────────────────────────────────────────

def _tekst_pozycji(p):
    return " ".join([p.get("tytul", ""), p.get("opis", ""), p.get("cel", "")] + [c for c in p.get("cytat", []) if isinstance(c, str)]
                    + [k for k in p.get("kryteria_akceptacji", []) if isinstance(k, str)])


def _slowo(s, tekst):
    """Słowo jako cały wyraz; zakończone „*” – jako początek wyrazu („żartuj*” łapie „żartuję”)."""
    if s.endswith("*"):
        return re.search(r"(?<![\w])" + re.escape(s[:-1]), tekst, re.IGNORECASE)
    return re.search(r"(?<![\w])" + re.escape(s) + r"(?![\w])", tekst, re.IGNORECASE)


def niepewnosc(cytaty, K):
    """Słowa niepewności albo żartu w cytatach (lista trafień)."""
    tekst = " ".join(c for c in cytaty if isinstance(c, str))
    return [s for s in K["niepewnosc"] + K["zart"] if _slowo(s, tekst)]


def wartosci_do_sprawdzenia(p):
    """Liczby, godziny, adresy i kwoty w pozycji: [„15:00”, „Toruńska 120”, „1500 zł”]."""
    t = _tekst_pozycji(p)
    wyn = []
    for r in (r"\b\d{1,2}[:.]\d{2}\b", r"\b\d[\d\s]*(?:zł|PLN|%|proc\.)", r"\b(?:ul\.|ulica|al\.|aleja|pl\.)\s*[A-ZŁŚŻŹĆŃÓ][\w ]{2,25}\d+[a-z]?",
              r"\b[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+\s+\d{1,3}[a-z]?\b(?=[,.\s]|$)", r"\b\d{2}-\d{3}\b", r"\b(?:do|od|około|ok\.)\s+\d{1,2}(?::\d{2})?\b"):
        for m in re.finditer(r, t):
            v = " ".join(m.group(0).split())
            if v not in wyn:
                wyn.append(v)
    return wyn[:5]


def pomylka_mowcy(p, karta, tekst_zrodla):
    """Powód „możliwa pomyłka mówcy”, gdy decyzja zastrzeżona (karta) jest przypisana komuś bez prawa do niej
    (pole kto_zdecydowal albo mówca cytatu w transkrypcji), a treść pozycji wskazuje uprawnioną osobę. Inaczej None."""
    klucz = p.get("klucz_sprawy")
    cyt = [c for c in p.get("cytat", []) if isinstance(c, str)]
    for d in (karta or {}).get("decyzje_zastrzezone", []):
        if not (klucz and klucz in d.get("klucze_spraw", [])):
            continue
        uprawniony = d.get("zastrzezone_dla")
        uprawnieni = [uprawniony] if isinstance(uprawniony, str) else list(uprawniony or [])
        if not uprawnieni:
            continue
        if p.get("kto_zdecydowal"):
            przypisani = [p["kto_zdecydowal"]]
        else:
            przypisani = [m for m, t in wypowiedzi(tekst_zrodla) if any(" ".join(c.split())[:60] in " ".join(t.split()) for c in cyt)]
        if not przypisani or any(_pasuje_imie(a, u) or _pasuje_imie(u, a) for a in przypisani for u in uprawnieni):
            continue
        tekst = " ".join(cyt + [p.get("opis", ""), p.get("tytul", "")])
        if any(re.search(r"(?<![\w])" + re.escape(u.split()[0]) + r"(?![\w])", tekst) for u in uprawnieni):
            return "możliwa pomyłka mówcy"
    return None


POLECENIA = [r"ignor(?:e|uj)\w*\s+(?:all\s+|wszystk\w+\s+)?(?:previous|poprzedni\w+|instrukcj\w+|zasad\w+)", r"\bsystem\s*(?:prompt|:)", r"jesteś teraz\b",
             r"\bact as\b", r"zdejm(?:ij|ie)\w*\s+zakaz", r"uchyl\w*\s+(?:wszystkie\s+)?zakaz", r"usu[ńn]\w*\s+(?:wszystkie\s+)?zakaz",
             r"wy[śs]lij\w*\s+(?:maila?|wiadomo[śs][ćc])\s+do\s+wszystkich", r"nie\s+informuj\s+(?:człowieka|nikogo)", r"oznacz\s+jako\s+(?:zrobione|done)"]


def polecenia_w_tresci(tekst):
    """Fragmenty treści wyglądające na polecenia dla systemu (dane, nie polecenia: nie mają żadnego efektu, tylko ostrzeżenie)."""
    znalezione = []
    for r in POLECENIA:
        for m in re.finditer(r, tekst, re.IGNORECASE):
            znalezione.append(" ".join(tekst[max(0, m.start() - 10):m.end() + 40].split()))
    return znalezione[:5]


def _warianty_klienta(slug, karta):
    w = {slug, slug.replace("-", " "), slug.replace("-", "")}
    if karta:
        for k in ("nazwa", "klient"):
            if karta.get(k):
                w.add(str(karta[k]))
    return {x.casefold() for x in w if x and len(x) >= 4}


def inny_klient(p, klient, karty):
    """Slug innego klienta, jeśli pozycja wymienia go po nazwie, a nie wymienia bieżącego. karty: {slug: karta}."""
    tekst = _tekst_pozycji(p).casefold()
    wlasny = _warianty_klienta(klient, karty.get(klient))
    if any(w in tekst for w in wlasny):
        return None
    for slug, karta in karty.items():
        if slug != klient and any(re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", tekst) for w in _warianty_klienta(slug, karta)):
            return slug
    return None


def data_stanu_karty(karta):
    """Najnowsza data źródła, które karta już widziała (z nazw plików źródeł spraw, zakazów i ryzyk)."""
    daty = []
    for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):
        for w in (karta or {}).get(sekcja, {}).values():
            if isinstance(w, dict):
                daty += [_data_z_nazwy(z) for z in w.get("zrodla", [])]
    for r in ((karta or {}).get("ryzyka") or {}).values():
        daty += [_data_z_nazwy(x.get("zrodlo", "")) for x in r]
    daty = [d for d in daty if d]
    return max(daty) if daty else None


def _data_z_nazwy(sciezka):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", Path(str(sciezka)).name)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def zrodlo_starsze(data_zrodla, karta, zrodlo=None):
    """True, gdy źródło jest starsze niż stan karty (karta widziała już nowsze źródło niż to). Samo to źródło nie liczy się."""
    if not data_zrodla:
        return False
    inne = []
    for sekcja in ("otwarte_sprawy", "zamkniete_sprawy"):
        for w in (karta or {}).get(sekcja, {}).values():
            if isinstance(w, dict):
                inne += [_data_z_nazwy(z) for z in w.get("zrodla", []) if z != zrodlo]
    for r in ((karta or {}).get("ryzyka") or {}).values():
        inne += [_data_z_nazwy(x.get("zrodlo", "")) for x in r if x.get("zrodlo") != zrodlo]
    inne = [d for d in inne if d]
    return bool(inne) and data_zrodla < max(inne)


# ── adnotacja wyniku ──────────────────────────────────────────────────────────

def adnotuj_wynik(wynik, tekst_zrodla, klient, karta, karty, K, data_zrodla=None, zrodlo=None, meta_maila=None, nowy_klient=False):
    """Dopisuje do wynik.json znaczniki: pozycje[].flagi, kontrola (powody ogólne). Idempotentne (liczy od zera).
    meta_maila: słownik z maile.wczytaj_meta_maila (uwierzytelnienie, przekazany, zalaczniki_zablokowane)."""
    kontrola = wynik.setdefault("kontrola", {})
    for k in ("niepelna", "wewnetrzna", "starsze", "nowy_klient", "polecenia", "inny_klient", "mail"):
        kontrola.pop(k, None)
    meta_maila = meta_maila or {}
    if not meta_maila:
        niepelne = ocena_kompletnosci(tekst_zrodla, K.get("min_slow", 80))
        if niepelne:
            kontrola["niepelna"] = niepelne
        if rozmowa_wewnetrzna(tekst_zrodla):
            kontrola["wewnetrzna"] = True
    if nowy_klient:
        kontrola["nowy_klient"] = True
    if zrodlo_starsze(data_zrodla, karta, zrodlo):
        kontrola["starsze"] = True
    pol = polecenia_w_tresci(tekst_zrodla)
    if pol:
        kontrola["polecenia"] = pol
    if meta_maila.get("uwierzytelnienie") == "nie":
        kontrola.setdefault("mail", []).append("nieuwierzytelniony_mail")
    if meta_maila.get("przekazany"):
        kontrola.setdefault("mail", []).append("przekazany_mail")
    if meta_maila.get("zalaczniki_zablokowane"):
        kontrola.setdefault("mail", []).append("zalacznik_zablokowany")

    ogolne = []
    if kontrola.get("niepelna"):
        ogolne.append("niepelna_transkrypcja")
    if kontrola.get("starsze"):
        ogolne.append("zrodlo_starsze")
    if kontrola.get("nowy_klient"):
        ogolne.append("nowy_klient")
    if kontrola.get("wewnetrzna"):
        ogolne.append("rozmowa_wewnetrzna")
    ogolne += kontrola.get("mail", [])

    typy_decyzji = set(K["typy_zobowiazan"])
    inne_pozycje = []
    for p in wynik.get("pozycje", []):
        flagi = list(ogolne)
        cyt = [c for c in p.get("cytat", []) if isinstance(c, str)]
        if p.get("typ") in typy_decyzji:
            tr = niepewnosc(cyt, K)
            if tr:
                flagi.append("niepewne")
                p["pewnosc"] = "niska"
                p["niepewnosc_slowa"] = tr
        pm = pomylka_mowcy(p, karta, tekst_zrodla)
        if pm:
            flagi.append("mozliwa_pomylka_mowcy")
            p["pewnosc"] = "niska"
        ik = inny_klient(p, klient, karty)
        if ik:
            flagi.append("inny_klient")
            p["inny_klient"] = ik
            inne_pozycje.append(p.get("id"))
        if polecenia_w_tresci(" ".join(cyt)):
            flagi.append("polecenie_w_tresci")
        if p.get("typ") in K["typy_do_sprawdzenia"]:
            wart = wartosci_do_sprawdzenia(p)
            if wart:
                p["sprawdz_z_nagraniem"] = wart
        elif p.get("sprawdz_z_nagraniem"):
            p.pop("sprawdz_z_nagraniem")
        p["flagi"] = list(dict.fromkeys(flagi))
        if not p["flagi"]:
            p.pop("flagi")
    if inne_pozycje:
        kontrola["inny_klient"] = [i for i in inne_pozycje if i]
    for a in wynik.get("aktualizacje_spraw", []):
        if niepewnosc([a.get("cytat", "")], K):
            a["pewnosc"] = "niska"
            a["uzasadnienie"] = (a.get("uzasadnienie", "") + " [niepewne sformułowanie]").strip()
    return kontrola


def opis_znacznikow(p):
    """Linie do opisu zgłoszenia i raportu: [„⚠ …”]."""
    linie = [f"⚠ {FLAGI_OPISY[f]}" for f in p.get("flagi", []) if f in FLAGI_OPISY]
    if p.get("sprawdz_z_nagraniem"):
        linie.append("⚠ sprawdź z nagraniem: " + ", ".join(p["sprawdz_z_nagraniem"]))
    return linie


# ── maile ─────────────────────────────────────────────────────────────────────

WYKONYWALNE = {".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".js", ".jse", ".vbs", ".vbe", ".wsf", ".ps1", ".jar", ".sh", ".lnk", ".dll", ".apk",
               ".app", ".pif", ".reg", ".hta", ".cpl", ".msc", ".iso", ".dmg"}
ARCHIWA = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab", ".z"}


def klasa_zalacznika(nazwa, rozmiar, limit_mb=10):
    """„ok” albo powód blokady: „wykonywalny”, „archiwum”, „za duży”. Zablokowanych nie otwieramy i nie używamy jako dowodu dostarczenia."""
    n = str(nazwa).lower().strip()
    ext = "." + n.rsplit(".", 1)[-1] if "." in n else ""
    if ext in WYKONYWALNE or re.search(r"\.(exe|bat|js|vbs|scr|jar)\.[a-z0-9]{2,4}$", n):
        return "wykonywalny"
    if ext in ARCHIWA:
        return "archiwum"
    if (rozmiar or 0) > limit_mb * 1024 * 1024:
        return "za duży"
    return "ok"


def uwierzytelnienie(naglowek, domena):
    """True, gdy Authentication-Results ma dkim=pass albo spf=pass DLA domeny nadawcy. Brak nagłówka albo inna domena: False."""
    if not naglowek or not domena:
        return False
    d = domena.lower()
    for fragment in re.split(r";", str(naglowek)):
        f = fragment.lower()
        if re.search(r"\b(?:dkim|spf)=pass\b", f):
            if re.search(r"(?:header\.d|header\.i|smtp\.mailfrom|smtp\.helo|header\.from)=[^\s;]*" + re.escape(d) + r"\b", f):
                return True
    return False


def autoodpowiedz(naglowki, temat="", tresc=""):
    """True dla autoodpowiedzi: Auto-Submitted ≠ no, X-Autoreply, Precedence: auto_reply, temat „Out of office / Autoodpowiedź”, „jestem na urlopie”."""
    auto = str(naglowki.get("Auto-Submitted", "")).strip().lower()
    if auto and auto != "no":
        return True
    if naglowki.get("X-Autoreply") or naglowki.get("X-Autorespond") or str(naglowki.get("Precedence", "")).strip().lower() == "auto_reply":
        return True
    if re.search(r"out of office|automatic reply|auto[- ]?reply|autoodpowiedź|odpowiedź automatyczna|nieobecno[śs][ćc]", str(temat), re.I):
        return True
    return bool(re.search(r"jestem na urlopie|jestem nieobecn\w+|out of (?:the )?office|poza biurem", str(tresc), re.I))


def nieobecnosc_z_autoodpowiedzi(tresc, data_maila):
    """{"od": date, "do": date} z dat w autoodpowiedzi (daty.py liczy daty, nie model) albo None."""
    import daty
    d0 = data_maila if isinstance(data_maila, date) else daty.parse_date(str(data_maila))
    t = re.sub(r"\s+", " ", str(tresc))
    for wzor in (r"od\s+\d{1,2}(?:\.\d{1,2})?(?:\s+\w+)?\s+do\s+\d{1,2}(?:\.\d{1,2})?(?:\s+\w+)?", r"\d{1,2}\s*[–-]\s*\d{1,2}\.\d{1,2}(?:\.\d{2,4})?"):
        m = re.search(wzor, t, re.I)
        if m:
            tekst = m.group(0)
            mm = re.match(r"(\d{1,2})\s*[–-]\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", tekst)
            if mm:
                rok = int(mm.group(4)) + (2000 if mm.group(4) and len(mm.group(4)) == 2 else 0) if mm.group(4) else d0.year
                return {"od": date(rok, int(mm.group(3)), int(mm.group(1))), "do": date(rok, int(mm.group(3)), int(mm.group(2)))}
            r = daty.oblicz_wyrazenie(tekst, d0)
            if r and r.get("rodzaj") == "zakres":
                return {"od": r["od"], "do": r["do"]}
    m = re.search(r"(?:do|wr[óo]c[eę]|wracam)\s+(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?|\d{1,2}\s+\w+)", t, re.I)
    if m:
        dd = daty.znajdz_date(m.group(1), d0)
        if dd:
            return {"od": d0, "do": dd}
    return None


def dopisz_nieobecnosc(karta, adres, okres, zrodlo):
    """Dopisuje nieobecność do kontaktu o tym adresie; True, gdy dopisano (nie dubluje)."""
    for k in karta.get("kontakty", []):
        if str(k.get("email", "")).casefold() == str(adres).casefold():
            n = {"od": okres["od"].isoformat(), "do": okres["do"].isoformat(), "zrodlo": zrodlo, "skad": "autoodpowiedź"}
            if any(x.get("od") == n["od"] and x.get("do") == n["do"] for x in k.setdefault("nieobecnosci", [])):
                return False
            k["nieobecnosci"].append(n)
            return True
    return False


def przekazany(temat, tresc):
    """True, gdy mail jest wiadomością przekazaną (Fwd/PD/FW w temacie albo separator przekazania w treści)."""
    return bool(re.match(r"^\s*(?:fwd?|pd|przek)\s*:", str(temat), re.I)
                or re.search(r"-{2,}\s*(?:Forwarded message|Przekazana wiadomość|Wiadomość przekazana)", str(tresc), re.I))


def potwierdzenie_krotkie(tresc, K):
    """True, gdy odpowiedź to krótkie potwierdzenie („dzięki”, „będę”), bez pytań i nowych próśb."""
    t = re.sub(r"\s+", " ", str(tresc or "")).strip().lower()
    slow = re.findall(r"\w+", t)
    if not slow or len(slow) > K.get("max_slow_potwierdzenia", 12) or "?" in t:
        return False
    return any(re.search(r"(?<![\w])" + re.escape(s) + r"(?![\w])", t) for s in K["potwierdzenia"])


def znajdz_wyslany(in_reply_to, references, karty):
    """(klient, wpis historii_wysylek) maila, na który to odpowiedź (po In-Reply-To albo References); None, gdy to nie odpowiedź."""
    ids = [x for x in re.findall(r"<[^>]+>", f"{in_reply_to or ''} {references or ''}")]
    for klient, karta in karty.items():
        for w in karta.get("historia_wysylek", []):
            if w.get("message_id") in ids:
                return klient, w
    return None
