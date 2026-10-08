# SPDX-License-Identifier: GPL-3.0-or-later
"""Słowniki: statusy, waluty, producenci, kategorie (z szablonami atrybutów)."""
from __future__ import annotations

import json
import sqlite3

from baza.polaczenie import klucz_sortowania
from i18n.tlumacz import nazwa


def statusy(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT id, kod, nazwy FROM status ORDER BY kolejnosc, id").fetchall()


def status_id(db: sqlite3.Connection, kod: str) -> int | None:
    wiersz = db.execute("SELECT id FROM status WHERE kod = ?", (kod,)).fetchone()
    return wiersz[0] if wiersz else None


def waluty(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Bieżące waluty najpierw, historyczne na końcu listy."""
    return db.execute("SELECT kod, nazwy, miejsca_dzies, historyczna FROM waluta "
                      "ORDER BY historyczna, kod").fetchall()


def miejsca_dziesietne(db: sqlite3.Connection, kod: str) -> int:
    wiersz = db.execute("SELECT miejsca_dzies FROM waluta WHERE kod = ?", (kod,)).fetchone()
    return wiersz[0] if wiersz else 2


def producenci(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT id, nazwa FROM producent ORDER BY nazwa COLLATE NORNICA").fetchall()


def producent_id(db: sqlite3.Connection, nazwa_: str | None, utworz: bool = False) -> int | None:
    """Szuka producenta po nazwie (bez wielkości liter); opcjonalnie tworzy nowego."""
    nazwa_ = (nazwa_ or "").strip()
    if not nazwa_:
        return None
    wiersz = db.execute("SELECT id FROM producent WHERE nazwa = ?", (nazwa_,)).fetchone()
    if wiersz:
        return wiersz[0]
    if utworz:
        return db.execute("INSERT INTO producent (nazwa) VALUES (?)", (nazwa_,)).lastrowid
    return None


# ---------------------------------------------------------------------------
# Kategorie
# ---------------------------------------------------------------------------
def kategorie(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute("SELECT id, kod, rodzic_id, rodzaj, nazwy, szablon_atrybutow, kolejnosc "
                      "FROM kategoria").fetchall()


def kategoria(db: sqlite3.Connection, kat_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM kategoria WHERE id = ?", (kat_id,)).fetchone()


def kategorie_plasko(db: sqlite3.Connection, jezyk: str | None = None) -> list[tuple[int, int, str]]:
    """Drzewo kategorii spłaszczone do listy (id, głębokość, nazwa) w kolejności
    wyświetlania: rodzic, potem jego dzieci. Nazwy w podanym języku."""
    wiersze = kategorie(db)
    dzieci: dict[int | None, list] = {}
    for w in wiersze:
        dzieci.setdefault(w["rodzic_id"], []).append(w)
    wynik = []

    def zejdz(rodzic, glebokosc):
        for w in sorted(dzieci.get(rodzic, []),
                        key=lambda w: (w["kolejnosc"], klucz_sortowania(nazwa(w["nazwy"], jezyk)))):
            wynik.append((w["id"], glebokosc, nazwa(w["nazwy"], jezyk)))
            if glebokosc < 16:
                zejdz(w["id"], glebokosc + 1)

    zejdz(None, 0)
    return wynik


def lancuch_kategorii(db: sqlite3.Connection, kat_id: int | None) -> list[int]:
    """Identyfikatory od wskazanej kategorii w górę do korzenia."""
    rodzice = {w["id"]: w["rodzic_id"] for w in db.execute("SELECT id, rodzic_id FROM kategoria")}
    lancuch = []
    while kat_id is not None and kat_id not in lancuch and len(lancuch) < 32:
        lancuch.append(kat_id)
        kat_id = rodzice.get(kat_id)
    return lancuch


def szablon(db: sqlite3.Connection, kat_id: int | None) -> list[dict]:
    """Pola atrybutów kategorii razem z polami odziedziczonymi po rodzicach.
    Pole o tym samym kodzie w kategorii podrzędnej zastępuje pole rodzica."""
    pola: dict[str, dict] = {}
    for kid in reversed(lancuch_kategorii(db, kat_id)):
        wiersz = db.execute("SELECT szablon_atrybutow FROM kategoria WHERE id = ?", (kid,)).fetchone()
        for pole in json.loads(wiersz[0] or "[]"):
            if pole.get("wartosci_wlasne"):
                # wartości dopisane przez użytkownika do pola wbudowanego — trzymane osobno,
                # żeby aktualizacja listy wbudowanej ich nie nadpisała; tu łączone w jedną listę
                pole = {**pole, "wartosci": list(pole.get("wartosci", [])) + list(pole["wartosci_wlasne"])}
            pola[pole["kod"]] = pole
    return list(pola.values())
