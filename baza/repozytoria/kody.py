# SPDX-License-Identifier: GPL-3.0-or-later
"""Generowanie kodów inwentarzowych i kodów etykiet lokalizacji.

Kody pochodzą z tabeli `licznik`, a nie z MAX() po istniejących kodach:
  * MAX() na tekście porównuje leksykalnie: 'NOR-1000000' < 'NOR-999999',
  * po usunięciu ostatniego rekordu MAX() oddałby jego numer ponownie,
    a wydrukowana etykieta wskazywałaby nagle inny sprzęt,
  * kod wpisany ręcznie (np. ze starej ewidencji) nie przestawia numeracji.

Wyścig: funkcja wymaga otwartej transakcji. `transakcja()` zaczyna się od
BEGIN IMMEDIATE, więc blokada zapisu jest założona przed odczytem licznika
i dwa połączenia nie dostaną tego samego numeru. W obrębie programu zapis
do bazy wykonuje wyłącznie wątek GUI (wątki w tle tylko pobierają dane
z sieci), więc wyścig między wątkami jednego połączenia nie powstaje.
"""
from __future__ import annotations

import sqlite3

from baza.repozytoria import ustawienia

# rodzaj -> (tabela, kolumna, klucz prefiksu w ustawieniach, prefiks domyślny, cyfry)
RODZAJE = {
    "egzemplarz":  ("egzemplarz", "kod_inwentarzowy", "prefiks_kodu", "NOR", 6),
    "lokalizacja": ("lokalizacja", "kod_etykiety", "prefiks_lokalizacji", "LOC", 4),
}


def nastepny_kod(polaczenie: sqlite3.Connection, rodzaj: str = "egzemplarz") -> str:
    """Zwraca kolejny wolny kod. Wywoływać wewnątrz `transakcja()`."""
    if not polaczenie.in_transaction:
        raise RuntimeError("nastepny_kod() wymaga otwartej transakcji (BEGIN IMMEDIATE)")
    tabela, kolumna, klucz_prefiksu, prefiks_domyslny, cyfry = RODZAJE[rodzaj]
    prefiks = ustawienia.pobierz(polaczenie, klucz_prefiksu, prefiks_domyslny)
    while True:
        numer = polaczenie.execute(
            "UPDATE licznik SET wartosc = wartosc + 1 WHERE nazwa = ? RETURNING wartosc",
            (rodzaj,)).fetchall()[0][0]
        kod = f"{prefiks}-{numer:0{cyfry}d}"
        # Pomijamy numer zajęty przez kod wpisany ręcznie (porównanie NOCASE z kolumny).
        zajety = polaczenie.execute(
            f"SELECT 1 FROM {tabela} WHERE {kolumna} = ?", (kod,)).fetchone()
        if not zajety:
            return kod
