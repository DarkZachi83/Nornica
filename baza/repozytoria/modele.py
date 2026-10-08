# SPDX-License-Identifier: GPL-3.0-or-later
"""Katalog modeli."""
from __future__ import annotations

import sqlite3

POLA = ("kategoria_id", "producent_id", "nazwa", "numer_czesci", "rok_od", "rok_do",
        "opis", "atrybuty", "zrodlo_url", "zaimportowano")

_SELECT = ("SELECT m.*, p.nazwa AS producent FROM model m "
           "LEFT JOIN producent p ON p.id = m.producent_id")


def pobierz(db: sqlite3.Connection, model_id: int) -> sqlite3.Row | None:
    return db.execute(f"{_SELECT} WHERE m.id = ?", (model_id,)).fetchone()


def w_kategorii(db: sqlite3.Connection, kat_id: int | None) -> list[sqlite3.Row]:
    return db.execute(f"{_SELECT} WHERE m.kategoria_id IS ? "
                      "ORDER BY p.nazwa COLLATE NORNICA, m.nazwa COLLATE NORNICA",
                      (kat_id,)).fetchall()


def etykieta(wiersz) -> str:
    """'Creative Sound Blaster 16 (CT2230)'"""
    tekst = " ".join(c for c in (wiersz["producent"], wiersz["nazwa"]) if c)
    return f"{tekst} ({wiersz['numer_czesci']})" if wiersz["numer_czesci"] else tekst


def wstaw(db: sqlite3.Connection, dane: dict) -> int:
    kolumny = [k for k in POLA if k in dane]
    return db.execute(f"INSERT INTO model ({', '.join(kolumny)}) "
                      f"VALUES ({', '.join('?' * len(kolumny))})",
                      [dane[k] for k in kolumny]).lastrowid


def aktualizuj(db: sqlite3.Connection, model_id: int, dane: dict) -> None:
    kolumny = [k for k in POLA if k in dane]
    db.execute(f"UPDATE model SET {', '.join(k + ' = ?' for k in kolumny)} WHERE id = ?",
               [dane[k] for k in kolumny] + [model_id])


def katalog(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Wszystkie modele z nazwą kategorii i liczbą egzemplarzy."""
    return db.execute(
        "SELECT m.id, m.nazwa, m.numer_czesci, m.kategoria_id, p.nazwa AS producent, "
        "       k.nazwy AS kategoria_nazwy, "
        "       (SELECT COUNT(*) FROM egzemplarz e WHERE e.model_id = m.id) AS egzemplarze "
        "FROM model m LEFT JOIN producent p ON p.id = m.producent_id "
        "JOIN kategoria k ON k.id = m.kategoria_id").fetchall()
