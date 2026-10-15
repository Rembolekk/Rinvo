#!/usr/bin/env python3
"""odmaskuj.py – przywraca osoby ze strony klienta i naszej, które maskowanie omyłkowo zamieniło na „[nazwisko]”.

Maskujemy tylko osoby TRZECIE (klienci końcowi, goście, leady). Dyrektor „pan Robert” z nagłówka rozmowy jest uczestnikiem rozmowy
(wspomniany z rolą), więc nie może być „[nazwisko]”. Skrypt NIE woła modelu:
  * cytaty wracają dosłownie z transkrypcji (dopasowanie po otoczeniu „[nazwisko]” w surowym tekście),
  * pozostałe napisy dostają formę wynikającą z poprzedzającego słowa (panem → Robertem, panu → Robertowi, do → Roberta, pan → Robert…),
  * potem wynik jest maskowany od nowa już poprawną regułą (higiena.maskuj_wynik), a raport.html renderowany ponownie.
Użycie: python3 odmaskuj.py <klient> <transkrypcja.md> [--zastosuj] [--bez-linear]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import higiena

ZNACZNIK = "[nazwisko]"
# forma imienia/nazwiska wg słowa poprzedzającego (wzorce odmiany polskiej: dopełniacz, celownik, narzędnik, miejscownik)
PRZYPADKI = {
    "pan": "mian", "pani": "mian", "państwo": "mian", "panem": "narz", "panią": "narz", "pana": "dop", "panu": "cel",
    "do": "dop", "od": "dop", "dla": "dop", "u": "dop", "bez": "dop", "przez": "dop", "wobec": "dop", "obok": "dop", "dzięki": "cel",
    "z": "narz", "za": "narz", "przed": "narz", "między": "narz", "o": "miej", "po": "miej", "przy": "miej", "na": "miej", "w": "miej",
    "wyślę": "cel", "wyślij": "cel", "napiszę": "cel", "napisz": "cel", "powiedz": "cel", "przekaż": "cel", "przekażę": "cel", "mu": "cel",
}


def odmien(imie, przypadek):
    """Prosta odmiana męskiego imienia/nazwiska na -t/-r/-k/-n… (Robert → Roberta, Robertowi, Robertem, Robercie)."""
    if przypadek == "mian":
        return imie
    if przypadek == "dop":
        return imie + "a"
    if przypadek == "cel":
        return imie + "owi"
    if przypadek == "narz":
        return imie + "em"
    if przypadek == "miej":
        return re.sub(r"rt$", "rcie", imie) if imie.endswith("rt") else imie + "ie"
    return imie


def _norm(t):
    return re.sub(r"\s+", " ", t.replace("**", ""))


def rodzina_do_przywrocenia(tekst_zrodla, znane=()):
    """Rdzeń znanej osoby, której formy stoją po „pan/pani/…” w transkrypcji i która NIE jest osobą trzecią. None, gdy nie ma
    jednoznacznego rdzenia (wtedy nic nie przywracamy). Osoby trzecie zostają zamaskowane."""
    znane_t = higiena._tokeny_znane(list(znane) + higiena.osoby_z_naglowka(tekst_zrodla))
    rdzenie = set()
    for m in higiena._PAN.finditer(tekst_zrodla):
        for tok in re.split(r"[ -]", m.group(1)):
            if higiena.jest_znany(tok, znane_t):
                rdzenie.add(min((k for k in znane_t if k not in higiena._TYTULY and len(k) >= 3 and tok.casefold().startswith(k[:max(3, len(k) - 1)])),
                                key=len, default=tok.casefold()))
    return rdzenie.pop().capitalize() if len(rdzenie) == 1 else None


def odmaskuj_tekst(tekst, surowy, rdzen):
    """(nowy tekst, [(otoczenie, forma, metoda)]). Najpierw dosłownie z surowej transkrypcji (po otoczeniu), potem wg poprzedzającego słowa."""
    surowy_n = _norm(surowy)
    zmiany = []

    def zamien(m):
        s, e = m.span()
        lewo = tekst[max(0, s - 30):s]
        prawo = tekst[e:e + 30]
        lewo = lewo.rsplit("]", 1)[-1]
        prawo = prawo.split("[", 1)[0]
        wz = re.escape(_norm(lewo)) + "(" + re.escape(rdzen[:-1]) + r"\w*)" + re.escape(_norm(prawo))
        w = re.search(wz, surowy_n)
        if w:
            zmiany.append(((lewo + ZNACZNIK + prawo).strip(), w.group(1), "z transkrypcji"))
            return w.group(1)
        slowa = re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", lewo.casefold())
        przyp = PRZYPADKI.get(slowa[-1], "mian") if slowa else "mian"
        forma = odmien(rdzen, przyp)
        zmiany.append(((lewo + ZNACZNIK + prawo).strip(), forma, f"wg słowa „{slowa[-1] if slowa else ''}”"))
        return forma

    return re.sub(re.escape(ZNACZNIK), zamien, tekst), zmiany


def odmaskuj_obiekt(o, surowy, rdzen, zmiany, klucz=None):
    if isinstance(o, str):
        if klucz == "zrodlo" or ZNACZNIK not in o:
            return o
        t, z = odmaskuj_tekst(o, surowy, rdzen)
        zmiany.extend(z)
        return t
    if isinstance(o, list):
        return [odmaskuj_obiekt(x, surowy, rdzen, zmiany, klucz) for x in o]
    if isinstance(o, dict):
        return {k: (v if k == "kontrola" else odmaskuj_obiekt(v, surowy, rdzen, zmiany, k)) for k, v in o.items()}
    return o


def przelicz_wynik(wynik_path, zrodlo, klient, root="."):
    """Odmaskowuje wynik.json i maskuje od nowa poprawną regułą. Zwraca (zmiany, rdzeń)."""
    surowy = Path(zrodlo).read_text(encoding="utf-8")
    karta_p = Path(root) / "ops/klienci" / klient / "karta.json"
    karta = json.loads(karta_p.read_text(encoding="utf-8")) if karta_p.exists() else {}
    znane = [k.get("imie", "") for k in karta.get("kontakty", [])] + [d.get("imie", "") for d in karta.get("decydenci", [])]
    rdzen = rodzina_do_przywrocenia(surowy, znane)
    wynik = json.loads(Path(wynik_path).read_text(encoding="utf-8"))
    zmiany = []
    if rdzen:
        wynik = odmaskuj_obiekt(wynik, surowy, rdzen, zmiany)
    dozwolone = [k.get("email", "") for k in karta.get("kontakty", []) if k.get("email")]
    higiena.maskuj_wynik(wynik, surowy, dozwolone, znane)
    Path(wynik_path).write_text(json.dumps(wynik, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return zmiany, rdzen


def przelicz_karte(klient, surowy, rdzen, root="."):
    import linear_sync
    plik = Path(root) / "ops/klienci" / klient / "karta.json"
    karta = json.loads(plik.read_text(encoding="utf-8"))
    zmiany = []
    karta = odmaskuj_obiekt(karta, surowy, rdzen, zmiany) if rdzen else karta
    plik.write_text(json.dumps(karta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    linear_sync.write_karta_md(klient, karta)
    return zmiany


def przelicz_linear(api_key, gql, klient, surowy, rdzen, zastosuj):
    """Tytuły, opisy i komentarze zgłoszeń klienta z „[nazwisko]”. Zwraca [(identyfikator, co, stary, nowy)]."""
    import linear_sync
    q = ('query { issues(first: 100, filter: { team: { key: { eq: "%s" } }, title: { startsWith: "[%s]" } }) { nodes { id identifier title description '
         'comments(first: 50) { nodes { id body } } } } }' % (linear_sync.TEAM_KEY, klient))
    wynik = []
    for n in gql(api_key, q)["issues"]["nodes"]:
        wejscie = {}
        for pole in ("title", "description"):
            if n.get(pole) and ZNACZNIK in n[pole]:
                nowy, _ = odmaskuj_tekst(n[pole], surowy, rdzen)
                wejscie[pole] = nowy
                wynik.append((n["identifier"], pole, n[pole], nowy))
        if wejscie and zastosuj:
            gql(api_key, linear_sync.M_UPDATE_ISSUE, {"id": n["id"], "input": wejscie})
        for k in n["comments"]["nodes"]:
            if ZNACZNIK in k["body"]:
                nowy, _ = odmaskuj_tekst(k["body"], surowy, rdzen)
                wynik.append((n["identifier"], "komentarz", k["body"], nowy))
                if zastosuj:
                    gql(api_key, "mutation($id: String!, $input: CommentUpdateInput!) { commentUpdate(id: $id, input: $input) { success } }",
                        {"id": k["id"], "input": {"body": nowy}})
    return wynik


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="Przywraca osoby omyłkowo zamaskowane jako [nazwisko] (bez modelu).")
    ap.add_argument("klient")
    ap.add_argument("zrodlo", help="ścieżka transkrypcji")
    ap.add_argument("--zastosuj", action="store_true", help="zapisz zmiany (bez tego tylko raport)")
    ap.add_argument("--bez-linear", action="store_true")
    args = ap.parse_args()
    zrodlo = Path(args.zrodlo)
    surowy = zrodlo.read_text(encoding="utf-8")
    wynik_p = Path("wyniki") / args.klient / zrodlo.stem / "wynik.json"
    rdzen = rodzina_do_przywrocenia(surowy)
    print(f"Osoba do przywrócenia: {rdzen or 'brak jednoznacznej (nic nie zmieniam)'}")
    if not rdzen:
        return
    if not args.zastosuj:
        _, zm = odmaskuj_tekst(wynik_p.read_text(encoding="utf-8"), surowy, rdzen)
        for kontekst, forma, metoda in zm:
            print(f"  …{kontekst}… → {forma} ({metoda})")
        print(f"Do przywrócenia w wynik.json: {len(zm)} (raport; nic nie zmieniono)")
        return
    zmiany, _ = przelicz_wynik(wynik_p, zrodlo, args.klient)
    print(f"wynik.json: przywrócono {len(zmiany)}")
    subprocess.run([sys.executable, "-I", "render.py", str(wynik_p), "--transkrypcja", str(zrodlo)], check=False, capture_output=True)
    print(f"karta: przywrócono {len(przelicz_karte(args.klient, surowy, rdzen))}")
    if not args.bez_linear:
        import linear_sync
        from przetworz import load_env
        load_env()
        zm = przelicz_linear(linear_sync.load_api_key(), linear_sync.gql, args.klient, surowy, rdzen, True)
        print(f"Linear: poprawiono {len(zm)} (tytuły, opisy, komentarze)")
        import stan_linear
        stan_linear.po_przebiegu()


if __name__ == "__main__":
    main()
