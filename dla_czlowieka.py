#!/usr/bin/env python3
"""dla_czlowieka.py – porządek w zgłoszeniach dla człowieka (Decyzja człowieka, Do weryfikacji, Szkic gotowy).

Stały układ każdego takiego zgłoszenia:
  * tytuł zaczyna się od czynności („Wyślij:”, „Zdecyduj:”, „Sprawdź:”, „Uzupełnij:”), potem krótki opis (do 60 znaków),
  * na górze opisu blok: Co masz zrobić / Dlaczego Ty / (gotowy mail: Do, Temat, treść, Załączniki, Kiedy wyjdzie) / Twoje ruchy,
  * pod linią „---”: kontekst, cytaty, zakazy (to, co było w opisie dotąd).
Treść maila do wysłania pochodzi z tego bloku: wersja poprawiona przez człowieka wygrywa (wyslij.py), a komentarze ze szkicami
zostają jako historia. Etykieta „Odrzuć”: zgłoszenie Canceled, wpis w karcie („odrzucone przez człowieka”), nie tworzymy go
ponownie z tego samego źródła. Widok „Dla mnie dziś” (widok.py) i kolejność w porannym podsumowaniu: po terminie, termin dziś, reszta
według priorytetu.

Użycie:
  python3 dla_czlowieka.py --przelicz              # pokaż, jak zmieniłyby się istniejące zgłoszenia dla człowieka
  python3 dla_czlowieka.py --przelicz --zastosuj   # przelicz je do nowego układu w Linearze
"""

import argparse
import re
import sys
from datetime import date, datetime, timedelta

import slack_widok as sw

START = "**Co masz zrobić:**"
RUCHY_LINIA = "**Twoje ruchy:**"
POWOD_ODRZUCENIA = "odrzucone przez człowieka"
STANY_ZAMKNIETE = ("Done", "Canceled", "Cancelled")
_CZYNNOSC_RE = re.compile(r"^(?:Wyślij|Zdecyduj|Sprawdź|Uzupełnij):\s*|^Potwierdź kartę klienta\s*")
_CZASOWNIK_RE = re.compile(r"^(?:wyślij|wysłać|zdecyduj|sprawdź|uzupełnij)\s+", re.IGNORECASE)
_DNI = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]


def _n(opis):
    """Opis do porównań: Linear normalizuje puste linie i końcowy newline, więc porównujemy bez tych różnic."""
    return re.sub(r"\n{3,}", "\n\n", (opis or "").replace("\r\n", "\n")).strip()


# ── tytuł ─────────────────────────────────────────────────────────────────────

def tytul_merytoryczny(tytul):
    """Tytuł bez „[klient] ” i bez czynności na początku."""
    t = re.sub(r"^\[[^\]]+\]\s*", "", tytul or "").strip()
    return _CZYNNOSC_RE.sub("", t).strip()


def prefiks_klienta(tytul):
    m = re.match(r"^(\[[^\]]+\])\s*", tytul or "")
    return m.group(1) if m else ""


def skroc(tekst, limit=60):
    """Do limit znaków, cięcie na granicy wyrazu, z wielokropkiem liczonym w limicie."""
    t = re.sub(r"\s+", " ", str(tekst or "")).strip()
    if len(t) <= limit:
        return t
    t = t[: limit - 1]
    if " " in t:
        t = t.rsplit(" ", 1)[0]
    return t.rstrip(" ,.;:–-") + "…"


def tytul_zgloszenia(tytul, czynnosc, Z):
    """„[klient] Czynność: krótki opis”; opis do dla_czlowieka.max_znakow_opisu_tytulu znaków."""
    opis = _CZASOWNIK_RE.sub("", tytul_merytoryczny(tytul)).strip() or tytul_merytoryczny(tytul)
    limit = Z["dla_czlowieka"]["max_znakow_opisu_tytulu"]
    pref = prefiks_klienta(tytul)
    return f"{pref} {czynnosc}: {skroc(opis, limit)}".strip()


def ma_uklad(tytul):
    return bool(_CZYNNOSC_RE.match(tytul_bez_klienta(tytul)))


def tytul_bez_klienta(tytul):
    return re.sub(r"^\[[^\]]+\]\s*", "", tytul or "").strip()


# ── czynność i powód ──────────────────────────────────────────────────────────

