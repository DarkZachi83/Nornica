# SPDX-License-Identifier: GPL-3.0-or-later
"""Zasoby bez powiązań („sieroty”) i ich bezpieczne usuwanie.

Usunięcie modelu lub egzemplarza kasuje powiązania (CASCADE), ale nie sam
zasób ani jego plik — celowo, bo BIOS czy skan instrukcji bywa nie do
odzyskania. Sprzątanie jest zawsze ręczne: program pokazuje listę sierot
z rozmiarami, a użytkownik zaznacza, co usunąć. Nigdy automatycznie.

Kolejność przy usuwaniu: najpierw rekord w bazie (transakcja), dopiero po
zatwierdzeniu plik na dysku. Gdyby usuwanie pliku się nie powiodło, zostaje
plik bez rekordu, który wyłapie skan folderu (uslugi/pliki.py, etap 3).
Odwrotna kolejność zostawiłaby rekord wskazujący nieistniejący plik.
"""
from __future__ import annotations

import sqlite3


def osierocone(polaczenie: sqlite3.Connection) -> list[sqlite3.Row]:
    """Zasoby bez żadnego powiązania, najstarsze najpierw.

    NOT EXISTS zamiast NOT IN: NOT IN zwraca pusty wynik, gdy podzapytanie
    zawiera choć jeden NULL. Tu zasob_id jest NOT NULL, ale nawyk chroni
    przed tą pułapką w innych miejscach.
    """
    return polaczenie.execute(
        "SELECT z.id, z.typ, z.tytul, z.plik_sciezka, z.plik_rozmiar, z.dodano "
        "FROM zasob z "
        "WHERE NOT EXISTS (SELECT 1 FROM zasob_powiazanie p WHERE p.zasob_id = z.id) "
        "ORDER BY z.dodano").fetchall()


def usun_osierocone(polaczenie: sqlite3.Connection, identyfikatory: list[int]) -> list[str]:
    """Usuwa wskazane zasoby, o ile NADAL są sierotami.

    Między wyświetleniem listy a kliknięciem „Usuń” użytkownik mógł zasób
    gdzieś podpiąć — taki rekord zostaje nietknięty. Zwraca ścieżki plików
    do usunięcia z dysku PO zatwierdzeniu transakcji.
    """
    if not polaczenie.in_transaction:
        raise RuntimeError("usun_osierocone() wymaga otwartej transakcji")
    if not identyfikatory:
        return []
    znaki = ", ".join("?" * len(identyfikatory))
    wiersze = polaczenie.execute(
        f"DELETE FROM zasob WHERE id IN ({znaki}) "
        "AND NOT EXISTS (SELECT 1 FROM zasob_powiazanie p WHERE p.zasob_id = zasob.id) "
        "RETURNING plik_sciezka", identyfikatory).fetchall()
    return [w["plik_sciezka"] for w in wiersze if w["plik_sciezka"]]
