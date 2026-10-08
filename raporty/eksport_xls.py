# SPDX-License-Identifier: GPL-3.0-or-later
"""Eksport XLS (Excel 97–2003) przez xlwt.

Biblioteka nie jest już rozwijana, a format ma twarde limity: 65 536 wierszy
i 256 kolumn na arkusz, 32 767 znaków w komórce. Program sprawdza je PRZED
zapisem i zgłasza czytelny błąd, zamiast przerwać zapis w połowie pliku.
Bez xlwt opcja .xls jest w oknie eksportu wyłączona.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from raporty.dane import KWOTA, LICZBA, Tabela
from raporty.eksport_xlsx import nazwa_arkusza
from wyjatki import BladNornicy

MAKS_WIERSZY = 65536
MAKS_KOLUMN = 256
MAKS_ZNAKOW = 32767


def dostepny() -> bool:
    import importlib.util
    return importlib.util.find_spec("xlwt") is not None


def zapisz(tabele: list[Tabela], sciezka: Path) -> Path:
    try:
        import xlwt
    except ImportError:
        raise BladNornicy("blad.brak_xlwt") from None
    for tabela in tabele:
        if len(tabela.wiersze) + 1 > MAKS_WIERSZY or len(tabela.kolumny) > MAKS_KOLUMN:
            raise BladNornicy("blad.xls_limit", tabela=tabela.nazwa, wiersze=len(tabela.wiersze))
    skoroszyt = xlwt.Workbook(encoding="utf-8")
    pogrubiony = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour ivory")
    kwota = xlwt.easyxf(num_format_str="#,##0.00")
    liczba = xlwt.easyxf(num_format_str="0")
    uzyte_nazwy: set[str] = set()
    for tabela in tabele:
        nazwa = nazwa_arkusza(tabela.nazwa)
        while nazwa in uzyte_nazwy:                 # xlwt nie przyjmie dwóch arkuszy o tej samej nazwie
            nazwa = nazwa[:28] + f"_{len(uzyte_nazwy)}"
        uzyte_nazwy.add(nazwa)
        arkusz = skoroszyt.add_sheet(nazwa)
        for k, kolumna in enumerate(tabela.kolumny):
            arkusz.write(0, k, kolumna.naglowek, pogrubiony)
            arkusz.col(k).width = 256 * (kolumna.szerokosc + 2)
        for r, wiersz in enumerate(tabela.wiersze, 1):
            for k, (wartosc, kolumna) in enumerate(zip(wiersz, tabela.kolumny)):
                if wartosc is None or wartosc == "":
                    continue
                if isinstance(wartosc, Decimal):
                    wartosc = float(wartosc)
                if isinstance(wartosc, str) and len(wartosc) > MAKS_ZNAKOW:
                    wartosc = wartosc[:MAKS_ZNAKOW - 1] + "…"
                styl = kwota if kolumna.typ == KWOTA else liczba if kolumna.typ == LICZBA else None
                if styl is None:
                    arkusz.write(r, k, wartosc)
                else:
                    arkusz.write(r, k, wartosc, styl)
        arkusz.set_panes_frozen(True)
        arkusz.set_horz_split_pos(1)
    skoroszyt.save(str(sciezka))
    return sciezka
