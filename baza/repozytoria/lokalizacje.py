# SPDX-License-Identifier: GPL-3.0-or-later
"""Lokalizacje (drzewo: pokój > regał > półka > pudełko)."""
from __future__ import annotations

import sqlite3

POLA = ("rodzic_id", "nazwa", "typ", "kod_etykiety", "uwagi")


def wszystkie(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM lokalizacja ORDER BY nazwa COLLATE NORNICA").fetchall()


def pobierz(db: sqlite3.Connection, lok_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM lokalizacja WHERE id = ?", (lok_id,)).fetchone()


def sciezki(db: sqlite3.Connection) -> dict[int, str]:
    return {w[0]: w[1] for w in db.execute("SELECT lokalizacja_id, sciezka FROM v_lokalizacja_sciezka")}


def potomkowie(db: sqlite3.Connection, lok_id: int) -> set[int]:
    return {w[0] for w in db.execute(
        "WITH RECURSIVE d(id, g) AS (SELECT id, 0 FROM lokalizacja WHERE rodzic_id = ? "
        "UNION ALL SELECT l.id, d.g + 1 FROM lokalizacja l JOIN d ON l.rodzic_id = d.id WHERE d.g < 32) "
        "SELECT id FROM d", (lok_id,))}


def wstaw(db: sqlite3.Connection, dane: dict) -> int:
    kolumny = [k for k in POLA if k in dane]
    return db.execute(f"INSERT INTO lokalizacja ({', '.join(kolumny)}) "
                      f"VALUES ({', '.join('?' * len(kolumny))})",
                      [dane[k] for k in kolumny]).lastrowid


def aktualizuj(db: sqlite3.Connection, lok_id: int, dane: dict) -> None:
    kolumny = [k for k in POLA if k in dane]
    db.execute(f"UPDATE lokalizacja SET {', '.join(k + ' = ?' for k in kolumny)} WHERE id = ?",
               [dane[k] for k in kolumny] + [lok_id])
