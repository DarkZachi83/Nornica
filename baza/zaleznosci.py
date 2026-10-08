# SPDX-License-Identifier: GPL-3.0-or-later
"""Liczenie zależności przed usunięciem rekordu.

SQLite przy naruszeniu klucza obcego zgłasza tylko ogólne
'FOREIGN KEY constraint failed', bez wskazania tabeli. Dlatego przed
usunięciem program sam sprawdza, co wskazuje na rekord, i rozdziela to na:
  * blokujące (ON DELETE RESTRICT / NO ACTION) — usunięcie niemożliwe,
  * kaskadowe (CASCADE / SET NULL) — zostaną usunięte lub odpięte razem
    z rekordem; GUI pokaże je w pytaniu o potwierdzenie.

Funkcja czyta strukturę z PRAGMA foreign_key_list, więc sama nadąża za
zmianami schematu — nowa tabela z kluczem obcym nie wymaga zmian tutaj.
"""
from __future__ import annotations

import sqlite3

from i18n.tlumacz import t

_KASKADOWE = {"CASCADE", "SET NULL", "SET DEFAULT"}


def tabele_zrodlowe(polaczenie: sqlite3.Connection) -> set[str]:
    """Tabele, które mają klucze obce (potrzebne do testu tłumaczeń)."""
    wynik = set()
    for (tabela,) in polaczenie.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        if polaczenie.execute(f"PRAGMA foreign_key_list({tabela})").fetchone():
            wynik.add(tabela)
    return wynik


def zaleznosci(polaczenie: sqlite3.Connection, tabela: str, klucz) -> tuple[dict, dict]:
    """Zwraca (blokujące, kaskadowe): {(tabela, kolumna): liczba_wierszy}."""
    blokujace, kaskadowe = {}, {}
    for zrodlo in sorted(tabele_zrodlowe(polaczenie)):
        for fk in polaczenie.execute(f"PRAGMA foreign_key_list({zrodlo})").fetchall():
            if fk["table"] != tabela:
                continue
            liczba = polaczenie.execute(
                f"SELECT COUNT(*) FROM {zrodlo} WHERE {fk['from']} = ?", (klucz,)).fetchone()[0]
            if liczba:
                cel = kaskadowe if fk["on_delete"] in _KASKADOWE else blokujace
                cel[(zrodlo, fk["from"])] = cel.get((zrodlo, fk["from"]), 0) + liczba
    return blokujace, kaskadowe


def opis(zaleznosci_: dict, jezyk: str | None = None) -> str:
    """'Modele: 12, Kategorie: 3' — forma „etykieta: liczba” omija polską
    odmianę liczebników (1 model, 2 modele, 5 modeli)."""
    return ", ".join(f"{t('tabela.' + tabela, jezyk)}: {liczba}"
                     for (tabela, _), liczba in sorted(zaleznosci_.items()))
