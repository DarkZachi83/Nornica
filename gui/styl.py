# SPDX-License-Identifier: GPL-3.0-or-later
"""Wygląd programu: motyw jasny i ciemny.

Paleta pochodzi z tematu kolekcji: szaro-beżowa obudowa, zieleń laminatu
płytki drukowanej jako jedyny akcent, ciepły brąz drewnianych regałów
z ilustracji nornicy. Kolory statusów są stonowane, żeby drzewo z setkami
pozycji nie raziło. Motyw ciemny to ta sama paleta „po zgaszeniu światła”:
ciepła grafitowa obudowa, jaśniejsza zieleń i drewno dla kontrastu.

Z ttkbootstrap (jeśli jest) — jego silnik z naszą rodziną motywów „nornica”
(nornica-light / nornica-dark). Bez niego — zwykły ttk („clam”) z tą samą
paletą: brak biblioteki zmienia wygląd przycisków, nie kolory.

Słowniki KOLORY i KOLORY_STATUSOW są zmieniane W MIEJSCU przez ustaw():
moduły, które je zaimportowały, widzą nowe kolory po przebudowie okna —
tak samo jak teksty po zmianie języka. Wzorowane na gui/theme.py programu
AI Bóbr (ten sam autor, ta sama licencja).
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

MOTYWY = ("jasny", "ciemny")
DOMYSLNY_MOTYW = "jasny"
TRYB_BOOTSTRAP = {"jasny": "light", "ciemny": "dark"}

PALETY = {
    "jasny": {
        "tlo": "#E4E1D8",          # obudowa
        "panel": "#F2F0EA",        # pola i listy
        "tusz": "#2A2925",         # tekst
        "przygaszony": "#6E6A60",  # opisy, podpowiedzi
        "wyszarzony": "#8A857A",   # wpisy nieaktywne (pola innej kategorii, puste kontrole)
        "laminat": "#2F6B4F",      # akcent: zieleń PCB
        "drewno": "#7A5636",       # lokalizacje
        "obrys": "#C0BDB5",
        "zaznaczenie": "#CFE0D6",
        "zaznaczenie_tekstu": "#BDB8AC",   # zaznaczony tekst w polach i na listach wyboru
    },
    "ciemny": {
        "tlo": "#26251F",
        "panel": "#2D2C24",
        "tusz": "#E6E2D6",
        "przygaszony": "#A39E92",
        "wyszarzony": "#7E796E",
        "laminat": "#6FBF95",
        "drewno": "#D2A57A",
        "obrys": "#494843",
        "zaznaczenie": "#2F5644",
        "zaznaczenie_tekstu": "#4D4A42",
    },
}

# Kolor tekstu w drzewie według kodu statusu (kody, nie nazwy — nie zależą od języka).
# „Działa” to norma, więc zostaje w kolorze tekstu: kolor ma przyciągać wzrok
# tylko do tego, co wymaga uwagi. Na ciemnym tle — jaśniejsze odcienie.
STATUSY = {
    "jasny": {"uszkodzony": "#A23B2A", "w_naprawie": "#A3641E", "nietestowany": "#6E6A60",
              "zapasowy": "#3E5A78", "na_czesci": "#7D5A6B"},
    "ciemny": {"uszkodzony": "#E07A66", "w_naprawie": "#E0A458", "nietestowany": "#A39E92",
               "zapasowy": "#8DB0D6", "na_czesci": "#C99AB0"},
}

# Ekran powitalny ma stały wygląd — grafika nornicy jest rysowana pod ciemny
# pasek, niezależnie od motywu.
EKRAN_POWITALNY = {"pasek": "#2A2925", "napis": "#F2F0EA", "opis": "#A39E92"}

KOLORY: dict[str, str] = {}
KOLORY_STATUSOW: dict[str, str] = {}
biezacy_motyw = DOMYSLNY_MOTYW


def nazwa_motywu(wartosc) -> str:
    """Motyw z ustawień albo domyślny (stara baza, literówka w pliku)."""
    return wartosc if wartosc in MOTYWY else DOMYSLNY_MOTYW


def _ustaw_palete(motyw: str) -> None:
    global biezacy_motyw
    KOLORY.clear()
    KOLORY.update(PALETY[motyw])
    KOLORY_STATUSOW.clear()
    KOLORY_STATUSOW.update({"dziala": KOLORY["tusz"], **STATUSY[motyw]})
    biezacy_motyw = motyw


_ustaw_palete(DOMYSLNY_MOTYW)


def wlacz_ostrosc_dpi() -> None:
    """Windows ze skalowaniem 125–150%: bez tego okno tkintera jest rozmazane.
    Wołać przed utworzeniem pierwszego okna."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:   # noqa: BLE001 — starszy Windows: wersja z Visty
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:   # noqa: BLE001
            pass


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
        "odnosnik": tkfont.Font(root=korzen, family=rodzina, size=rozmiar, underline=True),
    }


