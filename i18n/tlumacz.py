# SPDX-License-Identifier: GPL-3.0-or-later
"""Warstwa tłumaczeń NORNICA / VOLE.

Zasady (wnioski z Jaźwca):
  * Napis powstaje w chwili wyświetlenia, nigdy przy wczytaniu modułu.
    Stałe w modułach przechowują KLUCZE, a nie gotowe teksty.
  * Bieżący język jest jeden, centralny i czytany przy każdym wywołaniu t().
    Moduły nie mają własnego set_language, więc nie da się „zapomnieć”
    przekazać im języka. Funkcje, które muszą działać w konkretnym języku
    (raporty), przyjmują jawny parametr `jezyk`.
  * Dwa cofnięcia: nieznany język -> domyślny, brakujący klucz -> domyślny,
    w ostateczności sam klucz. Błąd w polach formatowania daje surowy tekst
    i wpis w logu, a nie wyjątek u użytkownika.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Mapping

KATALOG = Path(__file__).resolve().parent
JEZYK_DOMYSLNY = "en"
JEZYKI = ("en", "pl")

_log = logging.getLogger(__name__)
_slowniki: dict[str, dict[str, str]] = {}
_jezyk_biezacy = JEZYK_DOMYSLNY


def _wczytaj(jezyk: str) -> dict[str, str]:
    """Wczytuje słownik języka (raz, potem z pamięci)."""
    if jezyk not in _slowniki:
        plik = KATALOG / f"{jezyk}.json"
        try:
            _slowniki[jezyk] = json.loads(plik.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _slowniki[jezyk] = {}
    return _slowniki[jezyk]


def przeladuj() -> None:
    """Czyści pamięć słowników (przydatne przy edycji plików JSON i w testach)."""
    _slowniki.clear()


def ustaw_jezyk(jezyk: str | None) -> str:
    """Ustawia bieżący język; nieznany kod zamienia na domyślny. Zwraca ustawiony kod."""
    global _jezyk_biezacy
    _jezyk_biezacy = jezyk if jezyk in JEZYKI else JEZYK_DOMYSLNY
    return _jezyk_biezacy


def jezyk_biezacy() -> str:
    return _jezyk_biezacy


def ma_klucz(klucz: str) -> bool:
    """Czy klucz istnieje w słowniku języka domyślnego."""
    return klucz in _wczytaj(JEZYK_DOMYSLNY)


def t(klucz: str, jezyk: str | None = None, **pola) -> str:
    """Zwraca przetłumaczony napis dla klucza, z opcjonalnym wstawieniem pól."""
    jezyk = jezyk or _jezyk_biezacy
    tekst = (_wczytaj(jezyk).get(klucz)
             or _wczytaj(JEZYK_DOMYSLNY).get(klucz)
             or klucz)
    if not pola:
        return tekst
    try:
        return tekst.format(**pola)
    except (KeyError, IndexError, ValueError) as blad:
        _log.warning("Błąd formatowania klucza %r (%s): %s", klucz, jezyk, blad)
        return tekst


def nazwa(nazwy: Mapping[str, str] | str | None, jezyk: str | None = None) -> str:
    """Wybiera nazwę z pola JSON słownika bazy: {"en": ..., "pl": ...}.

    Cofnięcia: bieżący język -> domyślny -> pierwsza dostępna -> pusty napis.
    Wpisy dodane przez użytkownika mogą mieć tylko jeden język.
    """
    if nazwy is None:
        return ""
    if isinstance(nazwy, str):
        try:
            nazwy = json.loads(nazwy)
        except json.JSONDecodeError:
            return nazwy
    jezyk = jezyk or _jezyk_biezacy
    return (nazwy.get(jezyk)
            or nazwy.get(JEZYK_DOMYSLNY)
            or next((w for w in nazwy.values() if w), ""))