def czynnosc_dla(etykiety, opis, Z, reguly=None):
    """„Wyślij” (Szkic gotowy), „Zdecyduj” (Decyzja człowieka), „Uzupełnij” albo „Sprawdź” (Do weryfikacji); None, gdy to nie
    zgłoszenie dla człowieka."""
    E, et = Z["etykiety"], set(etykiety or [])
    if E["karta"] in et:
        return "Potwierdź"
    if E["szkic"] in et or E["wyslij"] in et:
        return "Wyślij"
    if E["czlowiek"] in et:
        # jedyny powód to „trafia do klienta”: człowiek tylko wysyła (agent przygotowuje szkic); inne powody wymagają decyzji
        return "Wyślij" if reguly and set(reguly) == {"do_klienta"} else "Zdecyduj"
    if E["weryfikacja"] in et:
        niski = (opis or "").lower()
        return "Uzupełnij" if any(s in niski for s in Z["dla_czlowieka"]["slowa_uzupelnij"]) else "Sprawdź"
    return None


def czy_dla_czlowieka(etykiety, Z):
    E = Z["etykiety"]
    return bool(set(etykiety or []) & {E["szkic"], E["czlowiek"], E["weryfikacja"], E["wyslij"]})


def dlaczego_ty(przypisanie, etykiety, Z, czynnosc=None):
    """Jedno słowo powodu: pieniądze, klient, zakaz, decyzja albo weryfikacja (slack_widok.slowo_powodu)."""
    if czynnosc == "Wyślij" and not (przypisanie or {}).get("reguly"):
        return "klient"
    return sw.slowo_powodu(przypisanie, etykiety, Z)


def co_masz_zrobic(czynnosc, tytul, odbiorca=None, powod=None):
    t = skroc(tytul_merytoryczny(tytul), 120)
    if powod and czynnosc in ("Sprawdź", "Uzupełnij"):
        return f"{'Uzupełnij' if czynnosc == 'Uzupełnij' else 'Sprawdź'}: {skroc(powod, 220)}"
    if czynnosc == "Wyślij":
        return f"Przeczytaj gotowy mail do {odbiorca} i wyślij go." if odbiorca else f"Wyślij wiadomość do klienta: {t}."
    if czynnosc == "Zdecyduj":
        return f"Podejmij decyzję w sprawie: {t}."
    if czynnosc == "Uzupełnij":
        return f"Uzupełnij brakujące dane, żeby sprawa mogła ruszyć: {t}."
    return f"Sprawdź zgłoszenie i potwierdź, że można je realizować: {t}."


# ── czas wysyłki ──────────────────────────────────────────────────────────────

def najblizsze_okno(teraz, W):
    """Najbliższy moment, w którym mail może wyjść: teraz (w oknie) albo początek najbliższego okna (dzień roboczy, godziny z reguł)."""
    import wyslij as wy
    t = wy.lokalnie(teraz, W)
    for przesuniecie in range(0, 21):
        dzien = (t + timedelta(days=przesuniecie)).replace(hour=W["godziny"]["od"], minute=0, second=0, microsecond=0)
        if dzien.weekday() not in W["dni_robocze"] or dzien.date().isoformat() in W["swieta"]:
            continue
        koniec = dzien.replace(hour=W["godziny"]["do"])
        if przesuniecie == 0:
            if t >= koniec:
                continue
            return t if t >= dzien else dzien
        return dzien
    return t


def kiedy_wyjdzie(teraz, W):
    """Tekst do bloku: kiedy mail wyjdzie po dodaniu etykiety „Wyślij” (z uwzględnieniem okna wysyłki)."""
    import wyslij as wy
    ok, _ = wy.okno_wysylki(teraz, W)
    okno = najblizsze_okno(teraz, W)
    dzien = f"{_DNI[okno.weekday()]} {okno.day}.{okno.month:02d}"
    if ok:
        return f"zaraz po dodaniu „Wyślij” (dziś, {dzien}, do {W['godziny']['do']}:00 czasu polskiego)"
    return f"{dzien} od {okno.hour}:00 (najbliższe okno wysyłki: dni robocze {W['godziny']['od']}:00–{W['godziny']['do']}:00)"


# ── blok ──────────────────────────────────────────────────────────────────────

def zloz_blok(co, dlaczego, mail=None, ruchy=None):
    """Tekst bloku. mail: {"do","temat","tresc","zgloszenia","zalaczniki","spotkanie","kiedy"} albo {"zbiorczy": "RIN-x"}."""
    import wyslij as wy
    linie = [f"{START} {co}", f"**Dlaczego Ty:** {dlaczego}"]
    if mail and mail.get("zbiorczy"):
        linie += ["", f"**Gotowy mail:** treść jest w zgłoszeniu {mail['zbiorczy']}; etykieta „Wyślij” wysyła mail całej grupy."]
    elif mail:
        linie += ["", "**Gotowy mail**"] + wy.czesc_maila(mail["do"], mail["temat"], mail["tresc"], mail.get("zgloszenia") or [],
                                                          mail.get("spotkanie"), mail.get("zalaczniki") or (), mail.get("kiedy"))
    linie += ["", f"{RUCHY_LINIA} " + (ruchy or "etykieta „Odrzuć” | zdecyduj i zamknij zgłoszenie (Done)")]
    return "\n".join(linie)


