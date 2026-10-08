# SPDX-License-Identifier: GPL-3.0-or-later
"""Wartości wyliczeniowe z ograniczeń CHECK w schemacie.

Klucz: "tabela.kolumna". Wartość: (przedrostek klucza tłumaczenia, wartości).
Etykieta wartości to t(f"{przedrostek}.{wartosc}").
Test sprawdza zgodność z plikiem SQL i obecność wszystkich tłumaczeń.
"""
from i18n.tlumacz import t

ENUMY: dict[str, tuple[str, tuple[str, ...]]] = {
    "kategoria.rodzaj": ("kategoria.rodzaj",
                         ("komputer_fabryczny", "skladak", "czesc", "akcesorium")),
    "lokalizacja.typ": ("lokalizacja.typ",
                        ("pokoj", "regal", "polka", "pudelko", "szuflada", "inne")),
    "zlacze_typ.rodzaj": ("zlacze.rodzaj", ("port", "slot", "gniazdo", "interfejs")),
    "model_zlacze.rola": ("zlacze.rola", ("posiada", "wymaga")),
    "egzemplarz_zlacze.rola": ("zlacze.rola", ("posiada", "wymaga")),
    "egzemplarz.stan_wizualny": ("stan_wizualny",
                                 ("idealny", "bardzo_dobry", "dobry", "zuzyty", "slaby")),
    "zasob.typ": ("zasob.typ", ("instrukcja", "sterownik", "bios", "rom",
                                "dokumentacja", "zdjecie", "notatka", "link")),
    "zdarzenie.typ": ("zdarzenie.typ", ("test", "naprawa")),
    "zdarzenie.podtyp": ("zdarzenie.podtyp", ("naprawa", "modyfikacja")),
    "zdarzenie.wynik": ("zdarzenie.wynik", ("ok", "czesciowo", "blad")),
    "inwentaryzacja_wynik.wynik": ("inw.grupa", ("na_miejscu", "nie_na_miejscu", "brak")),
}


def etykieta(pole: str, wartosc: str, jezyk: str | None = None) -> str:
    """Etykieta wartości wyliczeniowej w bieżącym (lub podanym) języku."""
    przedrostek, _ = ENUMY[pole]
    return t(f"{przedrostek}.{wartosc}", jezyk)


def opcje(pole: str, jezyk: str | None = None) -> list[tuple[str, str]]:
    """Lista (wartość, etykieta) — np. dla listy rozwijanej w GUI."""
    _, wartosci = ENUMY[pole]
    return [(w, etykieta(pole, w, jezyk)) for w in wartosci]
