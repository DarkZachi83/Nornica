# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno eksportu danych: zakres, tabele, formaty, język raportu, dane prywatne.

Wybór formatów i tabel jest zapamiętywany. Dane prywatne są zawsze domyślnie
wyłączone — świadomie włączane przy każdym eksporcie, żeby raport wysłany
innemu kolekcjonerowi nie zdradzał cen przez przypadek.
"""
from __future__ import annotations

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk

from baza.repozytoria import egzemplarze, lokalizacje, ustawienia
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import rozbierz_iid
from gui.pola import PoleWyboru
from i18n.tlumacz import JEZYKI, jezyk_biezacy, t
from raporty.dane import Opcje, egzemplarze_w_zakresie
from uslugi import eksport, pliki

TABELE = ("egzemplarze", "modele", "lokalizacje", "historia")


class OknoEksportu(OknoDialogowe):
    def __init__(self, glowne, iid: str | None):
        super().__init__(glowne)
        rodzaj, ident = rozbierz_iid(iid)
        self.lok_zakresu = ident if rodzaj == "L" else (
            egzemplarze.efektywna_lokalizacja(self.db, ident) if rodzaj == "E" else None)
        self.zakres = tk.StringVar(value="wszystko")
        zapisane_tabele = (ustawienia.pobierz(self.db, "eksport_tabele") or ",".join(TABELE)).split(",")
        self.tabele = {k: tk.BooleanVar(value=k in zapisane_tabele) for k in TABELE}
        self.dostepne = eksport.dostepne_formaty()
        zapisane_formaty = (ustawienia.pobierz(self.db, "eksport_formaty") or "xlsx,html").split(",")
        self.formaty = {f: tk.BooleanVar(value=f in zapisane_formaty and self.dostepne[f]) for f in eksport.FORMATY}
        self.jezyk = PoleWyboru(lambda: [(j, t(f"jezyk.{j}")) for j in JEZYKI], jezyk_biezacy())
        self.prywatne = tk.BooleanVar(value=False)
        self.miniatury = tk.BooleanVar(value=True)
        self.wynik: list[Path] = []
        self._etykieta_wyniku: ttk.Label | None = None
        self._przycisk_folderu: ttk.Button | None = None

    def _opcje(self) -> Opcje:
        return Opcje(jezyk=self.jezyk.wartosc or jezyk_biezacy(),
                     lokalizacja_id=self.lok_zakresu if self.zakres.get() == "lokalizacja" else None,
                     tabele=tuple(k for k, v in self.tabele.items() if v.get()),
                     prywatne=self.prywatne.get(), miniatury=self.miniatury.get())

    def zbuduj_ui(self) -> None:
        self.title(t("okno.eksport"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)

        zakres = ttk.LabelFrame(ramka, text=t("eksport.zakres"), padding=10)
        zakres.pack(fill="x")
        ttk.Radiobutton(zakres, text=t("etykiety.zakres_wszystko"), value="wszystko",
                        variable=self.zakres, command=self._odswiez).pack(anchor="w")
        if self.lok_zakresu is not None:
            sciezka = lokalizacje.sciezki(self.db).get(self.lok_zakresu, "")
            ttk.Radiobutton(zakres, text=t("etykiety.zakres_lokalizacja", nazwa=sciezka), value="lokalizacja",
                            variable=self.zakres, command=self._odswiez).pack(anchor="w")

        co = ttk.LabelFrame(ramka, text=t("eksport.tabele"), padding=10)
        co.pack(fill="x", pady=(10, 0))
        for i, kod in enumerate(TABELE):
            ttk.Checkbutton(co, text=t(f"eksport.tabela.{kod}"), variable=self.tabele[kod]).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, 24))

        jak = ttk.LabelFrame(ramka, text=t("eksport.formaty"), padding=10)
        jak.pack(fill="x", pady=(10, 0))
        opisy = {"csv": "eksport.format_csv", "xlsx": "eksport.format_xlsx",
                 "xls": "eksport.format_xls", "html": "eksport.format_html"}
        for i, f in enumerate(eksport.FORMATY):
            ttk.Checkbutton(jak, text=t(opisy[f]), variable=self.formaty[f],
                            state="normal" if self.dostepne[f] else "disabled").grid(row=i, column=0, sticky="w")
            if not self.dostepne[f]:
                ttk.Label(jak, text=t("eksport.brak_biblioteki", nazwa="xlwt" if f == "xls" else "openpyxl"),
                          style="Opis.TLabel").grid(row=i, column=1, sticky="w", padx=(8, 0))

        opcje = ttk.LabelFrame(ramka, text=t("eksport.opcje"), padding=10)
        opcje.pack(fill="x", pady=(10, 0))
        ttk.Label(opcje, text=t("eksport.jezyk_raportu"), style="Pole.TLabel").grid(row=0, column=0, sticky="w")
        self.jezyk.zbuduj(opcje, width=12).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Checkbutton(opcje, text=t("eksport.prywatne"), variable=self.prywatne).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(opcje, text=t("eksport.miniatury"), variable=self.miniatury).grid(
            row=2, column=0, columnspan=2, sticky="w")

        self._etykieta_wyniku = ttk.Label(ramka, style="Opis.TLabel", wraplength=440, justify="left")
        self._etykieta_wyniku.pack(anchor="w", pady=(10, 0))
        przyciski = ttk.Frame(ramka)
        przyciski.pack(fill="x", pady=(12, 0))
        ttk.Button(przyciski, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        ttk.Button(przyciski, text=t("eksport.eksportuj"), style="Akcent.TButton",
                   command=self.eksportuj).pack(side="right", padx=(0, 8))
        self._przycisk_folderu = ttk.Button(przyciski, text=t("eksport.otworz_folder"), command=self._otworz_folder)
        self._odswiez()

    def _odswiez(self) -> None:
        """Liczba egzemplarzy w zakresie albo wynik ostatniego eksportu."""
        if self._etykieta_wyniku is None or not self._etykieta_wyniku.winfo_exists():
            return
        if self.wynik:
            self._etykieta_wyniku.configure(text=t("eksport.zapisano", liczba=len(self.wynik),
                                                   folder=str(self.wynik[0].parent)))
            self._przycisk_folderu.pack(side="left")
        else:
            liczba = len(egzemplarze_w_zakresie(self.db, self._opcje().lokalizacja_id))
            self._etykieta_wyniku.configure(text=t("eksport.w_zakresie", liczba=liczba))

    def _otworz_folder(self) -> None:
        if self.wynik:
            try:
                pliki.otworz(self.wynik[0].parent)
            except Exception as blad:   # noqa: BLE001
                pokaz_blad(self, blad)

    def eksportuj(self, baza: str | None = None) -> list[Path]:
        formaty = [f for f, v in self.formaty.items() if v.get()]
        opcje = self._opcje()
        if baza is None:
            katalog = ustawienia.pobierz(self.db, "eksport_katalog", str(Path.home()))
            nazwa = f"{t('eksport.plik.bazowy', opcje.jezyk)}_{date.today().isoformat()}"
            baza = filedialog.asksaveasfilename(parent=self, title=t("eksport.eksportuj"),
                                                initialdir=katalog, initialfile=nazwa)
            if not baza:
                return []
        try:
            self.wynik = eksport.eksportuj(self.db, baza, formaty, opcje)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return []
        ustawienia.zapisz(self.db, "eksport_formaty", ",".join(formaty))
        ustawienia.zapisz(self.db, "eksport_tabele", ",".join(opcje.tabele))
        ustawienia.zapisz(self.db, "eksport_katalog", str(Path(baza).parent))
        self._odswiez()
        return self.wynik
