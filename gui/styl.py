# SPDX-License-Identifier: GPL-3.0-or-later
"""Wygląd programu.

Paleta pochodzi z tematu kolekcji: szaro-beżowa obudowa, zieleń laminatu
płytki drukowanej jako jedyny akcent, ciepły brąz drewnianych regałów
z ilustracji nornicy. Kolory statusów są stonowane, żeby drzewo z setkami
pozycji nie raziło. Wyrazistość zostawiamy jednemu elementowi: nornicy
na ekranie powitalnym i w oknie „O programie”.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

KOLORY = {
    "tlo": "#E4E1D8",          # obudowa
    "panel": "#F2F0EA",        # pola i listy
    "tusz": "#2A2925",         # tekst
    "przygaszony": "#6E6A60",  # opisy, podpowiedzi
    "laminat": "#2F6B4F",      # akcent: zieleń PCB
    "drewno": "#7A5636",       # lokalizacje
    "zaznaczenie": "#CFE0D6",
    "zaznaczenie_tekstu": "#BDB8AC",   # szary: zaznaczony tekst w polach i na listach wyboru
}

# Kolor tekstu w drzewie według kodu statusu (kody, nie nazwy — nie zależą od języka).
# „Działa” to norma, więc zostaje w kolorze tekstu: kolor ma przyciągać wzrok
# tylko do tego, co wymaga uwagi.
KOLORY_STATUSOW = {
    "dziala": KOLORY["tusz"],
    "uszkodzony": "#A23B2A",
    "w_naprawie": "#A3641E",
    "nietestowany": "#6E6A60",
    "zapasowy": "#3E5A78",
    "na_czesci": "#7D5A6B",
}


def czcionki(korzen: tk.Misc) -> dict[str, tkfont.Font]:
    """Czcionki pochodne od systemowej — tkinter nie wczytuje plików czcionek."""
    baza = tkfont.nametofont("TkDefaultFont", root=korzen)
    rozmiar = abs(baza.cget("size")) or 10
    rodzina = baza.cget("family")
    return {
        "zwykla": baza,
        "pogrubiona": tkfont.Font(root=korzen, family=rodzina, size=rozmiar, weight="bold"),
        "naglowek": tkfont.Font(root=korzen, family=rodzina, size=rozmiar + 5, weight="bold"),
        "maly": tkfont.Font(root=korzen, family=rodzina, size=max(rozmiar - 1, 8)),
    }


def ustaw(korzen: tk.Tk) -> dict[str, tkfont.Font]:
    styl = ttk.Style(korzen)
    # Windows: natywny motyw „vista” wygląda najlepiej; gdzie indziej „clam”
    if sys.platform.startswith("win") and "vista" in styl.theme_names():
        styl.theme_use("vista")
    else:
        styl.theme_use("clam")
        styl.configure(".", background=KOLORY["tlo"], foreground=KOLORY["tusz"])
        styl.configure("TEntry", fieldbackground=KOLORY["panel"])
        styl.configure("TCombobox", fieldbackground=KOLORY["panel"])
        styl.map("TCombobox", fieldbackground=[("readonly", KOLORY["panel"])])
        styl.configure("Treeview", background=KOLORY["panel"], fieldbackground=KOLORY["panel"])
        styl.configure("TNotebook.Tab", padding=(10, 4))
    korzen.configure(background=KOLORY["tlo"])

    # Zaznaczenie tekstu ustawione JAWNIE. Bez tego tkinter bierze kolory z motywu
    # pulpitu (np. KDE) i potrafi dać biały tekst na białym tle — zaznaczona
    # wartość w liście wyboru znika. Szare tło, ciemny tekst — w każdym stanie pola.
    zaznaczenie = [("readonly", "focus", KOLORY["zaznaczenie_tekstu"]),
                   ("readonly", KOLORY["zaznaczenie_tekstu"]),
                   ("focus", KOLORY["zaznaczenie_tekstu"]),
                   ("!focus", KOLORY["zaznaczenie_tekstu"])]
    tekst_zaznaczenia = [(stan[:-1] if len(stan) > 2 else stan[:1]) + (KOLORY["tusz"],)
                         for stan in zaznaczenie]
    for widzet in ("TCombobox", "TEntry", "TSpinbox"):
        styl.configure(widzet, selectbackground=KOLORY["zaznaczenie_tekstu"], selectforeground=KOLORY["tusz"])
        styl.map(widzet, selectbackground=zaznaczenie, selectforeground=tekst_zaznaczenia)
    # Rozwinięta lista wyboru i zwykłe pola tk (Text) korzystają z bazy opcji
    for wzorzec in ("*TCombobox*Listbox", "*Text", "*Listbox", "*Entry"):
        korzen.option_add(f"{wzorzec}.selectBackground", KOLORY["zaznaczenie_tekstu"])
        korzen.option_add(f"{wzorzec}.selectForeground", KOLORY["tusz"])
    korzen.option_add("*TCombobox*Listbox.background", KOLORY["panel"])
    korzen.option_add("*TCombobox*Listbox.foreground", KOLORY["tusz"])

    f = czcionki(korzen)
    wysokosc_wiersza = f["zwykla"].metrics("linespace") + 8
    styl.configure("Treeview", rowheight=wysokosc_wiersza)
    styl.map("Treeview", background=[("selected", KOLORY["zaznaczenie"])],
             foreground=[("selected", KOLORY["tusz"])])
    styl.configure("Naglowek.TLabel", font=f["naglowek"])
    styl.configure("Opis.TLabel", foreground=KOLORY["przygaszony"])
    styl.configure("Ostrzezenie.TLabel", foreground=KOLORY_STATUSOW.get("uszkodzony", "#A23B2A"))
    styl.configure("Maly.TButton", padding=(4, 1))
    styl.configure("Pole.TLabel", foreground=KOLORY["przygaszony"])
    styl.configure("Akcent.TButton", foreground=KOLORY["laminat"], font=f["pogrubiona"])
    styl.configure("Horizontal.TProgressbar", background=KOLORY["laminat"], troughcolor=KOLORY["panel"])
    f["odnosnik"] = tkfont.Font(root=korzen, family=f["zwykla"].cget("family"),
                                size=abs(f["zwykla"].cget("size")) or 10, underline=True)
    styl.configure("Odnosnik.TLabel", foreground=KOLORY["laminat"], font=f["odnosnik"])
    return f
