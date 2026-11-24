# SPDX-License-Identifier: GPL-3.0-or-later
"""Małe okna edycji słowników: kategoria, status, pole parametru, wartości listy.

Otwiera je okno „Słowniki” (gui/okno_slownikow.py). Każde przyjmuje
po_zapisie — wywołanie zwrotne z identyfikatorem zapisanego wpisu.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from baza.enumy import opcje
from baza.repozytoria import slowniki
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import jezyk_biezacy, nazwa, t
from uslugi import slowniki_edycja as edycja


def opcje_typow() -> list[tuple[str, str]]:
    return [(typ, t(f"typ_pola.{typ}")) for typ in edycja.TYPY_POL]


# ---------------------------------------------------------------------------
# Małe okna: nazwy w dwóch językach (wystarczy jeden), plus pola zależne od rodzaju
# ---------------------------------------------------------------------------
class _OknoNazw(OknoDialogowe):
    tytul_nowy = tytul_edycja = ""

    def __init__(self, glowne, ident, nazwy: dict, po_zapisie=None):
        super().__init__(glowne)
        self.ident = ident
        self.po_zapisie = po_zapisie
        self.nazwy = {j: tk.StringVar(value=nazwy.get(j, "")) for j in ("pl", "en")}

    def _pola_nazw(self, ramka: ttk.Frame, od_wiersza: int) -> int:
        jezyki = sorted(self.nazwy, key=lambda j: j != jezyk_biezacy())
        for i, jezyk in enumerate(jezyki):
            ttk.Label(ramka, text=t(f"pole.nazwa_{jezyk}"), style="Pole.TLabel").grid(
                row=od_wiersza + i, column=0, sticky="w", padx=(0, 10), pady=3)
            pole = ttk.Entry(ramka, textvariable=self.nazwy[jezyk], width=36)
            pole.grid(row=od_wiersza + i, column=1, sticky="we", pady=3)
            if i == 0:
                pole.focus_set()
        ttk.Label(ramka, text=t("formularz.nazwa_jednojezyczna"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=od_wiersza + 2, column=1, sticky="w", pady=(2, 0))
        return od_wiersza + 3

    def _zakoncz(self, wynik) -> None:
        self.zamknij()
        if self.po_zapisie:
            self.po_zapisie(wynik)


class OknoKategorii(_OknoNazw):
    def __init__(self, glowne, kat_id, rodzic_id, po_zapisie=None):
        wiersz = slowniki.kategoria(glowne.db, kat_id) if kat_id else None
        super().__init__(glowne, kat_id, json.loads(wiersz["nazwy"]) if wiersz else {}, po_zapisie)
        self.rodzic = PoleWyboru(self._opcje_rodzica, rodzic_id or "")
        self.rodzaj = PoleWyboru(lambda: opcje("kategoria.rodzaj"), wiersz["rodzaj"] if wiersz else "czesc")

    def _opcje_rodzica(self):
        pomin = set()
        if self.ident:                              # nie do własnego wnętrza
            from uslugi.slowniki_edycja import _potomkowie
            pomin = {self.ident, *_potomkowie(self.db, self.ident)}
        return [("", t("slowniki.kategoria_glowna"))] + [
            (k, "    " * g + n) for k, g, n in slowniki.kategorie_plasko(self.db) if k not in pomin]

    def zbuduj_ui(self) -> None:
        self.title(t("okno.kategoria_nowa") if self.ident is None else t("okno.kategoria_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        wiersz = self._pola_nazw(ramka, 0)
        ttk.Label(ramka, text=t("slowniki.nadrzedna"), style="Pole.TLabel").grid(row=wiersz, column=0, sticky="w",
                                                                                padx=(0, 10), pady=3)
        self.rodzic.zbuduj(ramka, width=36).grid(row=wiersz, column=1, sticky="we", pady=3)
        ttk.Label(ramka, text=t("pole.rodzaj"), style="Pole.TLabel").grid(row=wiersz + 1, column=0, sticky="w",
                                                                         padx=(0, 10), pady=3)
        self.rodzaj.zbuduj(ramka, width=24).grid(row=wiersz + 1, column=1, sticky="w", pady=3)
        ttk.Label(ramka, text=t("slowniki.rodzaj_podpowiedz"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=wiersz + 2, column=1, sticky="w")
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz + 3, column=0, columnspan=2, sticky="we", pady=(12, 0))

    def zapisz(self) -> None:
        try:
            kat_id = edycja.zapisz_kategorie(self.db, {"nazwy": {j: v.get() for j, v in self.nazwy.items()},
                                                       "rodzic_id": self.rodzic.wartosc or None,
                                                       "rodzaj": self.rodzaj.wartosc}, self.ident)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(kat_id)


class OknoStatusu(_OknoNazw):
    def __init__(self, glowne, status_id, po_zapisie=None):
        wiersz = slowniki.status(glowne.db, status_id)
        super().__init__(glowne, status_id, json.loads(wiersz["nazwy"]) if wiersz else {}, po_zapisie)

    def zbuduj_ui(self) -> None:
        self.title(t("okno.status_nowy") if self.ident is None else t("okno.status_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        wiersz = self._pola_nazw(ramka, 0)
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self.bind("<Return>", lambda _e: self.zapisz())

    def zapisz(self) -> None:
        try:
            status_id = edycja.zapisz_status(self.db, {j: v.get() for j, v in self.nazwy.items()}, self.ident)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(status_id)


class OknoPola(_OknoNazw):
    def __init__(self, glowne, kat_id: int, kod: str | None, po_zapisie=None):
        pole = next((p for p in slowniki.szablon(glowne.db, kat_id) if p["kod"] == kod), {}) if kod else {}
        super().__init__(glowne, kod, pole.get("nazwy", {}), po_zapisie)
        self.kat_id = kat_id
        self.typ = PoleWyboru(opcje_typow, pole.get("typ", "text"),
                              przy_zmianie=lambda _w: self._pokaz_dodatkowe())
        self._typ_poczatkowy = pole.get("typ")
        self.jednostka = tk.StringVar(value=pole.get("jednostka", ""))
        self.wartosci = PoleTekstu("\n".join(pole.get("wartosci", [])))
        self._jednostka = self._wartosci = None

    def zbuduj_ui(self) -> None:
        self.title(t("okno.pole_nowe") if self.ident is None else t("okno.pole_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        kat = slowniki.kategoria(self.db, self.kat_id)
        ttk.Label(ramka, text=t("slowniki.pole_w_kategorii", kategoria=nazwa(kat["nazwy"])),
                  style="Opis.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        wiersz = self._pola_nazw(ramka, 1)
        ttk.Label(ramka, text=t("slowniki.typ"), style="Pole.TLabel").grid(row=wiersz, column=0, sticky="w",
                                                                          padx=(0, 10), pady=3)
        self.typ.zbuduj(ramka, width=24).grid(row=wiersz, column=1, sticky="w", pady=3)
        if self._typ_poczatkowy == "text":
            ttk.Label(ramka, text=t("slowniki.typ_tekst_lista"), style="Opis.TLabel", wraplength=360,
                      justify="left").grid(row=wiersz, column=2, sticky="w", padx=(8, 0))
        self._jednostka = ttk.Frame(ramka)
        self._jednostka.grid(row=wiersz + 1, column=0, columnspan=2, sticky="we")
        ttk.Label(self._jednostka, text=t("slowniki.jednostka"), style="Pole.TLabel", width=18).pack(side="left")
        ttk.Entry(self._jednostka, textvariable=self.jednostka, width=10).pack(side="left", padx=(4, 0))
        ttk.Label(self._jednostka, text=t("slowniki.jednostka_przyklad"), style="Opis.TLabel").pack(side="left", padx=8)
        self._wartosci = ttk.Frame(ramka)
        self._wartosci.grid(row=wiersz + 2, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        ttk.Label(self._wartosci, text=t("slowniki.wartosci"), style="Pole.TLabel").pack(anchor="w")
        self.wartosci.zbuduj(self._wartosci, height=6, width=40).pack(fill="both", expand=True)
        ramka.columnconfigure(1, weight=1)
        ramka.rowconfigure(wiersz + 2, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz + 3, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self._pokaz_dodatkowe()

    def _pokaz_dodatkowe(self) -> None:
        if self._jednostka is None or not self._jednostka.winfo_exists():
            return
        if self.typ.wartosc in ("int", "real", "zakres"):
            self._jednostka.grid()
        else:
            self._jednostka.grid_remove()
        if self.typ.wartosc == "enum":
            self._wartosci.grid()
        else:
            self._wartosci.grid_remove()

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.wartosci.zapamietaj()

    def zapisz(self) -> None:
        dane = {"nazwy": {j: v.get() for j, v in self.nazwy.items()}, "typ": self.typ.wartosc,
                "jednostka": self.jednostka.get(), "wartosci": self.wartosci.zapamietaj().splitlines()}
        try:
            if self.ident is None:
                kod = edycja.dodaj_pole(self.db, self.kat_id, dane)
            else:
                edycja.zapisz_pole(self.db, self.kat_id, self.ident, dane)
                kod = self.ident
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(kod)


class OknoWartosci(OknoDialogowe):
    """Wartości do wyboru w polu typu „wybór z listy”, np. kolor obudowy z edycją
    limitowaną albo SECAM w „Normie TV”. Przy polu wbudowanym lista wbudowana jest
    tylko do odczytu, a edytuje się dopiski; przy własnym — całą listę."""

    def __init__(self, glowne, kat_id: int, kod: str, po_zapisie=None):
        super().__init__(glowne)
        self.kat_id, self.kod, self.po_zapisie = kat_id, kod, po_zapisie
        self.dane = edycja.wartosci_listy(self.db, kat_id, kod)
        self.wartosci = PoleTekstu("\n".join(self.dane["edytowalne"]))

    def zbuduj_ui(self) -> None:
        self.title(t("okno.wartosci_listy"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=nazwa(self.dane["nazwy"]), style="Naglowek.TLabel").pack(anchor="w")
        if self.dane["kategoria"] != self.kat_id:
            ttk.Label(ramka, text=t("slowniki.z_kategorii", kategoria=nazwa(
                slowniki.kategoria(self.db, self.dane["kategoria"])["nazwy"])), style="Opis.TLabel").pack(anchor="w")
        if self.dane["wbudowane"]:
            ttk.Label(ramka, text=t("slowniki.wartosci_wbudowane", lista=", ".join(self.dane["wbudowane"])),
                      style="Opis.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(ramka, text=t("slowniki.wartosci_twoje" if self.dane["wbudowane"] else "slowniki.wartosci"),
                  style="Pole.TLabel").pack(anchor="w", pady=(10, 0))
        self.wartosci.zbuduj(ramka, height=8, width=40).pack(fill="both", expand=True, pady=(4, 0))
        ttk.Label(ramka, text=t("slowniki.wartosci_podpowiedz"), style="Opis.TLabel", wraplength=420,
                  justify="left").pack(anchor="w", pady=(6, 0))
        self.przyciski(ramka, self.zapisz).pack(fill="x", pady=(12, 0))

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.wartosci.zapamietaj()

    def zapisz(self) -> None:
        try:
            edycja.ustaw_wartosci_wlasne(self.db, self.kat_id, self.kod, self.wartosci.zapamietaj().splitlines())
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        if self.po_zapisie:
            self.po_zapisie(self.kod)
