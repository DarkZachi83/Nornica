# SPDX-License-Identifier: GPL-3.0-or-later
"""Przeniesienie modelu (z jego egzemplarzami) albo egzemplarza bez modelu
do innej kategorii — bez utraty danych.

Zgłoszenie: Atari 2600 wpisane jako „Komputer fabryczny” zamiast „Konsola”.
Zmiana kategorii w formularzu egzemplarza odłączała model (lista modeli
pokazuje tylko te z wybranej kategorii) i parametry znikały.

Kategoria należy do MODELU — egzemplarze z modelem dziedziczą ją po nim,
więc przenosi się model, a egzemplarze idą razem z nim. Bez zmian w bazie:
to zwykła kolumna model.kategoria_id.

Parametry przechodzą według kodów pól. Komputery fabryczne i konsole mają
wspólne pola (procesor, taktowanie, pamięć, oryginalny zasilacz) — te
wartości przechodzą same. Pola, których nowa kategoria nie ma (np. „Norma TV”
— konsole mają zamiast niej „Region”), są usuwane — ale najpierw pokazywane
w podglądzie. Parametry spoza szablonu starej kategorii zostają nietknięte.
"""
from __future__ import annotations

import json
import sqlite3

from baza.polaczenie import transakcja
from baza.repozytoria import slowniki
from i18n.tlumacz import nazwa, t
from uslugi.formatowanie import liczba_na_tekst, pojemnosc_na_tekst
from wyjatki import BladNornicy


def _pola(db: sqlite3.Connection, kategoria_id: int | None) -> dict[str, dict]:
    return {p["kod"]: p for p in slowniki.szablon(db, kategoria_id)}


