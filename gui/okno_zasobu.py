# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno opisu zasobu: dodawanie pliku, odnośnika lub notatki oraz edycja opisu.

„Podepnij do” decyduje, gdzie zasób będzie widoczny: tylko przy tym
egzemplarzu, przy wszystkich egzemplarzach modelu (instrukcja, sterownik)
albo przy całej kategorii (ogólny poradnik).
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from baza.enumy import opcje
from baza.repozytoria import egzemplarze, modele
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import nazwa, t
from uslugi import pliki

_TYP_PO_ROZSZERZENIU = {".pdf": "instrukcja", ".rom": "rom", ".bin": "rom",
                        ".zip": "sterownik", ".lzh": "sterownik", ".exe": "sterownik",
                        ".adf": "sterownik", ".img": "sterownik", ".txt": "dokumentacja"}


class OknoZasobu(OknoDialogowe):
    """tryb: 'plik' | 'link' | 'notatka' | 'edycja'."""

    def __init__(self, glowne, egz_id: int, tryb: str, sciezka: str | None = None,
                 zasob_id: int | None = None):
        super().__init__(glowne)
        self.egz_id = egz_id
        self.tryb = tryb
        self.sciezka = sciezka
        self.zasob_id = zasob_id
        z = self.db.execute("SELECT * FROM zasob WHERE id = ?", (zasob_id,)).fetchone() if zasob_id else None
        self._zasob = z
        if z is not None:
            typ, tytul = z["typ"], z["tytul"]
        elif tryb == "plik":
            rozszerzenie = Path(sciezka).suffix.lower()
            typ = "zdjecie" if pliki.czy_zdjecie(sciezka) else _TYP_PO_ROZSZERZENIU.get(rozszerzenie, "dokumentacja")
            tytul = Path(sciezka).stem
        else:
            typ, tytul = ("link", "") if tryb == "link" else ("notatka", "")
        self.typ = PoleWyboru(lambda: opcje("zasob.typ"), typ)
        self.tytul = tk.StringVar(value=tytul)
        self.wersja = tk.StringVar(value=(z["wersja"] if z is not None and z["wersja"] else ""))
        self.url = tk.StringVar(value=(z["url"] if z is not None and z["url"] else ""))
        self.tresc = PoleTekstu(z["tresc"] if z is not None else "")
        e = egzemplarze.pobierz(self.db, egz_id)
        self._model_id, self._kat_id = e["model_id"], e["kat_id"]
        domyslny_cel = ("model" if self._model_id and typ not in ("zdjecie", "notatka")
                        else "egzemplarz")
        self.cel = PoleWyboru(self._opcje_celu, domyslny_cel)

    def _opcje_celu(self):
        wynik = [("egzemplarz", t("cel.egzemplarz"))]
        if self._model_id:
            wynik.append(("model", t("cel.model", nazwa=modele.etykieta(modele.pobierz(self.db, self._model_id)))))
        if self._kat_id:
            kat = self.db.execute("SELECT nazwy FROM kategoria WHERE id = ?", (self._kat_id,)).fetchone()
            wynik.append(("kategoria", t("cel.kategoria", nazwa=nazwa(kat["nazwy"]))))
        return wynik

    def _cel(self) -> dict:
        return {"egzemplarz": {"egzemplarz_id": self.egz_id}, "model": {"model_id": self._model_id},
                "kategoria": {"kategoria_id": self._kat_id}}[self.cel.wartosc or "egzemplarz"]

    def _pokazuj_url(self) -> bool:
        return self.tryb == "link" or (self.tryb == "edycja" and not self._zasob["plik_sciezka"]
                                       and self._zasob["typ"] != "notatka")

    def _pokazuj_tresc(self) -> bool:
        return self.tryb == "notatka" or (self.tryb == "edycja" and self._zasob["typ"] == "notatka")

    def zbuduj_ui(self) -> None:
        tytuly = {"plik": "okno.zasob_plik", "link": "okno.zasob_link",
                  "notatka": "okno.zasob_notatka", "edycja": "okno.zasob_edycja"}
        self.title(t(tytuly[self.tryb]))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        wiersz = 0

        def etykieta(klucz):
            ttk.Label(ramka, text=t(klucz), style="Pole.TLabel").grid(
                row=wiersz, column=0, sticky="nw", padx=(0, 10), pady=3)

        sciezka = self.sciezka or (self._zasob["plik_sciezka"] if self._zasob is not None else None)
        if sciezka:
            etykieta("pole.plik")
            ttk.Label(ramka, text=Path(sciezka).name, wraplength=360).grid(row=wiersz, column=1, sticky="w")
            wiersz += 1
        etykieta("pole.typ")
        self.typ.zbuduj(ramka, width=30).grid(row=wiersz, column=1, sticky="we", pady=3)
        wiersz += 1
        etykieta("pole.tytul")
        pole = ttk.Entry(ramka, textvariable=self.tytul, width=44)
        pole.grid(row=wiersz, column=1, sticky="we", pady=3)
        pole.focus_set()
        wiersz += 1
        etykieta("pole.wersja")
        ttk.Entry(ramka, textvariable=self.wersja, width=20).grid(row=wiersz, column=1, sticky="w", pady=3)
        wiersz += 1
        if self._pokazuj_url():
            etykieta("pole.url")
            ttk.Entry(ramka, textvariable=self.url).grid(row=wiersz, column=1, sticky="we", pady=3)
            wiersz += 1
        if self._pokazuj_tresc():
            etykieta("pole.tresc")
            self.tresc.zbuduj(ramka, height=8, width=50).grid(row=wiersz, column=1, sticky="nsew", pady=3)
            ramka.rowconfigure(wiersz, weight=1)
            wiersz += 1
        if self.tryb != "edycja":
            etykieta("pole.podepnij_do")
            self.cel.zbuduj(ramka, width=44).grid(row=wiersz, column=1, sticky="we", pady=3)
            wiersz += 1
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz, column=0, columnspan=2, sticky="we", pady=(12, 0))

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.tresc.zapamietaj()

    def zapisz(self) -> None:
        dane = {"typ": self.typ.wartosc or "dokumentacja", "tytul": self.tytul.get(),
                "wersja": self.wersja.get()}
        if self._pokazuj_url():
            dane["url"] = self.url.get()
        if self._pokazuj_tresc():
            dane["tresc"] = self.tresc.zapamietaj()
        try:
            if self.tryb == "plik":
                pliki.dodaj_plik(self.db, self.sciezka, self._cel(), dane["typ"], dane["tytul"], dane["wersja"])
            elif self.tryb == "edycja":
                pliki.zapisz_zasob(self.db, self.zasob_id, dane)
            else:
                pliki.dodaj_zasob(self.db, dane, self._cel())
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        self.glowne.odswiez()
