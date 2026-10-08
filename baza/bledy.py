# SPDX-License-Identifier: GPL-3.0-or-later
"""Zamiana błędów SQLite na komunikaty w języku użytkownika.

Wyzwalacze zgłaszają RAISE(ABORT, <klucz z przedrostkiem blad.>), a nazwane ograniczenia CHECK
dają komunikat 'CHECK constraint failed: nazwa'. Oba przypadki prowadzą do
klucza tłumaczenia. Reszta dostaje komunikat ogólny ze szczegółami.
"""
from __future__ import annotations

import re
import sqlite3

from i18n.tlumacz import ma_klucz, t

_WZOR_CHECK = re.compile(r"CHECK constraint failed: (\w+)")


def klucz_bledu_bazy(blad: sqlite3.Error) -> tuple[str, dict]:
    """Zwraca (klucz, pola) dla błędu bazy — przydatne także w testach."""
    tekst = str(blad)
    if tekst.startswith("blad.") and ma_klucz(tekst):
        return tekst, {}
    dopasowanie = _WZOR_CHECK.search(tekst)
    if dopasowanie and ma_klucz(f"blad.{dopasowanie.group(1)}"):
        return f"blad.{dopasowanie.group(1)}", {}
    if "UNIQUE constraint failed" in tekst:
        return "blad.duplikat", {}
    if "FOREIGN KEY constraint failed" in tekst:
        return "blad.klucz_obcy", {}
    return "blad.baza_ogolny", {"szczegoly": tekst}


def komunikat_bledu_bazy(blad: sqlite3.Error, jezyk: str | None = None) -> str:
    klucz, pola = klucz_bledu_bazy(blad)
    return t(klucz, jezyk, **pola)
