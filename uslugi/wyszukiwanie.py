# SPDX-License-Identifier: GPL-3.0-or-later
"""Wyszukiwanie po fragmencie nazwy na długich listach (np. typy złączy).

Porównanie bez wielkości liter, polskich znaków i znaków przestankowych:
„s-video”, „SVIDEO” i „s video” znajdą „S-Video”, a „zlacze” — „Złącze”.
Zapytanie z kilku słów pasuje, gdy KAŻDE słowo występuje gdzieś w opisie
(w dowolnej kolejności): „dvi dual” znajdzie „DVI-I (Dual-Link)”.
"""
from __future__ import annotations

import re
import unicodedata

_NIE_ALFANUMERYCZNE = re.compile(r"[\W_]+")


def klucz(tekst: str | None) -> str:
    """„Złącze D-Sub 15” -> „zlaczedsub15”."""
    tekst = (tekst or "").replace("ł", "l").replace("Ł", "L")
    tekst = "".join(z for z in unicodedata.normalize("NFKD", tekst) if not unicodedata.combining(z))
    return _NIE_ALFANUMERYCZNE.sub("", tekst.casefold())


def slowa(zapytanie: str | None) -> list[str]:
    return [k for k in (klucz(s) for s in (zapytanie or "").split()) if k]


def pasuje(zapytanie: str | None, *opisy: str | None) -> bool:
    """Puste zapytanie pasuje do wszystkiego."""
    stog = "\x00".join(klucz(o) for o in opisy if o)
    return all(slowo in stog for slowo in slowa(zapytanie))


def filtruj(zapytanie: str | None, pozycje: list[tuple], dodatkowe=None) -> list[tuple]:
    """Pozycje (wartość, etykieta) pasujące do zapytania, w kolejności listy,
    z lepszymi trafieniami na początku: najpierw etykiety zaczynające się od
    pierwszego słowa („vga” stawia „VGA (DE15)” przed „Karta SVGA”), potem
    pasujące samą etykietą, na końcu znalezione dopiero po synonimach.
    `dodatkowe(wartość)` daje słowa szukane, ale niewyświetlane (synonimy,
    kod) — każde osobno, żeby „graphics video” nie udawało „s-vid”."""
    if not slowa(zapytanie):
        return list(pozycje)
    pierwsze = slowa(zapytanie)[0]
    ocenione = []
    for p in pozycje:
        etykieta = p[1].split(": ", 1)[-1]        # „Port: VGA (DE15)” — bez nazwy rodzaju
        if pasuje(zapytanie, p[1]):
            ocena = 0 if klucz(etykieta).startswith(pierwsze) else 1
        elif dodatkowe and pasuje(zapytanie, p[1], *(dodatkowe(p[0]) or "").split()):
            ocena = 2
        else:
            continue
        ocenione.append((ocena, p))
    return [p for _o, p in sorted(ocenione, key=lambda x: x[0])]     # sortowanie stabilne