def _wpisy(db: sqlite3.Connection, model_id: int | None, egz_id: int | None) -> tuple[int, list[tuple[str, int, dict]]]:
    """(obecna kategoria, lista (tabela, id, atrybuty)) — model razem z egzemplarzami."""
    if model_id is not None:
        wiersz = db.execute("SELECT kategoria_id, atrybuty FROM model WHERE id = ?", (model_id,)).fetchone()
        if wiersz is None:
            raise BladNornicy("blad.klucz_obcy")
        wpisy = [("model", model_id, json.loads(wiersz["atrybuty"] or "{}"))]
        for e in db.execute("SELECT id, atrybuty FROM egzemplarz WHERE model_id = ?", (model_id,)):
            wpisy.append(("egzemplarz", e["id"], json.loads(e["atrybuty"] or "{}")))
        return wiersz["kategoria_id"], wpisy
    wiersz = db.execute("SELECT model_id, kategoria_id, atrybuty FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()
    if wiersz is None:
        raise BladNornicy("blad.klucz_obcy")
    if wiersz["model_id"] is not None:
        raise BladNornicy("blad.przenies_model")       # kategoria należy do modelu
    return wiersz["kategoria_id"], [("egzemplarz", egz_id, json.loads(wiersz["atrybuty"] or "{}"))]


def _dopasowane(atrybuty: dict, stare: dict, nowe: dict) -> dict:
    """Bez pól starej kategorii, których nowa nie ma. Pola spoza starego szablonu zostają."""
    return {k: v for k, v in atrybuty.items() if k in nowe or k not in stare}


def _tekst(pole: dict | None, wartosc, jezyk: str | None) -> str:
    if isinstance(wartosc, bool):
        return t("ogolne.tak", jezyk) if wartosc else t("ogolne.nie", jezyk)
    if pole and pole.get("typ") == "pojemnosc" and isinstance(wartosc, (int, float)):
        return pojemnosc_na_tekst(wartosc, jezyk)
    tekst = liczba_na_tekst(wartosc, jezyk)
    return f"{tekst} {pole['jednostka']}" if pole and pole.get("jednostka") else tekst


def podglad(db: sqlite3.Connection, kategoria_id: int, model_id: int | None = None,
            egz_id: int | None = None, jezyk: str | None = None) -> dict:
    """Co się stanie z parametrami: przejdą, wymagają sprawdzenia (wartość spoza
    listy nowego pola wyboru), zostaną usunięte. Plus liczba egzemplarzy."""
    obecna, wpisy = _wpisy(db, model_id, egz_id)
    stare, nowe = _pola(db, obecna), _pola(db, kategoria_id)
    wartosci: dict[str, list] = {}
    for _tabela, _id, atrybuty in wpisy:
        for kod, wartosc in atrybuty.items():
            if kod in stare and wartosc not in wartosci.setdefault(kod, []):
                wartosci[kod].append(wartosc)
    wynik = {"obecna": obecna, "egzemplarzy": sum(1 for w in wpisy if w[0] == "egzemplarz"),
             "zachowane": [], "do_sprawdzenia": [], "usuwane": []}
    for kod in [p for p in stare if p in wartosci]:              # w kolejności starego szablonu
        pole = nowe.get(kod) or stare[kod]
        pozycja = {"etykieta": nazwa(stare[kod]["nazwy"], jezyk),
                   "wartosci": ", ".join(_tekst(pole, w, jezyk) for w in wartosci[kod][:4])
                   + ("…" if len(wartosci[kod]) > 4 else "")}
        if kod not in nowe:
            wynik["usuwane"].append(pozycja)
        elif nowe[kod].get("typ") == "enum" and any(w not in nowe[kod].get("wartosci", []) for w in wartosci[kod]):
            wynik["do_sprawdzenia"].append(pozycja)
        else:
            wynik["zachowane"].append(pozycja)
    return wynik


def _dopasuj(db: sqlite3.Connection, wpisy: list[tuple[str, int, dict]], obecna: int, nowa: int) -> int:
    """Bez transakcji — wołane wewnątrz cudzej (przenies, zapisz_model)."""
    stare, nowe = _pola(db, obecna), _pola(db, nowa)
    zmienione = 0
    for tabela, id_, atrybuty in wpisy:
        dopasowane = _dopasowane(atrybuty, stare, nowe)
        if dopasowane != atrybuty:
            db.execute(f"UPDATE {tabela} SET atrybuty = ? WHERE id = ?",
                       (json.dumps(dopasowane, ensure_ascii=False, sort_keys=True) if dopasowane else None, id_))
            zmienione += 1
    return zmienione


def przenies(db: sqlite3.Connection, kategoria_id: int, model_id: int | None = None,
             egz_id: int | None = None) -> int:
    """Przenosi i porządkuje parametry. Zwraca liczbę wpisów, w których zmieniły się parametry."""
    if not kategoria_id:
        raise BladNornicy("blad.wybierz_kategorie")
    with transakcja(db):
        obecna, wpisy = _wpisy(db, model_id, egz_id)
        if obecna == kategoria_id:
            return 0
        if model_id is not None:
            db.execute("UPDATE model SET kategoria_id = ? WHERE id = ?", (kategoria_id, model_id))
        else:
            db.execute("UPDATE egzemplarz SET kategoria_id = ? WHERE id = ?", (kategoria_id, egz_id))
        return _dopasuj(db, wpisy, obecna, kategoria_id)


def po_zmianie_kategorii_modelu(db: sqlite3.Connection, model_id: int, obecna: int, nowa: int) -> None:
    """Zmiana kategorii w formularzu modelu: parametry modelu przychodzą już z nowego
    szablonu, ale egzemplarze trzeba uporządkować tak samo jak przy przeniesieniu."""
    egzemplarze = [("egzemplarz", e["id"], json.loads(e["atrybuty"] or "{}"))
                   for e in db.execute("SELECT id, atrybuty FROM egzemplarz WHERE model_id = ?", (model_id,))]
    _dopasuj(db, egzemplarze, obecna, nowa)
