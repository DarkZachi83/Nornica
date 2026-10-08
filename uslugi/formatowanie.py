# SPDX-License-Identifier: GPL-3.0-or-later
"""Formatowanie i odczyt wartości zależnych od języka: daty, kwoty, liczby."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from i18n.tlumacz import jezyk_biezacy

_FORMAT_DATY_CZASU = {"pl": "%d.%m.%Y %H:%M", "en": "%Y-%m-%d %H:%M"}
_SEPARATOR = {"pl": ",", "en": "."}


def data_lokalna(tekst_utc: str | None, jezyk: str | None = None) -> str:
    """Znacznik UTC z bazy -> czas lokalny w formacie języka."""
    if not tekst_utc:
        return ""
    try:
        chwila = datetime.fromisoformat(tekst_utc).replace(tzinfo=timezone.utc).astimezone()
    except ValueError:
        return tekst_utc
    return chwila.strftime(_FORMAT_DATY_CZASU.get(jezyk or jezyk_biezacy(), "%Y-%m-%d %H:%M"))


def sprawdz_date(tekst: str | None) -> str | None:
    """Data w formacie RRRR-MM-DD albo None. Zgłasza ValueError przy błędzie."""
    tekst = (tekst or "").strip()
    if not tekst:
        return None
    return date.fromisoformat(tekst).isoformat()


def tekst_na_minor(tekst: str | None, miejsca: int) -> int | None:
    """'199,99' lub '199.99' -> 19999 (dla 2 miejsc). Zgłasza ValueError."""
    tekst = (tekst or "").strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if not tekst:
        return None
    try:
        kwota = Decimal(tekst)
    except InvalidOperation as blad:
        raise ValueError(tekst) from blad
    if kwota < 0:
        raise ValueError(tekst)
    minor = kwota.scaleb(miejsca)
    if minor != minor.to_integral_value():
        raise ValueError(tekst)        # więcej miejsc po przecinku niż ma waluta
    return int(minor)


def minor_na_tekst(minor: int | None, miejsca: int, jezyk: str | None = None) -> str:
    if minor is None:
        return ""
    tekst = f"{Decimal(minor).scaleb(-miejsca):.{miejsca}f}"
    return tekst.replace(".", _SEPARATOR.get(jezyk or jezyk_biezacy(), "."))


def liczba_na_tekst(wartosc, jezyk: str | None = None) -> str:
    """33.0 -> '33'; 7.09 -> '7,09' po polsku, '7.09' po angielsku; tekst bez zmian.
    Formularze przyjmują oba separatory, więc wartość wraca do bazy bez strat."""
    if isinstance(wartosc, bool):
        return "true" if wartosc else "false"
    if isinstance(wartosc, float):
        return f"{wartosc:g}".replace(".", _SEPARATOR.get(jezyk or jezyk_biezacy(), "."))
    return "" if wartosc is None else str(wartosc)


# ---------------------------------------------------------------------------
# Pojemność: w bazie zawsze w bajtach, na ekranie w dobranej jednostce.
# 1 KB = 1024 B — konwencja komputerów, o których mówimy (Atari 2600: 128 B).
# ---------------------------------------------------------------------------
# Bez TB: w retro sprzęcie nie występuje (większe wartości pokazywane w GB).
JEDNOSTKI_POJEMNOSCI = (("B", 1), ("KB", 1024), ("MB", 1024 ** 2), ("GB", 1024 ** 3))
_MNOZNIK = dict(JEDNOSTKI_POJEMNOSCI)


def rozbij_pojemnosc(bajty: int | None, jezyk: str | None = None) -> tuple[str, str]:
    """65536 -> ("64", "KB"); 128 -> ("128", "B"); 1474560 -> ("1,41", "MB").
    Największa jednostka, w której liczba jest ≥ 1."""
    if bajty is None:
        return "", "KB"
    jednostka, mnoznik = JEDNOSTKI_POJEMNOSCI[0]
    for nazwa, wartosc in JEDNOSTKI_POJEMNOSCI:
        if bajty >= wartosc:
            jednostka, mnoznik = nazwa, wartosc
    liczba = bajty / mnoznik
    tekst = f"{liczba:.0f}" if liczba == int(liczba) else f"{liczba:.2f}".rstrip("0").rstrip(".")
    return tekst.replace(".", _SEPARATOR.get(jezyk or jezyk_biezacy(), ".")), jednostka


def pojemnosc_na_tekst(bajty: int | None, jezyk: str | None = None) -> str:
    if bajty is None:
        return ""
    liczba, jednostka = rozbij_pojemnosc(bajty, jezyk)
    return f"{liczba} {jednostka}"


def tekst_na_bajty(liczba: str, jednostka: str) -> int:
    """„128”, „B” -> 128; „1,44”, „MB” -> 1509949. Zgłasza ValueError."""
    tekst = (liczba or "").strip().replace(" ", "").replace(",", ".")
    try:
        wartosc = Decimal(tekst) if tekst else None
    except InvalidOperation:
        raise ValueError(liczba) from None
    if wartosc is None or wartosc < 0 or jednostka not in _MNOZNIK:
        raise ValueError(liczba)
    return int((wartosc * _MNOZNIK[jednostka]).to_integral_value())
