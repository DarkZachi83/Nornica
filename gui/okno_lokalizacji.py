# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno dodawania i edycji lokalizacji."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from baza.enumy import opcje
from baza.polaczenie import klucz_sortowania
from baza.repozytoria import lokalizacje
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import iid_lokalizacji
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import t
from uslugi import inwentarz


class OknoLokalizacji(OknoDialogowe):
    def __init__(self, glowne, lok_id: int | None, rodzic_id: int | None = None, po_zapisie=None):
        super().__init__(glowne)
        self.lok_id = lok_id
        self.po_zapisie = po_zapisie
        l = lokalizacje.pobierz(self.db, lok_id) if lok_id else None
        wartosc = lambda k, d=None: (l[k] if l is not None and l[k] is not None else d)  # noqa: E731
        self._wykluczone = ({lok_id} | lokalizacje.potomkowie(self.db, lok_id)) if lok_id else set()
        self.nazwa = tk.StringVar(value=wartosc("nazwa", ""))
        self.kod = tk.StringVar(value=wartosc("kod_etykiety", ""))
        self.typ = PoleWyboru(lambda: [(None, "—")] + opcje("lokalizacja.typ"), wartosc("typ"))
        self.rodzic = PoleWyboru(self._opcje_rodzica, wartosc("rodzic_id", rodzic_id))
        self.uwagi = PoleTekstu(wartosc("uwagi", ""))

    def _opcje_rodzica(self):
        sciezki = {k: v for k, v in lokalizacje.sciezki(self.db).items() if k not in self._wykluczone}
        return [(None, t("lokalizacja.najwyzszy_poziom"))] + sorted(
            sciezki.items(), key=lambda p: klucz_sortowania(p[1]))

    def zbuduj_ui(self) -> None:
        self.title(t("okno.lokalizacja_nowa") if self.lok_id is None else t("okno.lokalizacja_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)

        def etykieta(klucz, r):
            ttk.Label(ramka, text=t(klucz), style="Pole.TLabel").grid(row=r, column=0, sticky="w",
                                                                     padx=(0, 10), pady=3)

        etykieta("pole.nazwa", 0)
        pole_nazwy = ttk.Entry(ramka, textvariable=self.nazwa, width=40)
        pole_nazwy.grid(row=0, column=1, sticky="we", pady=3)
        pole_nazwy.focus_set()
        etykieta("pole.typ", 1)
        self.typ.zbuduj(ramka).grid(row=1, column=1, sticky="we", pady=3)
        etykieta("pole.lokalizacja_nadrzedna", 2)
        self.rodzic.zbuduj(ramka, width=40).grid(row=2, column=1, sticky="we", pady=3)
        etykieta("pole.kod_etykiety", 3)
        ttk.Entry(ramka, textvariable=self.kod).grid(row=3, column=1, sticky="we", pady=3)
        ttk.Label(ramka, text=t("formularz.kod_auto"), style="Opis.TLabel").grid(row=4, column=1, sticky="w")
        etykieta("pole.uwagi", 5)
        self.uwagi.zbuduj(ramka, height=4, width=40).grid(row=5, column=1, sticky="nsew", pady=3)
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=6, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self.bind("<Return>", lambda _e: self.zapisz())

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.uwagi.zapamietaj()

    def zapisz(self) -> None:
        try:
            lok_id = inwentarz.zapisz_lokalizacje(self.db, {
                "nazwa": self.nazwa.get(), "typ": self.typ.wartosc, "rodzic_id": self.rodzic.wartosc,
                "kod_etykiety": self.kod.get(), "uwagi": self.uwagi.zapamietaj(),
            }, self.lok_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        self.glowne.odswiez(zaznacz=iid_lokalizacji(lok_id))
        if self.po_zapisie:
            self.po_zapisie(lok_id)