RUCHY_MAIL = "etykieta „Wyślij” | etykieta „Odrzuć” | popraw treść w tym bloku i daj „Wyślij”"


def rozdziel(opis):
    """(blok, kontekst): blok to początek opisu od „Co masz zrobić:” do linii „Twoje ruchy:”; kontekst to reszta po linii „---”.
    Bez bloku: (None, cały opis)."""
    tekst = (opis or "").replace("\r\n", "\n")
    if not tekst.lstrip().startswith(START):
        return None, tekst
    linie = tekst.lstrip().split("\n")
    idx = next((i for i, l in enumerate(linie) if l.startswith(RUCHY_LINIA)), None)
    if idx is None:
        return None, tekst
    blok = "\n".join(linie[: idx + 1])
    reszta = "\n".join(linie[idx + 1:]).lstrip("\n")
    if reszta.startswith("---"):
        reszta = reszta[3:].lstrip("\n")
    return blok, reszta


def zloz_opis(blok, kontekst):
    return blok + "\n\n---\n\n" + (kontekst or "").strip() + "\n"


def parsuj_blok(opis):
    """Gotowy mail z bloku w opisie: słownik jak z wyslij.parsuj_szkic, {"zbiorczy": "RIN-x"} albo None (brak bloku, brak maila)."""
    import wyslij as wy
    blok, _ = rozdziel(opis)
    if not blok:
        return None
    m = re.search(r"^\*\*Gotowy mail:\*\*.*?zgłoszeniu (RIN-\d+)", blok, re.M)
    if m:
        return {"zbiorczy": m.group(1)}
    i = blok.find("**Gotowy mail**")
    if i < 0:
        return None
    return wy.parsuj_czesc_maila(blok[i:])


def kontekst_opisu(opis):
    return rozdziel(opis)[1]


# ── przebudowa zgłoszenia do układu ───────────────────────────────────────────

def przebuduj(zg, Z, teraz, komentarze=(), przypisanie=None, mail=None, kontekst=None, W=None, powod=None):
    """(tytuł, opis, czynność) zgłoszenia w nowym układzie albo None, gdy to nie zgłoszenie dla człowieka. Czysta funkcja.
    mail: nowy szkic (wygrywa); inaczej mail z bloku w opisie (wersja człowieka), inaczej z najnowszego komentarza ze szkicem.
    kontekst: opis bez bloku (domyślnie z istniejącego opisu)."""
    import wyslij as wy
    W = W or Z["wysylka"]
    opis_stary = zg.get("description") or ""
    if prefiks_klienta(zg.get("title")) == "[produkt]" or Z["etykiety"]["karta"] in (zg.get("labels") or []):
        return None                                                  # propozycje produktowe i „Potwierdź kartę klienta” mają własny układ
    # „Uzupełnij” rozpoznajemy po kontekście i powodzie, nie po samym bloku (jego treść powstaje z tytułu: inaczej czynność by migała)
    czynnosc = czynnosc_dla(zg.get("labels"), kontekst_opisu(opis_stary) + " " + (powod or ""), Z, (przypisanie or {}).get("reguly"))
    if czynnosc is None:
        return None
    ctx = kontekst if kontekst is not None else kontekst_opisu(opis_stary)
    szkic = mail
    if szkic is None and czynnosc == "Wyślij":
        szkic = parsuj_blok(opis_stary) or wy.parsuj_szkic(list(komentarze))
    if szkic is not None and not szkic.get("zbiorczy"):
        szkic = {**szkic, "kiedy": kiedy_wyjdzie(teraz, W)}
    odbiorca = (szkic or {}).get("do")
    co = co_masz_zrobic(czynnosc, zg.get("title"), odbiorca, powod)
    if czynnosc == "Wyślij" and szkic is None:
        co = f"Szkic maila jeszcze nie powstał albo wymaga poprawy: {skroc(tytul_merytoryczny(zg.get('title')), 100)}."
    blok = zloz_blok(co, dlaczego_ty(przypisanie, zg.get("labels"), Z, czynnosc), szkic,
                     RUCHY_MAIL if szkic is not None else None)
    return tytul_zgloszenia(zg.get("title"), czynnosc, Z), zloz_opis(blok, ctx), czynnosc


