# SPDX-License-Identifier: GPL-3.0-or-later
"""Migracje schematu.

Pliki NNN_opis.sql (schemat) i NNN_opis.py (przeliczenia danych, funkcja
migruj(db)) w katalogu baza/schemat są stosowane po kolei.
Każda migracja wykonuje się w osobnej transakcji: albo w całości, albo wcale.
Przed migracją istniejącej bazy powstaje kopia zapasowa.

Zastosowana migracja jest ZAMROŻONA. Suma kontrolna każdego pliku trafia do
bazy, a przy starcie program sprawdza, czy pliki już zastosowane nie zostały
zmienione. Poprawki schematu idą zawsze do nowego pliku NNN.
Końce linii są normalizowane przed liczeniem sumy, więc konwersja LF/CRLF
(np. przez git na Windows) nie wywołuje fałszywego alarmu.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from wyjatki import BladNornicy

KATALOG_SCHEMATU = Path(__file__).resolve().parent / "schemat"
_WZOR_PLIKU = re.compile(r"^(\d{3})_[\w-]+\.(sql|py)$")


def znajdz_migracje(katalog: Path = KATALOG_SCHEMATU) -> list[tuple[int, Path]]:
    migracje = []
    for plik in sorted([*katalog.glob("*.sql"), *katalog.glob("*.py")]):
        dopasowanie = _WZOR_PLIKU.match(plik.name)
        if dopasowanie:
            migracje.append((int(dopasowanie.group(1)), plik))
    numery = [numer for numer, _ in migracje]
    if len(numery) != len(set(numery)):
        raise ValueError(f"Zdublowany numer migracji w {katalog}")
    return migracje


def suma_kontrolna(plik: Path) -> str:
    return hashlib.sha256(plik.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _migracja_python(polaczenie: sqlite3.Connection, numer: int, plik: Path) -> None:
    """Migracja danych w Pythonie (np. przeliczenie wartości w JSON), gdy SQL byłby
    nieczytelny. Plik definiuje funkcję migruj(db). Ta sama transakcja co zapis
    wersji: całość albo nic. Ten sam strażnik sum kontrolnych co dla SQL."""
    import importlib.util
    specyfikacja = importlib.util.spec_from_file_location(f"migracja_{numer:03d}", plik)
    modul = importlib.util.module_from_spec(specyfikacja)
    specyfikacja.loader.exec_module(modul)
    polaczenie.execute("BEGIN IMMEDIATE")
    try:
        modul.migruj(polaczenie)
        polaczenie.execute("INSERT INTO wersja_schematu (wersja, zastosowano, suma_sha256) "
                           "VALUES (?, CURRENT_TIMESTAMP, ?)", (numer, suma_kontrolna(plik)))
    except BaseException:
        polaczenie.execute("ROLLBACK")
        raise
    polaczenie.execute("COMMIT")


def biezaca_wersja(polaczenie: sqlite3.Connection) -> int:
    polaczenie.execute(
        "CREATE TABLE IF NOT EXISTS wersja_schematu ("
        " wersja INTEGER PRIMARY KEY,"
        " zastosowano TEXT NOT NULL,"
        " suma_sha256 TEXT)")
    kolumny = {w["name"] for w in polaczenie.execute("PRAGMA table_info(wersja_schematu)")}
    if "suma_sha256" not in kolumny:   # baza sprzed wprowadzenia sum kontrolnych
        polaczenie.execute("ALTER TABLE wersja_schematu ADD COLUMN suma_sha256 TEXT")
    wersja = polaczenie.execute("SELECT MAX(wersja) FROM wersja_schematu").fetchone()[0]
    return wersja or 0


def zrob_kopie(polaczenie: sqlite3.Connection, katalog_kopii: Path, wersja: int) -> Path:
    """Kopia przez API backup SQLite — spójna nawet przy otwartym połączeniu."""
    katalog_kopii.mkdir(parents=True, exist_ok=True)
    znacznik = datetime.now().strftime("%Y%m%d-%H%M%S")
    cel = katalog_kopii / f"przed_migracja_v{wersja}_{znacznik}.sqlite3"
    kopia = sqlite3.connect(cel)
    try:
        polaczenie.backup(kopia)
    finally:
        kopia.close()
    return cel


def migruj(polaczenie: sqlite3.Connection,
           katalog_kopii: Path | None = None,
           katalog: Path = KATALOG_SCHEMATU) -> tuple[list[int], Path | None]:
    """Stosuje oczekujące migracje. Zwraca (lista_numerów, ścieżka_kopii)."""
    wersja = biezaca_wersja(polaczenie)
    dostepne = znajdz_migracje(katalog)
    najwyzsza = max((numer for numer, _ in dostepne), default=0)
    if wersja > najwyzsza:
        raise BladNornicy("blad.baza_nowsza", baza=wersja, program=najwyzsza)

    # Strażnik zamrożonych migracji
    zapisane = dict(polaczenie.execute("SELECT wersja, suma_sha256 FROM wersja_schematu"))
    for numer, plik in dostepne:
        suma = zapisane.get(numer)
        if suma is not None and suma != suma_kontrolna(plik):
            raise BladNornicy("blad.migracja_zmieniona", numer=numer)

    oczekujace = [(numer, plik) for numer, plik in dostepne if numer > wersja]
    if not oczekujace:
        return [], None

    kopia = None
    if wersja > 0 and katalog_kopii is not None:
        kopia = zrob_kopie(polaczenie, katalog_kopii, wersja)

    zastosowane = []
    for numer, plik in oczekujace:
        if plik.suffix == ".py":
            _migracja_python(polaczenie, numer, plik)
            zastosowane.append(numer)
            continue
        sql = plik.read_text(encoding="utf-8")
        # executescript nie otwiera transakcji sam — obejmujemy cały skrypt
        skrypt = (f"BEGIN IMMEDIATE;\n{sql}\n;\n"
                  f"INSERT INTO wersja_schematu (wersja, zastosowano, suma_sha256) "
                  f"VALUES ({numer}, CURRENT_TIMESTAMP, '{suma_kontrolna(plik)}');\nCOMMIT;")
        try:
            polaczenie.executescript(skrypt)
        except Exception:
            if polaczenie.in_transaction:
                polaczenie.execute("ROLLBACK")
            raise
        zastosowane.append(numer)
    return zastosowane, kopia
