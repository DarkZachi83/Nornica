# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno testu lub naprawy.

Po wybraniu wyniku okno proponuje zmianę statusu egzemplarza (test nieudany
-> „Uszkodzony”, udana naprawa -> „Działa”). To tylko propozycja: można ją
zmienić albo wybrać „bez zmiany”. Zapis zdarzenia i statusu to jedna operacja.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from baza.enumy import opcje
from baza.repozytoria import egzemplarze, slowniki
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import nazwa, t
from uslugi import inwentarz

# (typ, wynik) -> kod proponowanego statusu
PROPOZYCJE_STATUSU = {
    ("test", "ok"): "dziala",
    ("test", "blad"): "uszkodzony",
    ("naprawa", "ok"): "dziala",
    ("naprawa", "blad"): "w_naprawie",
}


class OknoZdarzenia(OknoDialogowe):
    def __init__(self, glowne, egz_id: int, zdarzenie_id: int | None = None, typ: str = "test"):
        super().__init__(glowne)
        self.egz_id = egz_id
        self.zdarzenie_id = zdarzenie_id
        z = self.db.execute("SELECT * FROM zdarzenie WHERE id = ?", (zdarzenie_id,)).fetchone() \
            if zdarzenie_id else None
        self.typ = tk.StringVar(value=z["typ"] if z is not None else typ)
        self.podtyp = PoleWyboru(lambda: opcje("zdarzenie.podtyp"),
                                 (z["podtyp"] if z is not None else None) or "naprawa")
        self.wynik = PoleWyboru(lambda: [(None, "—")] + opcje("zdarzenie.wynik"),
                                z["wynik"] if z is not None else None,
                                przy_zmianie=lambda _w: self._zaproponuj_status())
        self.data = tk.StringVar(value=z["data"] if z is not None else date.today().isoformat())
        self.opis = PoleTekstu(z["opis"] if z is not None else "")
        self.nowy_status = PoleWyboru(self._opcje_statusu, None)
        self._status_biezacy = egzemplarze.pobierz(self.db, egz_id)["status_id"]
        self._podtyp_widzet: ttk.Combobox | None = None

    def _opcje_statusu(self):
        return [(None, t("zdarzenie.bez_zmiany_statusu"))] + [
            (s["id"], nazwa(s["nazwy"])) for s in slowniki.statusy(self.db)]

    def _zaproponuj_status(self) -> None:
        kod = PROPOZYCJE_STATUSU.get((self.typ.get(), self.wynik.wartosc))
        status_id = slowniki.status_id(self.db, kod) if kod else None
        self.nowy_status.ustaw(status_id if status_id != self._status_biezacy else None)

    def _typ_zmieniony(self) -> None:
        if self._podtyp_widzet is not None and self._podtyp_widzet.winfo_exists():
            self._podtyp_widzet.configure(state="readonly" if self.typ.get() == "naprawa" else "disabled")
        self._zaproponuj_status()

    def zbuduj_ui(self) -> None:
        e = egzemplarze.pobierz(self.db, self.egz_id)
        self.title(t("okno.zdarzenie_nowe") if self.zdarzenie_id is None else t("okno.zdarzenie_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=egzemplarze.nazwa_wyswietlana(e), style="Naglowek.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        def etykieta(klucz, r):
            ttk.Label(ramka, text=t(klucz), style="Pole.TLabel").grid(row=r, column=0, sticky="nw",
                                                                     padx=(0, 10), pady=3)

        etykieta("pole.rodzaj_zdarzenia", 1)
        wybor = ttk.Frame(ramka)
        wybor.grid(row=1, column=1, columnspan=2, sticky="w")
        for wartosc, opis in opcje("zdarzenie.typ"):
            ttk.Radiobutton(wybor, text=opis, value=wartosc, variable=self.typ,
                            command=self._typ_zmieniony).pack(side="left", padx=(0, 12))
        etykieta("pole.podtyp", 2)
        self._podtyp_widzet = self.podtyp.zbuduj(ramka, width=20)
        self._podtyp_widzet.grid(row=2, column=1, sticky="w", pady=3)
        etykieta("pole.data", 3)
        ttk.Entry(ramka, textvariable=self.data, width=14).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(ramka, text=t("formularz.format_daty"), style="Opis.TLabel").grid(row=3, column=2, sticky="w")
        etykieta("pole.wynik", 4)
        self.wynik.zbuduj(ramka, width=20).grid(row=4, column=1, sticky="w", pady=3)
        etykieta("pole.opis", 5)
        self.opis.zbuduj(ramka, height=7, width=54).grid(row=5, column=1, columnspan=2, sticky="nsew", pady=3)
        etykieta("pole.zmien_status", 6)
        self.nowy_status.zbuduj(ramka, width=24).grid(row=6, column=1, columnspan=2, sticky="w", pady=3)
        ramka.columnconfigure(2, weight=1)
        ramka.rowconfigure(5, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=7, column=0, columnspan=3, sticky="we", pady=(12, 0))
        self._typ_zmieniony_bez_propozycji()

    def _typ_zmieniony_bez_propozycji(self) -> None:
        self._podtyp_widzet.configure(state="readonly" if self.typ.get() == "naprawa" else "disabled")

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.opis.zapamietaj()

    def zapisz(self) -> None:
        try:
            inwentarz.zapisz_zdarzenie(self.db, {
                "egzemplarz_id": self.egz_id, "typ": self.typ.get(), "podtyp": self.podtyp.wartosc,
                "data": self.data.get(), "wynik": self.wynik.wartosc, "opis": self.opis.zapamietaj(),
            }, self.zdarzenie_id, self.nowy_status.wartosc)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        self.glowne.odswiez()
