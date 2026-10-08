# SPDX-License-Identifier: GPL-3.0-or-later
"""Złącza modeli i egzemplarzy.

Złącza egzemplarza = złącza modelu + nadpisania egzemplarza (ilość 0 oznacza
złącze usunięte względem modelu). Klucz złącza: (zlacze_typ_id, rola).
"""
from __future__ import annotations

import sqlite3

Zlacza = dict[tuple[int, str], int]


def typy(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT id, kod, rodzaj, nazwy, kolejnosc FROM zlacze_typ "
                      "ORDER BY kod IS NULL, kolejnosc, id").fetchall()


def modelu(db: sqlite3.Connection, model_id: int | None) -> Zlacza:
    if not model_id:
        return {}
    return {(w[0], w[1]): w[2] for w in db.execute(
        "SELECT zlacze_typ_id, rola, ilosc FROM model_zlacze WHERE model_id = ?", (model_id,))}


def nadpisania_egzemplarza(db: sqlite3.Connection, egz_id: int | None) -> Zlacza:
    if not egz_id:
        return {}
    return {(w[0], w[1]): w[2] for w in db.execute(
        "SELECT zlacze_typ_id, rola, ilosc FROM egzemplarz_zlacze WHERE egzemplarz_id = ?", (egz_id,))}


def efektywne(z_modelu: Zlacza, nadpisania: Zlacza) -> Zlacza:
    return {**z_modelu, **nadpisania}


def roznice(efektywne_: Zlacza, z_modelu: Zlacza) -> Zlacza:
    """Nadpisania potrzebne, żeby z modelu otrzymać stan efektywny.
    Złącze modelu nieobecne w stanie efektywnym -> nadpisanie z ilością 0."""
    wynik = {}
    for klucz in set(efektywne_) | set(z_modelu):
        ilosc = efektywne_.get(klucz, 0)
        if ilosc != z_modelu.get(klucz, 0):
            wynik[klucz] = ilosc
    return wynik


def zapisz_modelu(db: sqlite3.Connection, model_id: int, zlacza: Zlacza) -> None:
    db.execute("DELETE FROM model_zlacze WHERE model_id = ?", (model_id,))
    db.executemany("INSERT INTO model_zlacze (model_id, zlacze_typ_id, rola, ilosc) VALUES (?, ?, ?, ?)",
                   [(model_id, typ, rola, ilosc) for (typ, rola), ilosc in zlacza.items() if ilosc > 0])


def zapisz_nadpisania(db: sqlite3.Connection, egz_id: int, nadpisania: Zlacza) -> None:
    db.execute("DELETE FROM egzemplarz_zlacze WHERE egzemplarz_id = ?", (egz_id,))
    db.executemany("INSERT INTO egzemplarz_zlacze (egzemplarz_id, zlacze_typ_id, rola, ilosc) "
                   "VALUES (?, ?, ?, ?)",
                   [(egz_id, typ, rola, ilosc) for (typ, rola), ilosc in nadpisania.items()])
