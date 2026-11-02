# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Budowa samodzielnego programu (PyInstaller): na Windowsie folder NORNICA
z NORNICA.exe — bez instalowania Pythona.

    pyinstaller nornica.spec --noconfirm

Moduły szukają swoich plików obok siebie (Path(__file__).parent), więc pliki
danych trafiają do paczki pod tymi samymi ścieżkami względnymi co w repozytorium.
Migracje (baza/schemat) jadą jako pliki, nie jako kod: ich sumy kontrolne są
zapisane w bazach użytkowników, a migracja 005 jest ładowana z pliku .py.
"""
from pathlib import Path

KORZEN = Path(SPECPATH)

dane = [
    (str(KORZEN / "i18n" / "en.json"), "i18n"),
    (str(KORZEN / "i18n" / "pl.json"), "i18n"),
    (str(KORZEN / "baza" / "schemat"), "baza/schemat"),
    (str(KORZEN / "zasoby"), "zasoby"),
    (str(KORZEN / "LICENSE"), "."),
    (str(KORZEN / "THIRD_PARTY_NOTICES.md"), "."),
]

a = Analysis(
    [str(KORZEN / "nornica.py")],
    pathex=[str(KORZEN)],
    datas=dane,
    # biblioteki opcjonalne ładowane dopiero przy użyciu funkcji — dołączone jawnie
    hiddenimports=["openpyxl", "xlwt", "qrcode", "reportlab", "cryptography", "PIL.ImageTk"],
    excludes=["testy", "narzedzia", "pytest", "unittest.mock"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NORNICA",
    console=False,                  # program okienkowy — bez czarnego okna konsoli
    icon=str(KORZEN / "zasoby" / "nornica.ico"),
    upx=False,                      # UPX częściej wywołuje fałszywe alarmy antywirusów
)

coll = COLLECT(exe, a.binaries, a.datas, name="NORNICA", upx=False)
