#!/usr/bin/env python3
"""utwardz.py – kroki utwardzające przetwarzanie, wołane przez przetworz.py (z plikami, ale bez modelu i bez sieci).

  przed_analiza(...)  – ponowna transkrypcja tej samej rozmowy: bez analizy i Slack z pytaniem (chyba że --wymus),
  po_analizie(...)    – po wynik.json od modelu: karta nowego klienta, znaczniki (higiena.adnotuj_wynik), maskowanie danych
                        osobowych, rozmowa wewnętrzna; zwraca linie dla Slacka.
"""

import json
from pathlib import Path

import higiena
import zasady


def wczytaj_karty(root="."):
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(root, "ops/klienci").glob("*/karta.json"))}


def przed_analiza(tekst, hash_tekstu, rejestr, wymus=False):
    """{"akcja": "duplikat"|"ok", "odcisk": str|None, "wpis": wpis rejestru tej samej rozmowy}."""
    odcisk = higiena.odcisk_rozmowy(tekst)
    pelny = {}
    for h, w in rejestr.items():                       # starsze wpisy rejestru bez odcisku: liczymy go z zapisanego pliku
        if isinstance(w, dict) and not w.get("odcisk") and w.get("transkrypcja") and Path(w["transkrypcja"]).exists():
            w = {**w, "odcisk": higiena.odcisk_rozmowy(Path(w["transkrypcja"]).read_text(encoding="utf-8"))}
        pelny[h] = w
    wpis = higiena.powtorna_transkrypcja(odcisk, hash_tekstu, pelny)
    if wpis and not wymus:
        return {"akcja": "duplikat", "odcisk": odcisk, "wpis": wpis}
    return {"akcja": "ok", "odcisk": odcisk, "wpis": wpis}


def pytanie_o_duplikat(transkrypcja, wpis):
    return (f":question: *{Path(transkrypcja).parent.name}*: `{Path(transkrypcja).name}` wygląda na tę samą rozmowę co "
            f"`{Path(str(wpis.get('transkrypcja', '?'))).name}` (ta sama data, godzina i uczestnicy), ale tekst jest inny "
            f"(ponowna transkrypcja). Nie analizuję jej drugi raz. Przetworzyć mimo to? Uruchom z `--wymus`.")


def po_analizie(wynik_path, zrodlo, klient, root=".", meta_maila=None, zapisz_karte=None, Z=None):
    """Adnotuje i maskuje wynik.json (zapisuje go z powrotem). Zwraca
    {"kontrola": dict, "slack": [linie], "nowy_klient": bool, "wewnetrzna": bool, "maskowanie": int}."""
    Z = Z or zasady.wczytaj_zasady()
    K = Z["kontrola"]
    wynik = json.loads(Path(wynik_path).read_text(encoding="utf-8"))
    tekst = Path(zrodlo).read_text(encoding="utf-8")
    karty = wczytaj_karty(root)
    nowy = klient not in karty
    slack = []
    if nowy:
        karta = higiena.karta_nowego_klienta(klient, tekst)
        karty[klient] = karta
        if zapisz_karte:
            zapisz_karte(klient, karta)
        slack.append(f":new: Nowy klient *{klient}*: karta założona z rozmowy (kontakty niepotwierdzone, decydenci jako wniosek). "
                     f"Potwierdź kartę w ops/klienci/{klient}/karta.json. Do potwierdzenia nic nie trafia do agenta ani do wysyłki.")
    else:
        karta = karty[klient]
    h = higiena.parsuj_naglowek_rozmowy(tekst)
    data_zrodla = h["data"] or higiena._data_z_nazwy(zrodlo)
    kontrola = higiena.adnotuj_wynik(wynik, tekst, klient, karta, karty, K, data_zrodla, zrodlo=str(zrodlo),
                                     meta_maila=meta_maila, nowy_klient=nowy)
    dozwolone = [k.get("email", "") for k in karta.get("kontakty", []) if k.get("email")]
    znane = [k.get("imie", "") for k in karta.get("kontakty", [])] + [d.get("imie", "") for d in karta.get("decydenci", [])]
    licznik = higiena.maskuj_wynik(wynik, tekst, dozwolone, znane)
    Path(wynik_path).write_text(json.dumps(wynik, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if kontrola.get("niepelna"):
        slack.append(f":warning: *{klient}*: niepełna transkrypcja ({'; '.join(kontrola['niepelna'])}). Pozycje nie dostają „Dla agenta”.")
    if kontrola.get("wewnetrzna"):
        slack.append(f":speech_balloon: *{klient}*: rozmowa wewnętrzna (nikogo ze strony klienta). Karta klienta bez zmian.")
    if kontrola.get("starsze"):
        slack.append(f":hourglass: *{klient}*: źródło starsze niż stan karty. Aktualizacje spraw i zmiany decyzji pominięte, nowe pozycje dodane z oznaczeniem.")
    if kontrola.get("inny_klient"):
        slack.append(f":twisted_rightwards_arrows: *{klient}*: pozycje innego klienta ({len(kontrola['inny_klient'])}) nie trafiły do tej karty ani do Lineara (Do weryfikacji).")
    if kontrola.get("polecenia"):
        slack.append(f":no_entry_sign: *{klient}*: w treści wykryto polecenia dla systemu ({len(kontrola['polecenia'])}). Zignorowane.")
    for f in kontrola.get("mail", []):
        slack.append(f":lock: *{klient}*: {higiena.FLAGI_OPISY.get(f, f)}. Pozycje: Do weryfikacji.")
    return {"kontrola": kontrola, "slack": slack, "nowy_klient": nowy, "wewnetrzna": bool(kontrola.get("wewnetrzna")),
            "maskowanie": sum(licznik.values())}


def obsluz_potwierdzenie(meta, linear, Z=None):
    """Odpowiedź klienta na NASZ wysłany mail (In-Reply-To z historii wysyłek). Krótkie potwierdzenie („dzięki”, „będę”)
    zamyka powiązane zgłoszenia i nie tworzy nowych. Zwraca {"zamkniete": [...], "juz_zamkniete": [...]} albo None,
    gdy to nie krótkie potwierdzenie (wtedy mail idzie do zwykłej analizy, z przypisaniem do tych zgłoszeń)."""
    Z = Z or zasady.wczytaj_zasady()
    o = meta.get("odpowiedz_na")
    if not o or not higiena.potwierdzenie_krotkie(meta.get("tresc", ""), Z["kontrola"]):
        return None
    zamkniete, juz = [], []
    for ident in o["zgloszenia"]:
        zg = linear.zgloszenie_po_numerze(int(str(ident).split("-")[-1]))
        if zg is None:
            continue
        if zg.get("state") in ("Done", "Canceled", "Cancelled"):
            juz.append(ident)
            continue
        linear.ustaw_stan(zg, "Done")
        linear.komentarz(zg, f"Klient potwierdził mailem („{' '.join(meta['tresc'].split())[:80]}”): zgłoszenie zamknięte.")
        zamkniete.append(ident)
    return {"zamkniete": zamkniete, "juz_zamkniete": juz}
