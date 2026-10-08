# SPDX-License-Identifier: GPL-3.0-or-later
"""Ścieżki danych programu, zależne od systemu operacyjnego.

Linux (Arch):  $XDG_DATA_HOME/nornica  albo  ~/.local/share/nornica
Windows:       %APPDATA%\\Nornica
macOS:         ~/Library/Application Support/Nornica
Zmienna środowiskowa NORNICA_DANE nadpisuje ścieżkę (testy, kolekcja na innym dysku).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

KATALOG_PROGRAMU = Path(__file__).resolve().parent
PLIK_BAZY = "nornica.sqlite3"


def katalog_danych() -> Path:
    nadpisany = os.environ.get("NORNICA_DANE")
    if nadpisany:
        return Path(nadpisany).expanduser()
    if sys.platform.startswith("win"):
        baza = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(baza) / "Nornica"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Nornica"
    baza = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(baza) / "nornica"


def sciezka_bazy() -> Path:
    return katalog_danych() / PLIK_BAZY


def katalog_plikow() -> Path:
    """Zarządzany magazyn oryginałów (PDF-y, BIOS-y, zdjęcia)."""
    return katalog_danych() / "pliki"


def katalog_kopii() -> Path:
    return katalog_danych() / "kopie"


def przygotuj_katalogi() -> None:
    for katalog in (katalog_danych(), katalog_plikow(), katalog_kopii()):
        katalog.mkdir(parents=True, exist_ok=True)


def plik_dziennika() -> Path:
    return katalog_danych() / "nornica.log"
