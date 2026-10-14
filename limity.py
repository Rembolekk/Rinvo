#!/usr/bin/env python3
"""limity.py – limity i kredyty modelu: wykrywanie błędu limitu, kolejka „oczekuje na limit”, dzienny bezpiecznik kosztów.

  * LimitModelu – claude zwrócił błąd limitu albo kredytów. Zadanie idzie do kolejki (ops/.kolejka_limit.json), NIE liczy się
    jako nieudana próba, Slack dostaje jedną informację na epizod, ponowienie następuje przy następnym przebiegu.
  * Budzet – dzienny limit wywołań modelu dla całego systemu i osobno dla agenta (ops/zasady.json → budzet_modelu).
    Po przekroczeniu: BudzetWyczerpany, alert raz dziennie, dalej następnego dnia (ops/.zuzycie_modelu.json).
Użycie CLI: python3 limity.py --dopisz-kolejke PLIK   (dopisuje transkrypcje czekające na limit do listy plików do przetworzenia)
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

PLIK_KOLEJKI = Path("ops/.kolejka_limit.json")
PLIK_ZUZYCIA = Path("ops/.zuzycie_modelu.json")


class LimitModelu(RuntimeError):
    """Błąd limitu albo kredytów zwrócony przez claude."""


class BudzetWyczerpany(RuntimeError):
    """Dzienny bezpiecznik kosztów: zakres „razem” albo „agent”."""

    def __init__(self, zakres):
        super().__init__(f"dzienny limit wywołań modelu ({zakres}) wyczerpany")
        self.zakres = zakres


def czy_limit(tekst, Z):
    """Czy tekst (wyjście claude) wygląda na błąd limitu, kredytów albo przeciążenia."""
    return any(re.search(w, str(tekst or ""), re.IGNORECASE) for w in Z["limity_modelu"]["wzorce"])


def _json(p, domyslnie):
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else domyslnie


def _zapisz(p, dane):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dane, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


class Kolejka:
    """Zadania czekające na limit modelu. powiadom_raz() zwraca True tylko raz na epizod (do pierwszego udanego wywołania)."""

    def __init__(self, plik=None):
        self.plik = Path(plik) if plik else PLIK_KOLEJKI

    def _stan(self):
        return _json(self.plik, {"oczekuje": [], "powiadomiono": False})

    def dodaj(self, klucz):
        s = self._stan()
        if klucz not in s["oczekuje"]:
            s["oczekuje"].append(klucz)
            _zapisz(self.plik, s)

    def usun(self, klucz):
        s = self._stan()
        if klucz in s["oczekuje"]:
            s["oczekuje"].remove(klucz)
            _zapisz(self.plik, s)

    def lista(self):
        return list(self._stan()["oczekuje"])

    def powiadom_raz(self):
        s = self._stan()
        if s["powiadomiono"]:
            return False
        s["powiadomiono"] = True
        _zapisz(self.plik, s)
        return True

    def sukces(self):
        """Udane wywołanie modelu kończy epizod: następny limit znów da jedną informację."""
        s = self._stan()
        if s["powiadomiono"]:
            s["powiadomiono"] = False
            _zapisz(self.plik, s)


class Budzet:
    def __init__(self, Z, plik=None, dzis=None):
        self.Z, self.plik, self.dzis = Z["budzet_modelu"], Path(plik) if plik else PLIK_ZUZYCIA, dzis

    def _stan(self):
        dzis = (self.dzis or date.today()).isoformat()
        s = _json(self.plik, {})
        if s.get("data") != dzis:
            s = {"data": dzis, "razem": 0, "agent": 0, "alerty": []}
        return s

    def zuzycie(self):
        return self._stan()

    def zuzyj(self, rodzaj="inne"):
        """Liczy jedno wywołanie modelu. rodzaj: „agent” albo „inne”. Przy przekroczeniu rzuca BudzetWyczerpany (wywołanie NIE jest liczone)."""
        s = self._stan()
        if s["razem"] >= self.Z["dziennie_razem"]:
            raise BudzetWyczerpany("razem")
        if rodzaj == "agent" and s["agent"] >= self.Z["dziennie_agent"]:
            raise BudzetWyczerpany("agent")
        s["razem"] += 1
        if rodzaj == "agent":
            s["agent"] += 1
        _zapisz(self.plik, s)

    def alert_potrzebny(self, zakres):
        """True tylko raz dziennie na zakres (do alertu na Slacku)."""
        s = self._stan()
        if zakres in s["alerty"]:
            return False
        s["alerty"].append(zakres)
        _zapisz(self.plik, s)
        return True


def tekst_alertu_budzetu(zakres, uzycie, Z):
    lim = Z["budzet_modelu"]
    return (f":money_with_wings: Dzienny limit wywołań modelu ({'dla agenta' if zakres == 'agent' else 'dla całego systemu'}) wyczerpany: "
            f"razem {uzycie['razem']}/{lim['dziennie_razem']}, agent {uzycie['agent']}/{lim['dziennie_agent']}. Zatrzymano do jutra, wtedy ruszy dalej.")


def tekst_oczekiwania_na_limit(klucze):
    return (":hourglass_flowing_sand: Limit albo kredyty modelu wyczerpane. Zadania czekają w kolejce „oczekuje na limit” "
            f"({', '.join(klucze[:5])}{'…' if len(klucze) > 5 else ''}) i nie liczą się jako nieudane próby. Ponowimy przy następnym przebiegu.")


def main():
    ap = argparse.ArgumentParser(description="Kolejka zadań czekających na limit modelu.")
    ap.add_argument("--dopisz-kolejke", metavar="PLIK", help="dopisz do pliku z listą ścieżek zadania czekające na limit (istniejące pliki)")
    args = ap.parse_args()
    if args.dopisz_kolejke:
        p = Path(args.dopisz_kolejke)
        obecne = {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()} if p.exists() else set()
        dodane = [k for k in Kolejka().lista() if Path(k).exists() and k not in obecne and k.startswith("ops/transkrypcje/")]
        if dodane:
            with p.open("a", encoding="utf-8") as f:
                f.write("".join(f"{k}\n" for k in dodane))
        print(f"Kolejka limitu: dopisano {len(dodane)}")


if __name__ == "__main__":
    main()
