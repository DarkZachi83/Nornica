# SPDX-License-Identifier: GPL-3.0-or-later
"""Eksport kolekcji: zbiera tabele raz i zapisuje je w wybranych formatach.

Nazwy plików wynikają z jednej ścieżki bazowej (bez rozszerzenia):
  kolekcja.xlsx, kolekcja.xls, kolekcja.html,
  kolekcja_egzemplarze.csv, kolekcja_modele.csv… (CSV: plik na tabelę)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from i18n.tlumacz import t
from raporty import dane, eksport_csv, eksport_html, eksport_xls, eksport_xlsx
from wyjatki import BladNornicy

FORMATY = ("csv", "xlsx", "xls", "html")


def dostepne_formaty() -> dict[str, bool]:
    import importlib.util
    return {"csv": True, "html": True, "xlsx": importlib.util.find_spec("openpyxl") is not None,
            "xls": eksport_xls.dostepny()}


def eksportuj(db: sqlite3.Connection, baza: str | Path, formaty: list[str], opcje: dane.Opcje) -> list[Path]:
    """Zwraca listę zapisanych plików. Formaty zapisywane w kolejności FORMATY."""
    formaty = [f for f in FORMATY if f in formaty]
    if not formaty:
        raise BladNornicy("blad.wybierz_format")
    if not opcje.tabele:
        raise BladNornicy("blad.wybierz_tabele")
    baza = Path(baza)
    baza = baza.with_suffix("") if baza.suffix.lower() in {".csv", ".xlsx", ".xls", ".html", ".htm"} else baza
    tabele = dane.zbierz(db, opcje)
    wynik: list[Path] = []
    if "csv" in formaty:
        wynik += eksport_csv.zapisz(tabele, baza, opcje.jezyk)
    if "xlsx" in formaty:
        wynik.append(eksport_xlsx.zapisz(tabele, baza.with_suffix(".xlsx")))
    if "xls" in formaty:
        wynik.append(eksport_xls.zapisz(tabele, baza.with_suffix(".xls")))
    if "html" in formaty:
        if opcje.lokalizacja_id is None:
            zakres = t("etykiety.zakres_wszystko", opcje.jezyk)
        else:
            from baza.repozytoria import lokalizacje
            zakres = lokalizacje.sciezki(db).get(opcje.lokalizacja_id, "")
        wynik.append(eksport_html.zapisz(tabele, dane.podsumowanie(db, opcje), baza.with_suffix(".html"),
                                         opcje.jezyk, zakres))
    return wynik
