# SPDX-License-Identifier: GPL-3.0-or-later
"""Eksport CSV: jeden plik na tabelę.

Zapis zgodny z Excelem w danym języku:
  * UTF-8 z BOM — bez niego Excel w Windows czyta polskie litery jako krzaczki,
  * po polsku separator „;” i przecinek dziesiętny (Excel PL traktuje przecinek
    jako część liczby), po angielsku „,” i kropka.
"""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from raporty.dane import KWOTA, Tabela

SEPARATOR = {"pl": ";", "en": ","}
DZIESIETNY = {"pl": ",", "en": "."}


def _wartosc(wartosc, typ: str, jezyk: str) -> str:
    if wartosc is None:
        return ""
    if typ == KWOTA and isinstance(wartosc, Decimal):
        return f"{wartosc:.2f}".replace(".", DZIESIETNY.get(jezyk, "."))
    if isinstance(wartosc, float):
        return f"{wartosc:g}".replace(".", DZIESIETNY.get(jezyk, "."))
    return str(wartosc)


def zapisz(tabele: list[Tabela], baza: Path, jezyk: str) -> list[Path]:
    """baza: ścieżka bez rozszerzenia; pliki: <baza>_<tabela>.csv"""
    wynik = []
    for tabela in tabele:
        sciezka = baza.with_name(f"{baza.name}_{tabela.plik}.csv")
        with open(sciezka, "w", encoding="utf-8-sig", newline="") as plik:
            pisarz = csv.writer(plik, delimiter=SEPARATOR.get(jezyk, ","), quoting=csv.QUOTE_MINIMAL)
            pisarz.writerow([k.naglowek for k in tabela.kolumny])
            for wiersz in tabela.wiersze:
                pisarz.writerow([_wartosc(w, k.typ, jezyk) for w, k in zip(wiersz, tabela.kolumny)])
        wynik.append(sciezka)
    return wynik
