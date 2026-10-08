# SPDX-License-Identifier: GPL-3.0-or-later
"""Dziennik błędów: plik nornica.log w katalogu danych programu.

Bez niego błąd w oknie (np. przerwane budowanie zawartości) trafiał tylko do
terminala — a z menu programu terminala nie widać. Zgłoszenie: okno „Telefon
jako skaner” skurczone do pustej ramki, bez żadnego komunikatu.

Plik ma ograniczony rozmiar (3 × 1 MB) i nie rośnie bez końca.
"""
from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

DZIENNIK = logging.getLogger("nornica")
_plik: Path | None = None


def wlacz(sciezka: Path) -> None:
    """Zapis do pliku + przechwycenie błędów spoza okien (wątki w tle, start programu)."""
    global _plik
    _plik = Path(sciezka)
    _plik.parent.mkdir(parents=True, exist_ok=True)
    obsluga = RotatingFileHandler(_plik, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    obsluga.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    DZIENNIK.addHandler(obsluga)
    DZIENNIK.setLevel(logging.INFO)

    def watek(argumenty):
        DZIENNIK.error("Błąd w wątku %s", argumenty.thread.name if argumenty.thread else "?",
                       exc_info=(argumenty.exc_type, argumenty.exc_value, argumenty.exc_traceback))

    threading.excepthook = watek
    poprzedni = sys.excepthook

    def program(typ, wartosc, slad):
        DZIENNIK.critical("Nieobsłużony błąd", exc_info=(typ, wartosc, slad))
        poprzedni(typ, wartosc, slad)

    sys.excepthook = program


def plik() -> Path | None:
    return _plik


def blad(opis: str, exc_info=True) -> None:
    DZIENNIK.error(opis, exc_info=exc_info)