def zastosuj_uklad(s, zg, komentarze=None, przypisanie=None, mail=None, powod=None):
    """Zapisuje w Linearze nowy układ zgłoszenia (jeśli się zmienił). Zwraca czynność albo None."""
    kom = komentarze if komentarze is not None else s.linear.komentarze(zg)
    wynik = przebuduj(zg, s.Z, s.teraz(), kom, przypisanie, mail, powod=powod)
    if wynik is None:
        return None
    tytul, opis, czynnosc = wynik
    if tytul != zg.get("title") or _n(opis) != _n(zg.get("description")):
        s.linear.ustaw_uklad(zg, tytul, opis)
    return czynnosc


def zdejmij_uklad(zg, tytul_oryginalny=None):
    """(tytuł bez czynności, opis bez bloku): zgłoszenie przestaje być zgłoszeniem dla człowieka (np. wycofany szkic, sprawa wróciła do agenta).
    tytul_oryginalny: pełny tytuł z karty klienta (tytuł w układzie jest skrócony do 60 znaków)."""
    pref = prefiks_klienta(zg.get("title"))
    tytul = f"{pref} {tytul_oryginalny or tytul_merytoryczny(zg.get('title'))}".strip()
    blok, kontekst = rozdziel(zg.get("description"))
    return tytul, (kontekst.strip() + "\n") if blok else (zg.get("description") or "")


# ── kolejność „Dla mnie dziś” ─────────────────────────────────────────────────

def klucz_dla_mnie(z, dzis):
    """Klucz sortowania „Dla mnie dziś”: po terminie (najstarszy termin pierwszy), termin dziś, reszta według priorytetu Lineara
    (1 pilny … 4 niski, bez priorytetu na końcu), na końcu numer zgłoszenia."""
    t = z.get("dueDate")
    try:
        d = date.fromisoformat(t[:10]) if t else None
    except ValueError:
        d = None
    pr = z.get("priority") or z.get("priorytet") or 0
    pr = pr if pr else 9
    if d and d < dzis:
        grupa, w_grupie = 0, (d.isoformat(), pr)
    elif d and d == dzis:
        grupa, w_grupie = 1, ("", pr)
    else:
        grupa, w_grupie = 2, ("", pr)
    numer = int(re.sub(r"\D", "", z.get("identifier", "0")) or 0)
    return (grupa, w_grupie, numer)


def kolejnosc_dla_mnie(zgloszenia, dzis):
    """Sortuje zgłoszenia (słowniki z dueDate i priority) według klucz_dla_mnie."""
    return sorted(zgloszenia, key=lambda z: klucz_dla_mnie(z, dzis))


# ── ruch „Odrzuć” ─────────────────────────────────────────────────────────────

def _klient(tytul):
    m = re.match(r"^\[([^\]]+)\]", tytul or "")
    return m.group(1) if m else ""


def odrzuc(s, zg):
    """Etykieta „Odrzuć”: zgłoszenie Canceled, wpis w karcie („odrzucone przez człowieka”), brak ponownego tworzenia z tego samego źródła.
    Propozycje produktowe (zgłoszenie „[produkt]”) oznacza jako odrzucone w stanie propozycji."""
    E = s.Z["etykiety"]
    if zg.get("state") in STANY_ZAMKNIETE:
        s.linear.usun_etykiete(zg, E["odrzuc"])
        return {"status": "pominiete", "powod": "zgłoszenie już zamknięte", "zgloszenie": zg["identifier"]}
    klient = _klient(zg.get("title"))
    if getattr(s, "sucho", False):
        return {"status": "odrzucilby", "zgloszenie": zg["identifier"]}
    s.linear.ustaw_stan(zg, "Canceled")
    for nazwa in (E["wyslij"], E["odrzuc"]):
        s.linear.usun_etykiete(zg, nazwa)
    s.linear.komentarz(zg, "Odrzucone przez człowieka (etykieta „Odrzuć”). Nie utworzę tego zgłoszenia ponownie z tego samego źródła.")
    klucz = None
    if klient == "produkt":
        import propozycje
        klucz = propozycje.oznacz_odrzucona(s, zg)
    else:
        karta = s.wczytaj_karte(klient)
        for k, wpis in list((karta.get("otwarte_sprawy") or {}).items()):
            if isinstance(wpis, dict) and wpis.get("identifier") == zg["identifier"]:
                kiedy = s.teraz().date().isoformat()
                karta.setdefault("odrzucone", {})[k] = {**wpis, "powod": POWOD_ODRZUCENIA, "kiedy": kiedy}
                del karta["otwarte_sprawy"][k]
                klucz = k
                s.zapisz_karte(klient, karta)
                break
    return {"status": "odrzucone", "zgloszenie": zg["identifier"], "klucz": klucz}


