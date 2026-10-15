#!/usr/bin/env python3
"""karta_klienta.py – nowy klient: JEDNO zgłoszenie „Potwierdź kartę klienta <nazwa>” zamiast oznaczania wszystkich jego spraw jako wymagających człowieka.

Karta nowego klienta (nowy_klient: true) powstaje z rozmowy, z kontaktami i decydentami „do potwierdzenia”. Wtedy:
  * człowiek dostaje jedno zgłoszenie „Potwierdź kartę klienta …” z krótką listą kontaktów i decydentów (etykiety Do weryfikacji + Karta do potwierdzenia),
  * pozostałe sprawy klienta mają normalny podział (agent, czeka na klienta, produkt, ryzyko, decyzja), ale też etykietę „Wstrzymane do potwierdzenia karty”:
    agent ich nie bierze i nie liczą się jako „Wymaga Ciebie”,
  * po potwierdzeniu karty (zgłoszenie Done albo zdjęty znacznik nowy_klient w karcie) etykieta wstrzymania znika i sprawy wracają do normalnego obiegu.
Kroki wyslij.py (cron co kilka minut) wołą zwolnij_potwierdzone().
"""

import re

import dla_czlowieka as dc
import slack_widok as sw


def _rola(osoba):
    """Rola bez adresów e-mail (w karcie z rozmowy rola bywa adresem) i bez dopisku o wniosku."""
    rola = (osoba.get("rola") or "").strip()
    if "@" in rola:
        return "adres e-mail w karcie" if osoba.get("email") or osoba.get("potwierdzony") is not None else ""
    return re.sub(r"^wniosek z rozmowy, do potwierdzenia$", "z rozmowy", rola)


def lista_do_potwierdzenia(karta):
    """Krótka lista: kontakty i decydenci do potwierdzenia (bez adresów e-mail)."""
    def wiersz(o, status=""):
        rola = _rola(o)
        return f"- {o.get('imie', '?')}" + (f", {rola}" if rola else "") + status
    kontakty = [wiersz(k, " (potwierdzony)" if k.get("potwierdzony") else " (do potwierdzenia)") for k in karta.get("kontakty", [])]
    decydenci = [wiersz(d) for d in (karta.get("decydenci_wniosek") or []) + (karta.get("decydenci") or [])]
    return kontakty, decydenci


def opis_potwierdzenia(klient, karta, Z):
    """Opis zgłoszenia w układzie dla człowieka: blok „Co masz zrobić” + krótka lista."""
    kontakty, decydenci = lista_do_potwierdzenia(karta)
    nazwa = karta.get("nazwa") or klient
    blok = dc.zloz_blok(f"Sprawdź kontakty i decydentów nowego klienta {nazwa} i potwierdź kartę. Do tego czasu jego pozostałe sprawy są wstrzymane.",
                        "karta", None,
                        f"popraw kontakty i decydentów w ops/klienci/{klient}/karta.json | zamknij to zgłoszenie (Done), gdy karta jest dobra")
    kontekst = ("## Kontakty (do potwierdzenia)\n\n" + ("\n".join(kontakty) or "_brak_")
                + "\n\n## Decydenci (do potwierdzenia)\n\n" + ("\n".join(decydenci) or "_brak_")
                + "\n\n## Co się stanie po potwierdzeniu\n\nSprawy klienta z etykietą „Wstrzymane do potwierdzenia karty” wracają do normalnego obiegu "
                  "(agent, czeka na klienta, produkt, ryzyko). Do czasu potwierdzenia nic z tej karty nie trafia do wysyłki maili.")
    return dc.zloz_opis(blok, kontekst)


def tytul_potwierdzenia(klient, karta, Z):
    return f"[{klient}] " + Z["nowy_klient"]["tytul_zgloszenia"].format(nazwa=karta.get("nazwa") or klient)


def zapewnij_zgloszenie(s, klient, karta):
    """Tworzy (raz) zgłoszenie „Potwierdź kartę klienta …” dla niepotwierdzonej karty. s.linear.utworz; stan w karcie (potwierdzenie_karty).
    Zwraca zgłoszenie albo None, gdy karta jest potwierdzona albo zgłoszenie już istnieje."""
    Z, E = s.Z, s.Z["etykiety"]
    if karta.get("nowy_klient") is not True or karta.get("potwierdzenie_karty"):
        return None
    zg = s.linear.utworz(tytul_potwierdzenia(klient, karta, Z), opis_potwierdzenia(klient, karta, Z), [E["weryfikacja"], E["karta"]], "Todo",
                         Z["nowy_klient"].get("priorytet"))
    karta["potwierdzenie_karty"] = {"identifier": zg["identifier"], "linear_id": zg["id"], "url": zg["url"]}
    s.zapisz_karte(klient, karta)
    return zg


