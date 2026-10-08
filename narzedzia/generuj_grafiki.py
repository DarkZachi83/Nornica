# SPDX-License-Identifier: GPL-3.0-or-later
"""Generuje ikony i obrazek „brak zdjęcia” z ilustracji źródłowej.

Wymaga Pillow. Uruchamiane przez dewelopera po zmianie ilustracji — gotowe
pliki PNG są w repozytorium, więc sam program do startu Pillow nie potrzebuje
(tkinter czyta PNG natywnie).

    python narzedzia/generuj_grafiki.py              # ikony + brak_zdjecia.png
    python narzedzia/generuj_grafiki.py --powitanie  # dodatkowo nadpisz powitanie.png

Ekran powitalny (zasoby/powitanie.png) jest przygotowywany ręcznie, więc
domyślnie NIE jest nadpisywany.

Kadry są podane względnie (ułamek szerokości i wysokości), żeby działały przy
każdej rozdzielczości ilustracji — po zamianie ilustracji 2816×1536 na
1024×559 współrzędne w pikselach trafiłyby w złe miejsce.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

KORZEN = Path(__file__).resolve().parents[1]
ZRODLO = KORZEN / "zasoby" / "zrodlo" / "nornica.jpeg"
CEL = KORZEN / "zasoby"

KADR_GLOWY = (0.5149, 0.0977, 0.6641, 0.3711)          # głowa nornicy (kwadrat)
KADR_BRAKU_ZDJECIA = (0.4474, 0.0716, 0.7322, 0.4622)  # nornica przy regale, 4:3
ROZMIAR_ZDJECIA_GLOWNEGO = (280, 210)                  # musi się zgadzać z gui/szczegoly.py
SZEROKOSC_POWITALNEGO = 1020


def kadr(obraz: Image.Image, wzgledny: tuple[float, float, float, float]) -> Image.Image:
    w, h = obraz.size
    x0, y0, x1, y1 = wzgledny
    return obraz.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))


def zaokraglij(obraz: Image.Image, promien_proc: float = 0.18) -> Image.Image:
    maska = Image.new("L", obraz.size, 0)
    promien = int(obraz.size[0] * promien_proc)
    ImageDraw.Draw(maska).rounded_rectangle((0, 0, *obraz.size), promien, fill=255)
    wynik = obraz.convert("RGBA")
    wynik.putalpha(maska)
    return wynik


def main(nadpisz_powitanie: bool = False) -> None:
    oryginal = Image.open(ZRODLO).convert("RGB")
    glowa = kadr(oryginal, KADR_GLOWY)
    ikony = []
    for rozmiar in (256, 64, 32, 16):
        ikona = zaokraglij(glowa.resize((rozmiar, rozmiar), Image.LANCZOS))
        ikona.save(CEL / f"ikona_{rozmiar}.png")
        ikony.append(ikona)
    ikony[0].save(CEL / "nornica.ico", sizes=[(s, s) for s in (256, 64, 32, 16)])

    # Obrazek zastępczy zdjęcia głównego: przygaszone kolory odróżniają go od
    # prawdziwego zdjęcia. Napis (NO IMAGE / BRAK ZDJĘCIA) program dokłada
    # w chwili wyświetlenia — zależy od języka.
    brak = kadr(oryginal, KADR_BRAKU_ZDJECIA).resize(ROZMIAR_ZDJECIA_GLOWNEGO, Image.LANCZOS)
    brak = ImageEnhance.Brightness(ImageEnhance.Color(brak).enhance(0.45)).enhance(1.08)
    brak.save(CEL / "brak_zdjecia.png", optimize=True)

    if nadpisz_powitanie:
        wysokosc = round(oryginal.height * SZEROKOSC_POWITALNEGO / oryginal.width)
        oryginal.resize((SZEROKOSC_POWITALNEGO, wysokosc), Image.LANCZOS).save(
            CEL / "powitanie.png", optimize=True)
    print("Gotowe:", ", ".join(p.name for p in sorted(CEL.glob("*.*"))))


if __name__ == "__main__":
    main("--powitanie" in sys.argv)
