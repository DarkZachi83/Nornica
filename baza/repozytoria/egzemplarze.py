# SPDX-License-Identifier: GPL-3.0-or-later
"""Egzemplarze: odczyt z danymi modelu, producenta, kategorii i statusu."""
from __future__ import annotations

import sqlite3

POLA = ("kod_inwentarzowy", "model_id", "kategoria_id", "nazwa_wlasna", "numer_seryjny",
        "rewizja", "status_id", "stan_wizualny", "rodzic_id", "pozycja_montazu",
        "lokalizacja_id", "ilosc", "atrybuty", "data_nabycia", "zrodlo_nabycia",
        "cena_minor", "waluta_kod", "uwagi")

_SELECT = """
SELECT e.*,
       m.nazwa AS model_nazwa, m.numer_czesci, m.atrybuty AS model_atrybuty,
       p.nazwa AS producent,
       coalesce(m.kategoria_id, e.kategoria_id) AS kat_id,
       k.nazwy AS kategoria_nazwy,
       s.kod AS status_kod, s.nazwy AS status_nazwy
FROM egzemplarz e
LEFT JOIN model m     ON m.id = e.model_id
LEFT JOIN producent p ON p.id = m.producent_id
LEFT JOIN kategoria k ON k.id = coalesce(m.kategoria_id, e.kategoria_id)
JOIN status s         ON s.id = e.status_id
"""


def lista(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(_SELECT).fetchall()


def pobierz(db: sqlite3.Connection, egz_id: int) -> sqlite3.Row | None:
    return db.execute(_SELECT + " WHERE e.id = ?", (egz_id,)).fetchone()


def nazwa_wyswietlana(wiersz) -> str:
    """Nazwa własna, a bez niej producent i model."""
    if wiersz["nazwa_wlasna"]:
        return wiersz["nazwa_wlasna"]
    return " ".join(c for c in (wiersz["producent"], wiersz["model_nazwa"]) if c) or "?"


def potomkowie(db: sqlite3.Connection, egz_id: int) -> set[int]:
    """Wszystko zamontowane w egzemplarzu, na dowolnej głębokości."""
    return {w[0] for w in db.execute(
        "WITH RECURSIVE d(id, g) AS (SELECT id, 0 FROM egzemplarz WHERE rodzic_id = ? "
        "UNION ALL SELECT e.id, d.g + 1 FROM egzemplarz e JOIN d ON e.rodzic_id = d.id WHERE d.g < 64) "
        "SELECT id FROM d", (egz_id,))}


def efektywna_lokalizacja(db: sqlite3.Connection, egz_id: int) -> int | None:
    wiersz = db.execute("SELECT lokalizacja_id FROM v_egzemplarz_lokalizacja "
                        "WHERE egzemplarz_id = ?", (egz_id,)).fetchone()
    return wiersz[0] if wiersz else None


def wstaw(db: sqlite3.Connection, dane: dict) -> int:
    kolumny = [k for k in POLA if k in dane]
    return db.execute(f"INSERT INTO egzemplarz ({', '.join(kolumny)}) "
                      f"VALUES ({', '.join('?' * len(kolumny))})",
                      [dane[k] for k in kolumny]).lastrowid


def aktualizuj(db: sqlite3.Connection, egz_id: int, dane: dict) -> None:
    kolumny = [k for k in POLA if k in dane]
    db.execute(f"UPDATE egzemplarz SET {', '.join(k + ' = ?' for k in kolumny)} WHERE id = ?",
               [dane[k] for k in kolumny] + [egz_id])
