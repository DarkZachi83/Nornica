# SPDX-License-Identifier: GPL-3.0-or-later
"""Zakładka Historia: testy i naprawy egzemplarza.

Klasa pomocnicza panelu szczegółów (gui/szczegoly.py): korzysta z jego
atrybutów — glowne, db, notatnik, gora, rodzic — i nie działa samodzielnie.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from baza.enumy import etykieta
from baza.repozytoria.szczegoly import zdarzenia
from gui.bazowe import pokaz_blad
from i18n.tlumacz import t


class HistoriaKarty:
    """Lista zdarzeń z menu edycji i usuwania."""

    # -------------------------------------------------------------- historia
    def _historia(self, karta: ttk.Frame, egz_id: int) -> None:
        przyciski = ttk.Frame(karta)
        przyciski.pack(fill="x", pady=(0, 8))
        ttk.Button(przyciski, text=t("akcja.dodaj_test"),
                   command=lambda: self.okno_zdarzenia(egz_id, typ="test")).pack(side="left")
        ttk.Button(przyciski, text=t("akcja.dodaj_naprawe"),
                   command=lambda: self.okno_zdarzenia(egz_id, typ="naprawa")).pack(side="left", padx=(6, 0))
        wpisy = zdarzenia(self.db, egz_id)
        if not wpisy:
            ttk.Label(karta, text=t("pusty.historia"), style="Opis.TLabel").pack(anchor="w")
            return
        lista = ttk.Treeview(karta, columns=("data", "typ", "wynik", "opis"), show="headings", height=8,
                             selectmode="browse")
        for kod, klucz, szerokosc in (("data", "kolumna.data", 90), ("typ", "kolumna.typ", 105),
                                      ("wynik", "kolumna.wynik", 85), ("opis", "kolumna.opis", 200)):
            lista.heading(kod, text=t(klucz), anchor="w")
            lista.column(kod, width=szerokosc, stretch=kod == "opis")
        for z in wpisy:
            rodzaj = (etykieta("zdarzenie.podtyp", z["podtyp"]) if z["podtyp"]
                      else etykieta("zdarzenie.typ", z["typ"]))
            lista.insert("", "end", iid=str(z["id"]), values=(
                z["data"], rodzaj, etykieta("zdarzenie.wynik", z["wynik"]) if z["wynik"] else "",
                (z["opis"] or "").replace("\n", " ")))
        lista.pack(fill="both", expand=True)

        def wybrany():
            wybor = lista.selection()
            return int(wybor[0]) if wybor else None

        def menu(zdarzenie):
            wiersz_ = lista.identify_row(zdarzenie.y)
            if not wiersz_:
                return
            lista.selection_set(wiersz_)
            m = tk.Menu(self.glowne, tearoff=False)
            m.add_command(label=t("akcja.edytuj"),
                          command=lambda: self.okno_zdarzenia(egz_id, zdarzenie_id=int(wiersz_)))
            m.add_command(label=t("akcja.usun"), command=lambda: self._usun_zdarzenie(int(wiersz_)))
            try:
                m.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
            finally:
                m.grab_release()

        lista.bind("<Double-1>", lambda _e: wybrany() and self.okno_zdarzenia(egz_id, zdarzenie_id=wybrany()))
        lista.bind("<Button-3>", menu)
        lista.bind("<Button-2>", menu)

    def okno_zdarzenia(self, egz_id: int, zdarzenie_id: int | None = None, typ: str = "test"):
        from gui.okno_zdarzenia import OknoZdarzenia
        okno = OknoZdarzenia(self.glowne, egz_id, zdarzenie_id, typ)
        okno.pokaz()
        return okno

    def _usun_zdarzenie(self, zdarzenie_id: int) -> None:
        if not messagebox.askyesno(t("okno.potwierdzenie"), t("pytanie.usun_zdarzenie"), parent=self.glowne):
            return
        try:
            from uslugi import inwentarz
            inwentarz.usun_zdarzenie(self.db, zdarzenie_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()
