# SPDX-License-Identifier: GPL-3.0-or-later
"""Ekran powitalny i okno „O programie” — jedyne miejsca, gdzie nornica
gra pierwsze skrzypce."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import konfiguracja
from gui import styl
from gui.bazowe import OknoDialogowe
from i18n.tlumacz import t
from wersja import AUTOR, LICENCJA, ROK, WERSJA

CZAS_POWITANIA_MS = 1600


class EkranPowitalny(tk.Toplevel):
    """Krótkie okno bez ramki. Kliknięcie zamyka je od razu."""

    def __init__(self, glowne, po_zamknieciu):
        super().__init__(glowne)
        self.po_zamknieciu = po_zamknieciu
        obraz = glowne.grafika("powitanie")
        if obraz is None:            # brak grafiki — od razu do programu
            self.after_idle(self.zamknij)
            return
        self.overrideredirect(True)
        self.configure(background=styl.KOLORY["tusz"])
        # Mały ekran (np. netbook 1024×600): obraz w połowie rozmiaru, żeby
        # ekran powitalny nie wychodził poza krawędzie.
        if (obraz.width() > self.winfo_screenwidth() * 0.9
                or obraz.height() + 60 > self.winfo_screenheight() * 0.9):
            obraz = obraz.subsample(2)
            self._pomniejszony = obraz          # referencja: inaczej tkinter zgubi obraz
        tk.Label(self, image=obraz, borderwidth=0).pack()
        pasek = tk.Frame(self, background=styl.KOLORY["tusz"], padx=18, pady=12)
        pasek.pack(fill="x")
        tk.Label(pasek, text=t("aplikacja.nazwa"), font=glowne.czcionki["naglowek"],
                 foreground=styl.KOLORY["panel"], background=styl.KOLORY["tusz"]).pack(side="left")
        tk.Label(pasek, text=t("aplikacja.opis"), foreground=styl.KOLORY["przygaszony"],
                 background=styl.KOLORY["tusz"]).pack(side="left", padx=(14, 0), pady=(6, 0))
        tk.Label(pasek, text=WERSJA, foreground=styl.KOLORY["przygaszony"],
                 background=styl.KOLORY["tusz"]).pack(side="right", pady=(6, 0))
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2
        y = (self.winfo_screenheight() - self.winfo_reqheight()) // 2
        self.geometry(f"+{x}+{y}")
        self.bind("<Button-1>", lambda _e: self.zamknij())
        self.after(CZAS_POWITANIA_MS, self.zamknij)

    def zamknij(self) -> None:
        if self.winfo_exists():
            self.destroy()
            self.po_zamknieciu()


class OknoOProgramie(OknoDialogowe):
    def zbuduj_ui(self) -> None:
        self.title(t("akcja.o_programie"))
        self.resizable(False, False)
        ramka = ttk.Frame(self, padding=20)
        ramka.pack(fill="both", expand=True)
        ikona = self.glowne.grafika("ikona_duza")
        if ikona is not None:
            ttk.Label(ramka, image=ikona).grid(row=0, column=0, rowspan=7, sticky="n", padx=(0, 20))
        ttk.Label(ramka, text=t("aplikacja.nazwa"), style="Naglowek.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(ramka, text=t("aplikacja.opis")).grid(row=1, column=1, sticky="w")
        ttk.Label(ramka, text=t("info.wersja", wersja=WERSJA), style="Opis.TLabel").grid(
            row=2, column=1, sticky="w", pady=(10, 0))
        ttk.Label(ramka, text=t("info.dane", sciezka=konfiguracja.katalog_danych()),
                  style="Opis.TLabel", wraplength=360, justify="left").grid(row=3, column=1, sticky="w")
        # Notka zalecana przez GPL dla programów interaktywnych: licencja i brak gwarancji
        ttk.Label(ramka, text=t("info.licencja", rok=ROK, autor=AUTOR, licencja=LICENCJA),
                  wraplength=360, justify="left").grid(row=4, column=1, sticky="w", pady=(12, 0))
        ttk.Label(ramka, text=t("info.gwarancja"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=5, column=1, sticky="w", pady=(4, 0))
        przyciski = ttk.Frame(ramka)
        przyciski.grid(row=6, column=1, sticky="e", pady=(16, 0))
        ttk.Button(przyciski, text=t("info.pokaz_licencje"), command=self._licencja).pack(side="left", padx=(0, 8))
        ttk.Button(przyciski, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="left")

    def _licencja(self) -> None:
        from gui.bazowe import pokaz_blad
        from uslugi import pliki
        try:
            pliki.otworz(konfiguracja.KATALOG_PROGRAMU / "LICENSE")
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