def obsluz_odrzucenia(s):
    wyniki = []
    for zg in s.linear.z_etykieta(s.Z["etykiety"]["odrzuc"]):
        try:
            wyniki.append(odrzuc(s, zg))
        except Exception as exc:  # noqa: BLE001  (jedno zgłoszenie nie zatrzymuje reszty)
            wyniki.append({"status": "blad", "powod": str(exc)[:160], "zgloszenie": zg["identifier"]})
    return wyniki


def czy_blokuje_odrzucenie(odrzucone_wpis, zrodlo):
    """Czy wpis „odrzucone” blokuje utworzenie zgłoszenia ze źródła. Usunięte przez człowieka w Linearze: zawsze;
    odrzucone etykietą „Odrzuć”: tylko z tego samego źródła (nowe źródło o tym samym może zgłosić sprawę od nowa)."""
    if odrzucone_wpis.get("powod") != POWOD_ODRZUCENIA:
        return True
    return zrodlo in (odrzucone_wpis.get("zrodla") or [])


# ── przeliczenie istniejących zgłoszeń ────────────────────────────────────────

def przelicz(s, zastosuj=False):
    """Istniejące otwarte zgłoszenia dla człowieka → nowy układ. Zwraca [(identyfikator, stary tytuł, nowy tytuł, czynność)].
    Mail z bloku (wersja człowieka) albo z najnowszego komentarza ze szkicem; kontekst z dotychczasowego opisu."""
    wynik = []
    for zg in sorted(s.linear.otwarte(["Backlog", "Todo", "In Progress"]), key=lambda z: z["identifier"]):
        if not czy_dla_czlowieka(zg.get("labels"), s.Z):
            # sprawa przestała być dla człowieka (np. etykiety po przeliczeniu), a ma jeszcze tytuł od czynności i blok: zdejmujemy układ
            klient = _klient(zg.get("title"))
            if (ma_uklad(zg.get("title")) or rozdziel(zg.get("description"))[0]) and klient != "produkt" and s.Z["etykiety"]["karta"] not in (zg.get("labels") or []):
                oryg = None
                if klient:
                    for wpis in (s.wczytaj_karte(klient).get("otwarte_sprawy") or {}).values():
                        if isinstance(wpis, dict) and wpis.get("identifier") == zg["identifier"]:
                            oryg = wpis.get("tytul")
                tytul, opis = zdejmij_uklad(zg, oryg)
                if (tytul, _n(opis)) != (zg.get("title"), _n(zg.get("description"))):
                    wynik.append((zg["identifier"], zg.get("title"), tytul, "bez układu"))
                    if zastosuj:
                        s.linear.ustaw_uklad(zg, tytul, opis)
            continue
        klient = _klient(zg.get("title"))
        przyp = None
        if klient and klient != "produkt":
            karta = s.wczytaj_karte(klient)
            for wpis in (karta.get("otwarte_sprawy") or {}).values():
                if isinstance(wpis, dict) and wpis.get("identifier") == zg["identifier"]:
                    przyp = wpis.get("przypisanie")
                    break
        nowy = przebuduj(zg, s.Z, s.teraz(), s.linear.komentarze(zg), przyp)
        if nowy is None:
            continue
        tytul, opis, czynnosc = nowy
        if tytul == zg.get("title") and _n(opis) == _n(zg.get("description")):
            continue
        wynik.append((zg["identifier"], zg.get("title"), tytul, czynnosc))
        if zastosuj:
            s.linear.ustaw_uklad(zg, tytul, opis)
    return wynik


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Układ zgłoszeń dla człowieka.")
    ap.add_argument("--przelicz", action="store_true", help="przelicz istniejące zgłoszenia dla człowieka do nowego układu")
    ap.add_argument("--zastosuj", action="store_true", help="zapisz zmiany w Linearze (bez tego tylko raport)")
    args = ap.parse_args()
    if not args.przelicz:
        ap.print_help()
        return
    import wyslij as wy
    s = wy.zbuduj_srodowisko(sucho=False)
    zmiany = przelicz(s, args.zastosuj)
    for ident, stary, nowy, czynnosc in zmiany:
        print(f"{ident}: {czynnosc}\n   {stary}\n → {nowy}")
    print(f"\nZgłoszeń dla człowieka do przeliczenia: {len(zmiany)}" + ("" if args.zastosuj else "  (raport; nic nie zmieniono)"))
    if args.zastosuj:
        import stan_linear
        stan_linear.po_przebiegu()


if __name__ == "__main__":
    main()
