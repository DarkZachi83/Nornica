# SPDX-License-Identifier: GPL-3.0-or-later
"""Otwieranie połączenia z bazą SQLite i obsługa transakcji."""
from __future__ import annotations

import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from wyjatki import BladNornicy

# 3.35: UPDATE ... RETURNING (liczniki kodów inwentarzowych)
MIN_WERSJA_SQLITE = (3, 35, 0)

# ---------------------------------------------------------------------------
# Kolacja NORNICA: sortowanie zgodne z polskim alfabetem, bez wielkości liter.
#
# Wbudowane NOCASE w SQLite składa tylko litery ASCII: „Łódź” i „łódź” są dla
# niego różne, a „Żółw” ląduje za „zebrą” tylko przypadkiem kodów Unicode.
# Kolacji z Pythona NIE wpisujemy w definicje kolumn: baza musi się otwierać
# w zewnętrznych narzędziach (np. DB Browser for SQLite), które jej nie znają.
# Repozytoria używają jej jawnie: ORDER BY nazwa COLLATE NORNICA.
# ---------------------------------------------------------------------------
NAZWA_KOLACJI = "NORNICA"
_ALFABET = "aąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż"
_POZYCJA = {litera: 1000 + i for i, litera in enumerate(_ALFABET)}


def klucz_sortowania(tekst: str) -> tuple:
    """Klucz: litery wg alfabetu polskiego, obce litery z diakrytykami
    (é, ü) przy swojej literze bazowej, cyfry i znaki przed literami."""
    klucz = []
    for znak in tekst.casefold():
        pozycja = _POZYCJA.get(znak)
        if pozycja is None:
            baza = unicodedata.normalize("NFD", znak)[0]
            pozycja = _POZYCJA.get(baza, ord(znak) if ord(znak) < 1000 else 10_000 + ord(znak))
        klucz.append(pozycja)
    # remis (np. „Amiga” i „AMIGA”) rozstrzyga oryginalny tekst — stabilna kolejność
    return (tuple(klucz), tekst)


def _porownaj(a: str, b: str) -> int:
    ka, kb = klucz_sortowania(a), klucz_sortowania(b)
    return (ka > kb) - (ka < kb)


def sprawdz_srodowisko(polaczenie: sqlite3.Connection) -> None:
    """Sprawdza wersję SQLite i obecność funkcji JSON."""
    if sqlite3.sqlite_version_info < MIN_WERSJA_SQLITE:
        raise BladNornicy("blad.srodowisko_sqlite",
                          wersja=sqlite3.sqlite_version,
                          wymagana=".".join(map(str, MIN_WERSJA_SQLITE)))
    try:
        polaczenie.execute("SELECT json_valid('{}')")
    except sqlite3.OperationalError as blad:
        raise BladNornicy("blad.srodowisko_json") from blad


def otworz_baze(sciezka: str | Path) -> sqlite3.Connection:
    """Otwiera bazę i ustawia parametry połączenia.

    isolation_level=None: moduł sqlite3 nie otwiera transakcji niejawnie,
    robimy to sami (funkcja `transakcja`). Dzięki temu wiadomo dokładnie,
    gdzie transakcja się zaczyna i kończy.

    Tryb dziennika zostaje domyślny (DELETE), a nie WAL: baza w spoczynku
    to jeden plik, co jest bezpieczne przy kopiowaniu i w synchronizowanych
    folderach. Dla programu jednoosobowego WAL nie daje odczuwalnego zysku.
    """
    sciezka = str(sciezka)
    if sciezka != ":memory:":
        Path(sciezka).parent.mkdir(parents=True, exist_ok=True)
    polaczenie = sqlite3.connect(sciezka, isolation_level=None)
    polaczenie.row_factory = sqlite3.Row
    polaczenie.create_collation(NAZWA_KOLACJI, _porownaj)
    sprawdz_srodowisko(polaczenie)
    polaczenie.execute("PRAGMA foreign_keys = ON")
    polaczenie.execute("PRAGMA busy_timeout = 5000")
    # Wyzwalacze znaczników czasu są odporne na rekursję (migracja 002),
    # ale nie ma powodu jej włączać: ustawiamy jawnie wartość domyślną,
    # żeby nikt nie musiał zgadywać, czy była świadomie wybrana.
    polaczenie.execute("PRAGMA recursive_triggers = OFF")
    return polaczenie


@contextmanager
def transakcja(polaczenie: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Blok wykonywany w całości albo wcale."""
    polaczenie.execute("BEGIN IMMEDIATE")
    try:
        yield polaczenie
    except BaseException:
        polaczenie.execute("ROLLBACK")
        raise
    else:
        polaczenie.execute("COMMIT")
