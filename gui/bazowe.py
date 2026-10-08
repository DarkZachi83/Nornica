# SPDX-License-Identifier: GPL-3.0-or-later
"""Wspólne elementy okien: okno dialogowe z przebudową, komunikaty błędów."""
from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from baza.bledy import komunikat_bledu_bazy
from i18n.tlumacz import t
from wyjatki import BladNornicy


def pokaz_blad(rodzic: tk.Misc, blad: Exception) -> None:
    """Komunikat w bieżącym języku — tekst powstaje teraz, nie przy zgłoszeniu."""
    if isinstance(blad, BladNornicy):
        tekst = blad.komunikat()
    elif isinstance(blad, sqlite3.Error):
        tekst = komunikat_bledu_bazy(blad)
    else:
        tekst = t("blad.nieoczekiwany", szczegoly=str(blad))
    messagebox.showerror(t("okno.blad"), tekst, parent=rodzic)


class OknoDialogowe(tk.Toplevel):
    """Okno podrzędne, które umie się przebudować po zmianie języka.

    Podklasa implementuje zbuduj_ui(). Wszystko, co ma przetrwać przebudowę,
    trzyma w atrybutach (StringVar, PoleWyboru, PoleTekstu). Widżety tworzone
    są wyłącznie w zbuduj_ui() i nie są nigdzie kolekcjonowane poza nim.
    """

    def __init__(self, glowne):
        super().__init__(glowne)
        self.glowne = glowne
        self.db = glowne.db
        self.transient(glowne)
        self.configure(background=glowne.cget("background"))
        self._zakladka = 0
        self._notatnik: ttk.Notebook | None = None
        glowne.zarejestruj(self)
        self.protocol("WM_DELETE_WINDOW", self.zamknij)
        self.bind("<Escape>", lambda _e: self.zamknij())

    # --- do nadpisania ---------------------------------------------------------
    def zbuduj_ui(self) -> None:
        raise NotImplementedError

    def zapamietaj_stan(self) -> None:
        """Przenosi do atrybutów stan, który mieszka w widżetach."""
        if self._notatnik is not None and self._notatnik.winfo_exists():
            self._zakladka = self._notatnik.index("current")

    def przywroc_stan(self) -> None:
        if self._notatnik is not None and self._notatnik.winfo_exists():
            self._notatnik.select(self._zakladka)

    # --- mechanika -------------------------------------------------------------
    def _zbuduj_bezpiecznie(self) -> None:
        """Zawartość okna albo — gdy budowanie przerwie błąd — komunikat z przyciskiem
        „Zamknij”, zamiast pustej ramki skurczonej do kilkudziesięciu pikseli
        (zgłoszenie: okno telefonu po uruchomieniu serwera). Błąd trafia do dziennika.
        W testach (NORNICA_SUROWE_BLEDY) błąd przerywa test — okno awaryjne
        nie może ukrywać zepsutych okien."""
        import os
        try:
            self.zbuduj_ui()
        except Exception as blad:   # noqa: BLE001
            if os.environ.get("NORNICA_SUROWE_BLEDY"):
                raise
            import dziennik
            dziennik.blad(f"Nie udało się zbudować okna {type(self).__name__}")
            for dziecko in self.winfo_children():
                dziecko.destroy()
            self._notatnik = None
            ramka = ttk.Frame(self, padding=20)
            ramka.pack(fill="both", expand=True)
            ttk.Label(ramka, text=t("blad.okno_nie_zbudowane", opis=f"{type(blad).__name__}: {blad}",
                                    plik=str(dziennik.plik() or "—")),
                      wraplength=420, justify="left").pack(anchor="w")
            ttk.Button(ramka, text=t("przycisk.zamknij"), command=self.zamknij).pack(anchor="e", pady=(16, 0))

    def pokaz(self) -> None:
        self._zbuduj_bezpiecznie()
        self.przywroc_stan()
        self.update_idletasks()
        x = self.glowne.winfo_rootx() + 60
        y = self.glowne.winfo_rooty() + 40
        self.geometry(f"+{x}+{y}")

    def przebuduj(self) -> None:
        self.zapamietaj_stan()
        for dziecko in self.winfo_children():
            dziecko.destroy()
        self._notatnik = None
        self._zbuduj_bezpiecznie()
        self.przywroc_stan()

    def dane_zmienione(self) -> None:
        """Wołane przez okno główne po każdej zmianie danych. Listy wyboru
        liczą opcje od nowa — lokalizacja założona w innym oknie pojawia się
        w otwartym formularzu. Wybrana wartość zostaje, chyba że zniknęła z bazy."""
        from gui.pola import PoleWyboru
        for pole in list(vars(self).values()):
            if isinstance(pole, PoleWyboru):
                pole.odswiez_opcje()
            elif hasattr(pole, "dane_zmienione") and not isinstance(pole, tk.Misc):
                pole.dane_zmienione()          # złożone edytory (np. złączy) odświeżają się same

    def zamknij(self) -> None:
        self.glowne.wyrejestruj(self)
        self.destroy()

    def przyciski(self, rodzic: tk.Misc, zapisz) -> ttk.Frame:
        ramka = ttk.Frame(rodzic)
        ttk.Button(ramka, text=t("przycisk.anuluj"), command=self.zamknij).pack(side="right")
        ttk.Button(ramka, text=t("przycisk.zapisz"), style="Akcent.TButton",
                   command=zapisz).pack(side="right", padx=(0, 8))
        self.bind("<Control-s>", lambda _e: zapisz())
        return ramka
