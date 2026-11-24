# SPDX-License-Identifier: GPL-3.0-or-later
"""Pasek menu okna głównego. Budowany od nowa przy każdej przebudowie okna
(zmiana języka), więc etykiety zawsze są w bieżącym języku."""
from __future__ import annotations

import tkinter as tk

from gui.model_drzewa import TRYBY
from gui.styl import MOTYWY
from i18n.tlumacz import JEZYKI, t

TRYB_KLUCZ = {"lokalizacje": "widok.lokalizacje", "montaz": "widok.montaz"}


def zbuduj_menu(okno) -> None:
    menu = tk.Menu(okno)
    plik = tk.Menu(menu, tearoff=False)
    plik.add_command(label=t("akcja.nowy_egzemplarz"), accelerator="Ctrl+N",
                     command=okno.nowy_egzemplarz)
    plik.add_command(label=t("akcja.nowa_lokalizacja"), command=okno.nowa_lokalizacja)
    plik.add_command(label=t("akcja.katalog_modeli"), accelerator="Ctrl+M",
                     command=okno.katalog_modeli)
    plik.add_command(label=t("akcja.asystent_ai"), command=okno.asystent_ai)
    plik.add_command(label=t("akcja.etykiety"), accelerator="Ctrl+P", command=okno.drukuj_etykiety)
    plik.add_command(label=t("akcja.eksport"), accelerator="Ctrl+E", command=okno.eksportuj)
    plik.add_command(label=t("akcja.slowniki"), command=okno.slowniki)
    plik.add_command(label=t("akcja.inwentaryzacje"), command=okno.inwentaryzacje)
    plik.add_command(label=t("akcja.porzadki"), command=okno.porzadki)
    plik.add_command(label=t("akcja.kopia"), accelerator="Ctrl+B", command=okno.kopia_zapasowa)
    plik.add_separator()
    plik.add_command(label=t("akcja.telefon"), accelerator="Ctrl+T", command=okno.telefon)
    plik.add_separator()
    plik.add_command(label=t("akcja.zakoncz"), accelerator="Ctrl+Q", command=okno.destroy)
    menu.add_cascade(label=t("menu.plik"), menu=plik)

    widok = tk.Menu(menu, tearoff=False)
    for tryb in TRYBY:
        widok.add_radiobutton(label=t(TRYB_KLUCZ[tryb]), value=tryb, variable=okno.tryb_var,
                              command=okno.tryb_zmieniony)
    widok.add_separator()
    for motyw in MOTYWY:
        widok.add_radiobutton(label=t(f"motyw.{motyw}"), value=motyw, variable=okno.motyw_var,
                              command=okno.przelacz_motyw)
    widok.add_separator()
    widok.add_command(label=t("akcja.odswiez"), accelerator="F5", command=okno.odswiez)
    menu.add_cascade(label=t("menu.widok"), menu=widok)

    jezyk = tk.Menu(menu, tearoff=False)
    for kod in JEZYKI:
        jezyk.add_radiobutton(label=t(f"jezyk.{kod}"), value=kod, variable=okno.jezyk_var,
                              command=okno.przelacz_jezyk)
    menu.add_cascade(label=t("menu.jezyk"), menu=jezyk)

    pomoc = tk.Menu(menu, tearoff=False)
    pomoc.add_command(label=t("akcja.o_programie"), command=okno.o_programie)
    menu.add_cascade(label=t("menu.pomoc"), menu=pomoc)
    okno.configure(menu=menu)
