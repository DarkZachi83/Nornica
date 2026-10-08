# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Przenieś do innej kategorii”: wybór kategorii i podgląd, co stanie
się z parametrami — zanim cokolwiek się zmieni."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from baza.repozytoria import egzemplarze, slowniki
from gui import styl
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleWyboru
from i18n.tlumacz import nazwa, t
from uslugi import przeniesienie


class OknoPrzeniesienia(OknoDialogowe):
    def __init__(self, glowne, model_id: int | None = None, egz_id: int | None = None,
                 kategoria_id: int | None = None, po_przeniesieniu=None):
        super().__init__(glowne)
        self.model_id, self.egz_id = model_id, egz_id
        self.po_przeniesieniu = po_przeniesieniu
        self.cel = PoleWyboru(self._opcje, kategoria_id, przy_zmianie=lambda _w: self._odswiez_podglad())
        self._podglad: tk.Text | None = None
        self._przycisk: ttk.Button | None = None

    def _opcje(self):
        return [(k, "    " * glebokosc + nazwa_) for k, glebokosc, nazwa_ in slowniki.kategorie_plasko(self.db)]

    def _opis_obiektu(self) -> str:
        if self.model_id is not None:
            m = self.db.execute("SELECT m.nazwa, p.nazwa AS producent FROM model m "
                                "LEFT JOIN producent p ON p.id = m.producent_id WHERE m.id = ?",
                                (self.model_id,)).fetchone()
            liczba = self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE model_id = ?",
                                     (self.model_id,)).fetchone()[0]
            return t("przenies.model", nazwa=" ".join(c for c in (m["producent"], m["nazwa"]) if c), liczba=liczba)
        return t("przenies.egzemplarz", nazwa=egzemplarze.nazwa_wyswietlana(egzemplarze.pobierz(self.db, self.egz_id)))

    def zbuduj_ui(self) -> None:
        self.title(t("okno.przenies"))
        ramka = ttk.Frame(self, padding=16)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=self._opis_obiektu(), wraplength=480, justify="left").pack(anchor="w")
        obecna, _ = przeniesienie._wpisy(self.db, self.model_id, self.egz_id)
        kategoria = self.db.execute("SELECT nazwy FROM kategoria WHERE id = ?", (obecna,)).fetchone()
        ttk.Label(ramka, text=t("przenies.obecna", kategoria=nazwa(kategoria["nazwy"])),
                  style="Opis.TLabel").pack(anchor="w", pady=(6, 0))
        wybor = ttk.Frame(ramka)
        wybor.pack(fill="x", pady=(12, 0))
        ttk.Label(wybor, text=t("przenies.nowa"), style="Pole.TLabel").pack(side="left")
        self.cel.zbuduj(wybor, width=36).pack(side="left", padx=(8, 0), fill="x", expand=True)
        self._podglad = tk.Text(ramka, height=12, width=64, wrap="word", relief="flat", borderwidth=0,
                                highlightthickness=0, background=styl.KOLORY["panel"], padx=10, pady=8,
                                font=self.glowne.czcionki["zwykla"])
        self._podglad.pack(fill="both", expand=True, pady=(12, 0))
        self._podglad.tag_configure("naglowek", font=self.glowne.czcionki["pogrubiona"], spacing1=4)
        self._podglad.tag_configure("usuwane", foreground=styl.KOLORY_STATUSOW["uszkodzony"])
        ttk.Label(ramka, text=t("przenies.bez_zmian"), style="Opis.TLabel", wraplength=480,
                  justify="left").pack(anchor="w", pady=(8, 0))
        przyciski = ttk.Frame(ramka)
        przyciski.pack(fill="x", pady=(14, 0))
        ttk.Button(przyciski, text=t("przycisk.anuluj"), command=self.zamknij).pack(side="right")
        self._przycisk = ttk.Button(przyciski, text=t("przenies.przenies"), style="Akcent.TButton",
                                    command=self.przenies)
        self._przycisk.pack(side="right", padx=(0, 8))
        self._odswiez_podglad()

    def _odswiez_podglad(self) -> None:
        if self._podglad is None or not self._podglad.winfo_exists():
            return
        tekst = self._podglad
        tekst.configure(state="normal")
        tekst.delete("1.0", "end")
        obecna, _ = przeniesienie._wpisy(self.db, self.model_id, self.egz_id)
        if not self.cel.wartosc or self.cel.wartosc == obecna:
            tekst.insert("end", t("przenies.wybierz"))
            self._przycisk.configure(state="disabled")
        else:
            p = przeniesienie.podglad(self.db, self.cel.wartosc, self.model_id, self.egz_id)
            if self.model_id is not None and p["egzemplarzy"]:
                tekst.insert("end", t("przenies.razem_z", liczba=p["egzemplarzy"]) + "\n")
            for klucz, tag in (("zachowane", ""), ("do_sprawdzenia", ""), ("usuwane", "usuwane")):
                if p[klucz]:
                    tekst.insert("end", t(f"przenies.{klucz}") + "\n", ("naglowek",))
                    for pozycja in p[klucz]:
                        tekst.insert("end", f"  • {pozycja['etykieta']}: {pozycja['wartosci']}\n", (tag,))
            if not (p["zachowane"] or p["do_sprawdzenia"] or p["usuwane"]):
                tekst.insert("end", t("przenies.brak_parametrow"))
            self._przycisk.configure(state="normal")
        tekst.configure(state="disabled")

    def przenies(self) -> None:
        try:
            przeniesienie.przenies(self.db, self.cel.wartosc, self.model_id, self.egz_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        if self.po_przeniesieniu:
            self.po_przeniesieniu(self.cel.wartosc)   # PRZED odświeżeniem: formularz egzemplarza ustawia kategorię
        self.glowne.odswiez()
        self.zamknij()