def odswiez_opis(s, klient, karta):
    """Opis istniejącego zgłoszenia „Potwierdź kartę klienta …” zgodny z bieżącą kartą. True, gdy zmieniono."""
    wpis = karta.get("potwierdzenie_karty")
    if karta.get("nowy_klient") is not True or not wpis:
        return False
    zg = {"id": wpis["linear_id"], "identifier": wpis["identifier"], "title": tytul_potwierdzenia(klient, karta, s.Z), "description": ""}
    s.linear.ustaw_uklad(zg, zg["title"], opis_potwierdzenia(klient, karta, s.Z))
    return True


def potwierdz_karte(karta):
    """Karta po potwierdzeniu: znacznik nowy_klient znika, decydenci z wniosku stają się decydentami, kontakty z adresem są potwierdzone."""
    karta.pop("nowy_klient", None)
    karta.pop("potwierdzenie_karty", None)
    wniosek = karta.pop("decydenci_wniosek", None) or []
    if wniosek and not karta.get("decydenci"):
        karta["decydenci"] = [{"imie": d["imie"], "rola": re.sub(r"^wniosek z rozmowy, do potwierdzenia$", "decydent", d.get("rola", "")) or "decydent"} for d in wniosek]
    for k in karta.get("kontakty", []):
        if k.get("email") and not k.get("potwierdzony"):
            k["potwierdzony"] = True
            k["status"] = "potwierdzony"
    return karta


def zwolnij_potwierdzone(s, log=None):
    """Potwierdzenie karty i zwolnienie spraw NIE zależy od pory ani dnia: okno wysyłki 8–18 (wyslij.okno_wysylki) dotyczy wyłącznie maili do klienta,
    a ten kod nie czyta czasu w ogóle (testy: o każdej porze, także po 18:00 i w niedzielę). log(tekst): diagnostyka do logu przebiegu.
    Dla każdego zgłoszenia „Karta do potwierdzenia”: gdy jest Done albo karta nie ma już znacznika nowy_klient, karta jest potwierdzona,
    sprawy klienta tracą etykietę wstrzymania, Slack dostaje jedną linijkę. Zwraca [{"klient", "zwolnione": [...]}]."""
    E = s.Z["etykiety"]
    wynik = []
    for zg in s.linear.z_etykieta(E["karta"]):
        m = re.match(r"^\[([^\]]+)\]", zg.get("title") or "")
        if not m:
            continue
        klient = m.group(1)
        karta = s.wczytaj_karte(klient)
        zamkniete = zg.get("state") in ("Done",)
        if log:
            log(f"{zg['identifier']} ({klient}): stan {zg.get('state')}, karta nowy_klient={karta.get('nowy_klient')}")
        if not (zamkniete or karta.get("nowy_klient") is not True):
            if log:
                log(f"  czeka: zamknij {zg['identifier']} jako Done (albo zdejmij nowy_klient w ops/klienci/{klient}/karta.json)")
            continue
        if karta.get("nowy_klient") is True:
            potwierdz_karte(karta)
            s.zapisz_karte(klient, karta)
        zwolnione = []
        for t in s.linear.z_etykieta(E["wstrzymane"]):
            if t.get("state") in ("Done", "Canceled", "Cancelled") or not (t.get("title") or "").startswith(f"[{klient}]"):
                continue
            s.linear.usun_etykiete(t, E["wstrzymane"])
            zwolnione.append(t["identifier"])
        if not zamkniete and zg.get("state") not in ("Canceled", "Cancelled"):
            s.linear.ustaw_stan(zg, "Done")
        s.linear.usun_etykiete(zg, E["karta"])
        linia = [f":white_check_mark: Karta klienta {karta.get('nazwa') or klient} potwierdzona: {len(zwolnione)} "
                 f"{sw.forma(len(zwolnione), 'sprawa wraca', 'sprawy wracają', 'spraw wraca')} do normalnego obiegu"]
        if zwolnione or not zamkniete:
            s.slack.wyslij(sw.tekst_zapasowy(linia), sw.bloki(linia))
        wynik.append({"klient": klient, "zwolnione": zwolnione})
    return wynik


def main():
    """Samodzielny krok workflow: potwierdzenie kart i zwolnienie wstrzymanych spraw, o każdej porze, niezależnie od wysyłki maili."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    import stan_linear
    import wyslij
    s = wyslij.zbuduj_srodowisko()
    wyniki = zwolnij_potwierdzone(s, log=print)
    for w in wyniki:
        print(f"{w['klient']}: karta potwierdzona, wróciło {len(w['zwolnione'])} spraw: {', '.join(w['zwolnione']) or '-'}")
    if not wyniki:
        print("Brak kart do potwierdzenia, które zostały potwierdzone.")
    stan_linear.po_przebiegu()


if __name__ == "__main__":
    main()
