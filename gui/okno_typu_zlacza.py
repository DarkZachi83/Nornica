# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno dopisania własnego typu złącza (np. „Atari ECI”, „Zasilanie DIN-7”).

Lista typów startowych celowo nie próbuje być kompletna — złączy w retro
sprzęcie jest zbyt wiele. Użytkownik dopisuje brakujące tam, gdzie ich
potrzebuje: w edytorze złączy.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from baza.enumy import opcje
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleWyboru
from i18n.tlumacz import jezyk_biezacy, t
from uslugi import inwentarz


class OknoTypuZlacza(OknoDialogowe):
    def __init__(self, glowne, rodzaj: str | None = None, po_zapisie=None, typ_id: int | None = None):
        super().__init__(glowne)
        self.po_zapisie = po_zapisie
        self.typ_id = typ_id
        nazwy = {}
        if typ_id is not None:                     # edycja: wartości z bazy
            wiersz = self.db.execute("SELECT rodzaj, nazwy FROM zlacze_typ WHERE id = ?", (typ_id,)).fetchone()
            rodzaj, nazwy = wiersz["rodzaj"], json.loads(wiersz["nazwy"])
        self.rodzaj = PoleWyboru(lambda: opcje("zlacze_typ.rodzaj"), rodzaj or "port")
        self.nazwy = {j: tk.StringVar(value=nazwy.get(j, "")) for j in ("pl", "en")}

    def zbuduj_ui(self) -> None:
        self.title(t("okno.typ_zlacza") if self.typ_id is None else t("okno.typ_zlacza_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("pole.rodzaj"), style="Pole.TLabel").grid(row=0, column=0, sticky="w",
                                                                         padx=(0, 10), pady=3)
        self.rodzaj.zbuduj(ramka, width=20).grid(row=0, column=1, sticky="w", pady=3)
        # pole w bieżącym języku jako pierwsze — to je użytkownik wypełni najczęściej
        jezyki = sorted(self.nazwy, key=lambda j: j != jezyk_biezacy())
        for wiersz, jezyk in enumerate(jezyki, 1):
            ttk.Label(ramka, text=t(f"pole.nazwa_{jezyk}"), style="Pole.TLabel").grid(
                row=wiersz, column=0, sticky="w", padx=(0, 10), pady=3)
            pole = ttk.Entry(ramka, textvariable=self.nazwy[jezyk], width=36)
            pole.grid(row=wiersz, column=1, sticky="we", pady=3)
            if wiersz == 1:
                pole.focus_set()
        ttk.Label(ramka, text=t("formularz.nazwa_jednojezyczna"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=3, column=1, sticky="w", pady=(2, 0))
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=4, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self.bind("<Return>", lambda _e: self.zapisz())

    def zapisz(self) -> None:
        try:
            nazwy = {j: v.get() for j, v in self.nazwy.items()}
            if self.typ_id is None:
                typ_id = inwentarz.dodaj_typ_zlacza(self.db, self.rodzaj.wartosc, nazwy)
            else:
                inwentarz.zapisz_typ_zlacza(self.db, self.typ_id, self.rodzaj.wartosc, nazwy)
                typ_id = self.typ_id
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        if self.po_zapisie:
            self.po_zapisie(typ_id)
        self.glowne.odswiez()          # inne otwarte edytory złączy też zobaczą nowy typ
