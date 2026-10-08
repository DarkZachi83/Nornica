# SPDX-License-Identifier: GPL-3.0-or-later
"""Odczyt i zapis ustawień programu (tabela `ustawienia`)."""
from __future__ import annotations

import sqlite3


def pobierz(polaczenie: sqlite3.Connection, klucz: str, domyslna: str | None = None) -> str | None:
    wiersz = polaczenie.execute(
        "SELECT wartosc FROM ustawienia WHERE klucz = ?", (klucz,)).fetchone()
    return wiersz["wartosc"] if wiersz and wiersz["wartosc"] is not None else domyslna


def zapisz(polaczenie: sqlite3.Connection, klucz: str, wartosc: str | None) -> None:
    polaczenie.execute(
        "INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?) "
        "ON CONFLICT(klucz) DO UPDATE SET wartosc = excluded.wartosc",
        (klucz, wartosc))