def _rodzina_bootstrap():
    """Rodzina motywów „nornica” dla ttkbootstrap 2.x: akcenty + tło i tekst obu trybów."""
    from ttkbootstrap.style.theme import Theme
    jasny, ciemny = PALETY["jasny"], PALETY["ciemny"]
    return Theme(name="nornica", primary=jasny["laminat"], success=jasny["laminat"],
                 info=STATUSY["jasny"]["zapasowy"], warning=STATUSY["jasny"]["w_naprawie"],
                 danger=STATUSY["jasny"]["uszkodzony"], neutral=jasny["wyszarzony"],
                 light=dict(background=jasny["tlo"], foreground=jasny["tusz"]),
                 dark=dict(background=ciemny["tlo"], foreground=ciemny["tusz"]))


def _styl_bootstrap(korzen: tk.Tk, motyw: str) -> ttk.Style:
    from ttkbootstrap.style import Style
    if Style.instance is not None and Style.instance.master is not korzen:
        Style.instance = None          # styl poprzedniego (zamkniętego) okna — np. w testach
    styl = Style()
    nazwa = f"nornica-{TRYB_BOOTSTRAP[motyw]}"
    if nazwa not in styl.theme_names():
        for definicja in _rodzina_bootstrap().to_definitions():
            styl.register_theme(definicja)
    styl.theme_use(nazwa)
    _rozgrzej_style(korzen)
    return styl


# Widżety, których domyślne style ttkbootstrap buduje dopiero przy pierwszym
# własnym widżecie danego rodzaju. Nornica tworzy zwykłe widżety ttk — bez
# „rozgrzania” przyciski wyboru i pola wyboru zostają w surowym wyglądzie
# (w motywie ciemnym niezaznaczona opcja wyglądała jak zaznaczona).
_WIDZETY_BOOTSTRAP = ("Button", "Checkbutton", "Radiobutton", "Entry", "Combobox", "Spinbox",
                      "Notebook", "Treeview", "Scrollbar", "Progressbar", "Labelframe",
                      "Separator", "Panedwindow", "Label", "Frame", "Menubutton", "Scale")


def _rozgrzej_style(korzen: tk.Tk) -> None:
    import ttkbootstrap
    for nazwa in _WIDZETY_BOOTSTRAP:
        klasa = getattr(ttkbootstrap, nazwa, None)
        if klasa is not None:
            klasa(korzen).destroy()


def _styl_zwykly(korzen: tk.Tk) -> ttk.Style:
    c = KOLORY
    styl = ttk.Style(korzen)
    styl.theme_use("clam")
    styl.configure(".", background=c["tlo"], foreground=c["tusz"], fieldbackground=c["panel"],
                   bordercolor=c["obrys"], lightcolor=c["obrys"], darkcolor=c["obrys"],
                   troughcolor=c["tlo"], insertcolor=c["tusz"], arrowcolor=c["tusz"])
    styl.map(".", foreground=[("disabled", c["wyszarzony"])],
             background=[("active", c["zaznaczenie_tekstu"])])
    styl.configure("TEntry", fieldbackground=c["panel"])
    styl.configure("TCombobox", fieldbackground=c["panel"])
    styl.map("TCombobox", fieldbackground=[("readonly", c["panel"])])
    styl.configure("TNotebook.Tab", background=c["tlo"])
    styl.map("TNotebook.Tab", background=[("selected", c["panel"])])
    styl.configure("TButton", background=c["panel"])
    return styl


