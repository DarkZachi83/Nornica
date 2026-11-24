# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Asystent AI”: parametry modelu z internetu, do przejrzenia i wstawienia.

Otwierane z okna modelu. Asystent szuka w sieci, lokalny model (Ollama)
wyciąga wartości ze znalezionych stron, a program sprawdza każdą z nich
(asystent/propozycje.py). Użytkownik zaznacza, co przyjmuje — wartości
trafiają do FORMULARZA modelu; zapis do bazy dopiero przyciskiem „Zapisz”.

Praca idzie w wątku pobocznym (sieć i model potrafią trwać minutę); do okna
wraca przez kolejkę, odczytywaną w wątku interfejsu. Stan żyje w atrybutach,
więc okno przeżywa zmianę języka i motywu.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from asystent.ollama import Przerwano
from asystent.propozycje import zapytanie
from gui import styl
from gui.asystent_wspolne import (PracaAsystenta, domyslnie_zaznaczona, fabryka_domyslna,
                                  lista_modeli_domyslna, ocena)
from gui.bazowe import OknoDialogowe
from gui.pola import PoleTekstu
from i18n.tlumacz import jezyk_biezacy, t
from wyjatki import BladNornicy


class OknoAsystenta(PracaAsystenta, OknoDialogowe):
    """dane: kategoria (nazwa), producent, nazwa; szablon: pola kategorii;
    obecne(): {kod: tekst w formularzu}; po_zastosowaniu(wynik, kody, nadpisz).
    Zaznaczony wiersz znaczy „wpisz tę wartość” — także w miejsce obecnej."""

    def __init__(self, glowne, szablon: list[dict], dane: dict, obecne, po_zastosowaniu,
                 fabryka=fabryka_domyslna, lista_modeli=lista_modeli_domyslna):
        super().__init__(glowne)
        self.szablon, self.dane, self.obecne = szablon, dane, obecne
        self.po_zastosowaniu = po_zastosowaniu
        self.zapytanie = tk.StringVar()
        self.oznaczenia = PoleTekstu(dane.get("oznaczenia", ""))
        self.wynik = None
        self.zaznaczone: set[str] = set()
        self._przygotuj_asystenta(fabryka, lista_modeli)

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("asystent.tytul"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        self._sekcja_ustawien(ramka)
        self._sekcja_przedmiotu(ramka)
        self._stan = ttk.Label(ramka, style="Opis.TLabel", wraplength=760, justify="left")
        self._stan.pack(fill="x", pady=(8, 0))
        self._pasek = ttk.Progressbar(ramka, mode="indeterminate")
        self._pasek.pack(fill="x", pady=(4, 0))
        self._sekcja_wynikow(ramka)
        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(10, 0))
        ttk.Label(dol, text=t("asystent.wstaw_podpowiedz"), style="Opis.TLabel").pack(side="left")
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        self._wstaw = ttk.Button(dol, text=t("asystent.wstaw"), style="Akcent.TButton", command=self.zastosuj)
        self._wstaw.pack(side="right", padx=(0, 8))
        self._odswiez()

    def _sekcja_przedmiotu(self, ramka: ttk.Frame) -> None:
        sekcja = ttk.LabelFrame(ramka, text=t("asystent.przedmiot"), padding=10)
        sekcja.pack(fill="x", pady=(10, 0))
        opis = " · ".join(x for x in (self.dane.get("kategoria"), self.dane.get("producent"),
                                      self.dane.get("nazwa")) if x)
        ttk.Label(sekcja, text=opis or "—").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(sekcja, text=t("asystent.oznaczenia"), style="Pole.TLabel").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.oznaczenia.zbuduj(sekcja, height=3, width=60, font=self.glowne.czcionki["zwykla"]).grid(row=1, column=1, columnspan=2, sticky="we",
                                                                padx=(8, 0), pady=(6, 0))
        ttk.Label(sekcja, text=t("asystent.oznaczenia_podpowiedz"), style="Opis.TLabel", wraplength=600,
                  justify="left").grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0))
        ttk.Label(sekcja, text=t("asystent.zapytanie"), style="Pole.TLabel").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(sekcja, textvariable=self.zapytanie).grid(row=3, column=1, sticky="we", padx=(8, 6), pady=(6, 0))
        przyciski = ttk.Frame(sekcja)
        przyciski.grid(row=3, column=2, sticky="e", pady=(6, 0))
        self._start = ttk.Button(przyciski, text=t("asystent.szukaj"), style="Akcent.TButton", command=self.uruchom)
        self._start.pack(side="left")
        self._stop = ttk.Button(przyciski, text=t("asystent.przerwij"), command=self.przerwij)
        self._stop.pack(side="left", padx=(6, 0))
        ttk.Label(sekcja, text=t("asystent.zapytanie_podpowiedz"), style="Opis.TLabel").grid(
            row=4, column=1, columnspan=2, sticky="w", padx=(8, 0))
        sekcja.columnconfigure(1, weight=1)

    def _sekcja_wynikow(self, ramka: ttk.Frame) -> None:
        obszar = ttk.Frame(ramka)
        obszar.pack(fill="both", expand=True, pady=(10, 0))
        kolumny = (("wstaw", 60), ("pole", 170), ("obecnie", 130), ("propozycja", 150), ("pewnosc", 160))
        drzewo = ttk.Treeview(obszar, columns=[k for k, _ in kolumny], show="headings", height=8,
                              selectmode="browse")
        for kod, szerokosc in kolumny:
            drzewo.heading(kod, text=t(f"asystent.kolumna_{kod}"), anchor="w")
            drzewo.column(kod, width=szerokosc, stretch=kod in ("propozycja", "pewnosc"), anchor="w")
        przewijak = ttk.Scrollbar(obszar, orient="vertical", command=drzewo.yview)
        drzewo.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")
        drzewo.pack(side="left", fill="both", expand=True)
        drzewo.tag_configure("niepotwierdzona", foreground=styl.KOLORY_STATUSOW["w_naprawie"])
        drzewo.tag_configure("bledna", foreground=styl.KOLORY_STATUSOW["uszkodzony"])
        drzewo.bind("<Button-1>", self._klik)
        drzewo.bind("<space>", lambda _e: self.przelacz(drzewo.focus()))
        drzewo.bind("<<TreeviewSelect>>", lambda _e: self._pokaz_szczegoly())
        self._drzewo = drzewo
        self._szczegoly = ttk.Label(ramka, wraplength=760, justify="left")
        self._szczegoly.pack(fill="x", pady=(6, 0))
        self._adres = ttk.Label(ramka, style="Odnosnik.TLabel", cursor="hand2")
        self._adres.pack(anchor="w")
        self._adres.bind("<Button-1>", lambda _e: self._otworz_zrodlo())
        self._uwagi = ttk.Label(ramka, style="Opis.TLabel", wraplength=760, justify="left")
        self._uwagi.pack(fill="x", pady=(6, 0))

    def _odswiez(self) -> None:
        """Widok ze stanu w atrybutach — po każdej zmianie i po przebudowie okna."""
        if not hasattr(self, "_drzewo") or not self._drzewo.winfo_exists():
            return
        self._odswiez_ustawienia()
        self._odswiez_pracy(self._start, self._stop, self._pasek)
        if self.pracuje:
            self._stan.configure(text=self.postep)
        elif self.blad is not None:
            tekst = self.blad.komunikat() if isinstance(self.blad, BladNornicy) else str(self.blad)
            self._stan.configure(text=tekst, style="Ostrzezenie.TLabel")
        elif self.wynik is not None:
            self._stan.configure(text=t("asystent.gotowe", ile=len(self.wynik.wartosci),
                                        zapytanie=self.wynik.zapytanie), style="Opis.TLabel")
        else:
            self._stan.configure(text=t("asystent.wstep"), style="Opis.TLabel")
        self._wypelnij_tabele()

    def _wypelnij_tabele(self) -> None:
        drzewo = self._drzewo
        biezacy = drzewo.focus()
        drzewo.delete(*drzewo.get_children())
        if self.wynik is None:
            return
        obecne = self.obecne()
        for w in self.wynik.wartosci:
            pewnosc, ostrzezenie = ocena(w, obecne.get(w.kod, ""))
            znaczniki = ("bledna",) if w.blad else ("niepotwierdzona",) if ostrzezenie else ()
            znak = "—" if w.blad else "☑" if w.kod in self.zaznaczone else "☐"
            drzewo.insert("", "end", iid=w.kod, tags=znaczniki,
                          values=(znak, w.etykieta, obecne.get(w.kod, "") or "—", w.tekst, pewnosc))
        if biezacy and drzewo.exists(biezacy):
            drzewo.focus(biezacy)
            drzewo.selection_set(biezacy)
        self._pokaz_szczegoly()

    def _pokaz_szczegoly(self) -> None:
        w = self._wartosc(self._drzewo.focus() or (self._drzewo.selection() or ("",))[0])
        if w is None:
            self._szczegoly.configure(text=t("asystent.wybierz_wiersz") if self.wynik else "")
            self._adres.configure(text="")
        else:
            cytat = f"„{w.cytat}”" if w.cytat else t("asystent.bez_cytatu")
            self._szczegoly.configure(text=t("asystent.cytat", cytat=cytat))
            self._adres.configure(text=f"{w.zrodlo.tytul} — {w.zrodlo.adres}" if w.zrodlo else t("asystent.bez_zrodla"))
        self._uwagi.configure(text=t("asystent.uwagi", uwagi=self.wynik.uwagi) if self.wynik and self.wynik.uwagi else "")

    def _wartosc(self, kod: str):
        if self.wynik is None:
            return None
        return next((w for w in self.wynik.wartosci if w.kod == kod), None)

    def _otworz_zrodlo(self) -> None:
        w = self._wartosc(self._drzewo.focus())
        if w is not None and w.zrodlo is not None:
            webbrowser.open(w.zrodlo.adres)

    def _klik(self, zdarzenie) -> None:
        if self._drzewo.identify_column(zdarzenie.x) == "#1":
            self.przelacz(self._drzewo.identify_row(zdarzenie.y))

    def przelacz(self, kod: str) -> None:
        """Zaznacza albo odznacza wiersz do wstawienia (wartości z błędem — nigdy)."""
        w = self._wartosc(kod)
        if w is None or not w.mozna_wstawic:
            return
        self.zaznaczone.symmetric_difference_update({kod})
        self._drzewo.set(kod, "wstaw", "☑" if kod in self.zaznaczone else "☐")

    # ------------------------------------------------------------------ praca
    def uruchom(self) -> None:
        if not self._gotowy_do_pracy():
            return
        dane = {**self.dane, "oznaczenia": self.oznaczenia.zapamietaj()}
        tekst_zapytania = self.zapytanie.get().strip() or zapytanie(dane.get("producent", ""), dane.get("nazwa", ""),
                                                                     dane["oznaczenia"])
        self.pracuje, self.blad, self.wynik, self.zaznaczone = True, None, None, set()
        self.postep = t("asystent.krok_start")
        anuluj, jezyk, u = self._anuluj, jezyk_biezacy(), self.ustawienia()

        def w_tle():
            try:
                asystent = self._fabryka(u)
                wynik = asystent.zaproponuj(self.szablon, dane, tekst_zapytania, anuluj,
                                            lambda klucz, **p: self._kolejka.put(("krok", klucz, p)), jezyk)
                self._kolejka.put(("wynik", wynik, None))
            except Przerwano:
                self._kolejka.put(("przerwano", None, None))
            except Exception as blad:   # noqa: BLE001 — wynik wraca do wątku interfejsu
                self._kolejka.put(("blad", None, blad))

        self._uruchom_watek(w_tle, "asystent")
        self._odswiez()

    def _odbierz(self, rodzaj: str, wartosc, dodatek) -> None:
        if rodzaj == "wynik":
            self.pracuje, self.wynik = False, wartosc
            obecne = self.obecne()
            self.zaznaczone = {w.kod for w in wartosc.wartosci if domyslnie_zaznaczona(w, obecne.get(w.kod, ""))}

    def zastosuj(self) -> None:
        if self.wynik is None or not self.zaznaczone:
            return
        self.po_zastosowaniu(self.wynik, set(self.zaznaczone), True)
        self.zamknij()

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.oznaczenia.zapamietaj()

