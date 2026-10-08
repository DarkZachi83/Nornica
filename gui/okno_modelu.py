# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno dodawania i edycji modelu (katalog: „co to jest”).

W etapie 4 to samo okno przyjmie dane zaimportowane z The Retro Web
do przejrzenia i poprawienia przed zapisem.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from baza.repozytoria import modele, slowniki
from baza.repozytoria import zlacza as repo_zlaczy
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import FormularzAtrybutow, PoleTekstu, PoleWyboru
from gui.zlacza import EdytorZlaczy
from i18n.tlumacz import t
from uslugi import inwentarz
from wyjatki import BladNornicy

POLA = ("nazwa", "numer_czesci", "rok_od", "rok_do", "zrodlo_url")


class OknoModelu(OknoDialogowe):
    def __init__(self, glowne, model_id: int | None, kategoria_id: int | None = None,
                 po_zapisie=None):
        super().__init__(glowne)
        self.model_id = model_id
        self.po_zapisie = po_zapisie
        m = modele.pobierz(self.db, model_id) if model_id else None
        wartosc = lambda k, d="": (m[k] if m is not None and m[k] is not None else d)  # noqa: E731
        self.v = {k: tk.StringVar(value=str(wartosc(k))) for k in POLA}
        self.producent = tk.StringVar(value=wartosc("producent"))
        self.kategoria = PoleWyboru(self._opcje_kategorii, wartosc("kategoria_id", kategoria_id),
                                    przy_zmianie=lambda _w: self._zbuduj_parametry())
        self.opis = PoleTekstu(wartosc("opis"))
        self.atrybuty = FormularzAtrybutow(json.loads(wartosc("atrybuty", "{}")))
        self.zlacza = EdytorZlaczy(self.db, repo_zlaczy.modelu(self.db, model_id), glowne=glowne)

    def _opcje_kategorii(self):
        return [(kid, "    " * g + n) for kid, g, n in slowniki.kategorie_plasko(self.db)]

    def zbuduj_ui(self) -> None:
        self.title(t("okno.model_nowy") if self.model_id is None else t("okno.model_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        self._notatnik = ttk.Notebook(ramka)
        self._notatnik.pack(fill="both", expand=True)

        ogolne = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(ogolne, text=t("zakladka.ogolne"))

        def etykieta(klucz, r):
            ttk.Label(ogolne, text=t(klucz), style="Pole.TLabel").grid(row=r, column=0, sticky="w",
                                                                      padx=(0, 10), pady=3)

        etykieta("pole.kategoria", 0)
        self.kategoria.zbuduj(ogolne, width=40).grid(row=0, column=1, sticky="we", pady=3)
        etykieta("pole.producent", 1)
        ttk.Combobox(ogolne, textvariable=self.producent,
                     values=[p["nazwa"] for p in slowniki.producenci(self.db)]).grid(
            row=1, column=1, sticky="we", pady=3)
        ttk.Label(ogolne, text=t("formularz.producent_nowy"), style="Opis.TLabel").grid(
            row=2, column=1, sticky="w")
        for r, (klucz, pole) in enumerate((("pole.nazwa_modelu", "nazwa"),
                                           ("pole.numer_czesci", "numer_czesci"),
                                           ("pole.rok_od", "rok_od"), ("pole.rok_do", "rok_do"),
                                           ("pole.zrodlo_url", "zrodlo_url")), 3):
            etykieta(klucz, r)
            if pole == "zrodlo_url":               # pole adresu + przycisk w jednej kolumnie
                wiersz = ttk.Frame(ogolne)
                wiersz.grid(row=r, column=1, sticky="we", pady=3)
                ttk.Button(wiersz, text=t("trw.przycisk"), command=self.retroweb).pack(side="right", padx=(6, 0))
                ttk.Entry(wiersz, textvariable=self.v[pole]).pack(side="left", fill="x", expand=True)
            else:
                ttk.Entry(ogolne, textvariable=self.v[pole]).grid(row=r, column=1, sticky="we", pady=3)
        etykieta("pole.opis", 8)
        self.opis.zbuduj(ogolne, height=8, width=60).grid(row=8, column=1, sticky="nsew", pady=3)
        ogolne.columnconfigure(1, weight=1)
        ogolne.rowconfigure(8, weight=1)       # opis rośnie razem z oknem

        self._parametry = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(self._parametry, text=t("zakladka.parametry"))
        self._zbuduj_parametry()

        karta_zlaczy = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(karta_zlaczy, text=t("zakladka.zlacza"))
        self.zlacza.zbuduj(karta_zlaczy)
        self.przyciski(ramka, self.zapisz).pack(fill="x", pady=(12, 0))

    def retroweb(self):
        from gui.okno_retroweb import OknoRetroWeb
        okno = OknoRetroWeb(self.glowne, self.v["zrodlo_url"].get(), self.producent.get(), self.v["nazwa"].get(),
                            po_zastosowaniu=self.zastosuj_retroweb)
        okno.pokaz()
        return okno

    def zastosuj_retroweb(self, p, nadpisz: bool = False) -> None:
        """Dane z The Retro Web do FORMULARZA (zapis dopiero przyciskiem „Zapisz”).
        Puste pola są uzupełniane; wypełnione zostają, chyba że nadpisz=True.
        Źródło i licencja zawsze trafiają do opisu — to warunek CC BY-SA."""
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = ?", (p.kategoria_kod,)).fetchone()
        if kat and (nadpisz or not self.kategoria.wartosc):
            self.kategoria.ustaw(kat["id"])
            self._zbuduj_parametry()
        for zmienna, wartosc in ((self.producent, p.producent), (self.v["nazwa"], p.nazwa),
                                 (self.v["rok_od"], p.rok_od), (self.v["zrodlo_url"], p.zrodlo_url)):
            if wartosc and (nadpisz or not zmienna.get().strip()):
                zmienna.set(str(wartosc))
        self.atrybuty.wstaw(slowniki.szablon(self.db, self.kategoria.wartosc), p.atrybuty, nadpisz)
        self.zlacza.wstaw(p.zlacza, nadpisz)
        opis = self.opis.zapamietaj().rstrip()
        zrodlo = p.opis.splitlines()[0]
        if zrodlo not in opis:                     # ponowny import nie dubluje dopisku
            self.opis.ustaw(f"{opis}\n\n{p.opis}" if opis else p.opis)

    def _zbuduj_parametry(self) -> None:
        if hasattr(self, "_parametry") and self._parametry.winfo_exists():
            self.atrybuty.zbuduj(self._parametry, slowniki.szablon(self.db, self.kategoria.wartosc))

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.opis.zapamietaj()

    def _rok(self, pole: str) -> int | None:
        tekst = self.v[pole].get().strip()
        if not tekst:
            return None
        try:
            return int(tekst)
        except ValueError:
            raise BladNornicy("blad.wartosc_liczbowa",
                              pole=t("pole.rok_od" if pole == "rok_od" else "pole.rok_do")) from None

    def zapisz(self) -> None:
        try:
            dane = {
                "kategoria_id": self.kategoria.wartosc,
                "producent": self.producent.get(),
                "nazwa": self.v["nazwa"].get(),
                "numer_czesci": self.v["numer_czesci"].get(),
                "rok_od": self._rok("rok_od"),
                "rok_do": self._rok("rok_do"),
                "zrodlo_url": self.v["zrodlo_url"].get(),
                "opis": self.opis.zapamietaj(),
                "atrybuty": self.atrybuty.zbierz(slowniki.szablon(self.db, self.kategoria.wartosc)),
                "zlacza": self.zlacza.wynik(),
            }
            model_id = inwentarz.zapisz_model(self.db, dane, self.model_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        if self.po_zapisie:
            self.po_zapisie(model_id)
        self.zamknij()