def ustaw(korzen: tk.Tk, motyw: str = DOMYSLNY_MOTYW,
          f: dict[str, tkfont.Font] | None = None) -> dict[str, tkfont.Font]:
    """Ustawia motyw (także ponownie, przy przełączeniu) i zwraca czcionki.
    Po zmianie motywu okno trzeba przebudować — widżety biorą kolory przy tworzeniu."""
    motyw = nazwa_motywu(motyw)
    _ustaw_palete(motyw)
    c = KOLORY
    f = f or czcionki(korzen)
    try:
        styl = _styl_bootstrap(korzen, motyw)
    except Exception:   # noqa: BLE001 — brak ttkbootstrap (uruchomienie z kodu) — zwykły ttk
        styl = _styl_zwykly(korzen)
    korzen.configure(background=c["tlo"])
    for okno in korzen.winfo_children():          # otwarte okna podrzędne nie przebudowują tła
        if isinstance(okno, tk.Toplevel):
            okno.configure(background=c["tlo"])

    # Zaznaczenie tekstu ustawione JAWNIE. Bez tego tkinter bierze kolory z motywu
    # pulpitu (np. KDE) i potrafi dać biały tekst na białym tle — zaznaczona
    # wartość w liście wyboru znika.
    zaznaczenie = [("readonly", "focus", c["zaznaczenie_tekstu"]),
                   ("readonly", c["zaznaczenie_tekstu"]),
                   ("focus", c["zaznaczenie_tekstu"]),
                   ("!focus", c["zaznaczenie_tekstu"])]
    tekst_zaznaczenia = [(stan[:-1] if len(stan) > 2 else stan[:1]) + (c["tusz"],)
                         for stan in zaznaczenie]
    for widzet in ("TCombobox", "TEntry", "TSpinbox"):
        # pola jaśniejsze od obudowy (ttkbootstrap w trybie jasnym daje im kolor tła okna)
        styl.configure(widzet, fieldbackground=c["panel"], foreground=c["tusz"],
                       selectbackground=c["zaznaczenie_tekstu"], selectforeground=c["tusz"])
        styl.map(widzet, selectbackground=zaznaczenie, selectforeground=tekst_zaznaczenia)
    _baza_opcji(korzen)

    # Drzewa i tabele: motyw nie ustawia pustej części pod wierszami (fieldbackground).
    styl.configure("Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["tusz"],
                   bordercolor=c["obrys"], lightcolor=c["obrys"], darkcolor=c["obrys"],
                   rowheight=f["zwykla"].metrics("linespace") + 8)
    styl.map("Treeview", background=[("selected", c["zaznaczenie"])],
             foreground=[("selected", c["tusz"])])
    styl.configure("TNotebook.Tab", padding=(10, 4))
    styl.configure("Naglowek.TLabel", font=f["naglowek"])
    styl.configure("Opis.TLabel", foreground=c["przygaszony"])
    styl.configure("Pole.TLabel", foreground=c["przygaszony"])
    styl.configure("Ostrzezenie.TLabel", foreground=KOLORY_STATUSOW["uszkodzony"])
    styl.configure("Odnosnik.TLabel", foreground=c["laminat"], font=f["odnosnik"])
    styl.configure("Maly.TButton", padding=(4, 1))
    styl.configure("Motyw.TButton", padding=(6, 1), font=f["pogrubiona"])
    styl.configure("Akcent.TButton", foreground=c["laminat"], font=f["pogrubiona"])
    styl.configure("Horizontal.TProgressbar", background=c["laminat"], troughcolor=c["panel"],
                   bordercolor=c["obrys"], lightcolor=c["laminat"], darkcolor=c["laminat"])
    return f


def _baza_opcji(korzen: tk.Tk) -> None:
    """Klasyczne widżety tk (menu, pola Text, lista rozwijana) nie biorą stylu ttk.
    Baza opcji działa na widżety tworzone PO jej ustawieniu — stąd przebudowa okna."""
    c = KOLORY
    for wzorzec, wartosc in (
            ("*Toplevel.background", c["tlo"]),
            ("*Menu.background", c["panel"]), ("*Menu.foreground", c["tusz"]),
            ("*Menu.activeBackground", c["zaznaczenie"]), ("*Menu.activeForeground", c["tusz"]),
            ("*Menu.selectColor", c["tusz"]), ("*Menu.disabledForeground", c["wyszarzony"]),
            ("*Text.background", c["panel"]), ("*Text.foreground", c["tusz"]),
            ("*Text.insertBackground", c["tusz"]),
            ("*Listbox.background", c["panel"]), ("*Listbox.foreground", c["tusz"]),
            ("*TCombobox*Listbox.background", c["panel"]), ("*TCombobox*Listbox.foreground", c["tusz"])):
        korzen.option_add(wzorzec, wartosc)
    for wzorzec in ("*TCombobox*Listbox", "*Text", "*Listbox", "*Entry"):
        korzen.option_add(f"{wzorzec}.selectBackground", c["zaznaczenie_tekstu"])
        korzen.option_add(f"{wzorzec}.selectForeground", c["tusz"])


def przelacznik(motyw: str) -> tuple[str, str]:
    """Napis przycisku i motyw, na który przełącza: ☀ w ciemnym (zapal światło), ☾ w jasnym."""
    return ("☀", "jasny") if motyw == "ciemny" else ("☾", "ciemny")
