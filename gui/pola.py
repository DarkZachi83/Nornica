# SPDX-License-Identifier: GPL-3.0-or-later
"""Pola formularzy, których STAN żyje w obiekcie, a nie w widżecie.

Zasada z Jaźwca: przy zmianie języka okno jest niszczone i budowane od nowa.
Wszystko, co ma przetrwać, nie może mieszkać w widżecie:
  * PoleWyboru — lista rozwijana pamięta WARTOŚĆ (np. id statusu), a nie
    wyświetlany napis; etykiety liczy od nowa przy każdym zbudowaniu,
    więc po przełączeniu pokazują się w nowym języku, a wybór zostaje,
  * PoleTekstu — wielowierszowy Text nie ma zmiennej tekstowej, więc
    jego treść jest zrzucana do atrybutu przed zniszczeniem widżetu,
  * zwykłe pola: tk.StringVar przypisany do obiektu okna — zmienna należy
    do interpretera Tcl, a nie do widżetu, i przeżywa destroy().
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Iterable

from i18n.tlumacz import t
from uslugi.formatowanie import (JEDNOSTKI_POJEMNOSCI, liczba_na_tekst, pojemnosc_na_tekst,
                                  rozbij_pojemnosc, tekst_na_bajty)
from wyjatki import BladNornicy

Opcje = Callable[[], Iterable[tuple[Any, str]]]


class PoleWyboru:
    def __init__(self, opcje: Opcje, wartosc: Any = None,
                 przy_zmianie: Callable[[Any], None] | None = None):
        self.opcje_fn = opcje
        self.wartosc = wartosc
        self.przy_zmianie = przy_zmianie
        self._opcje: list[tuple[Any, str]] = []
        self.widzet: ttk.Combobox | None = None

    def zbuduj(self, rodzic: tk.Misc, **opcje_widzetu) -> ttk.Combobox:
        opcje_widzetu.setdefault("state", "readonly")
        self.widzet = ttk.Combobox(rodzic, **opcje_widzetu)
        self.widzet.bind("<<ComboboxSelected>>", self._wybrano)
        self.odswiez_opcje()
        return self.widzet

    def odswiez_opcje(self) -> None:
        """Przelicza opcje (np. po zmianie kategorii). Wartość spoza nowej listy
        jest czyszczona."""
        self._opcje = list(self.opcje_fn())
        if self.wartosc is not None and all(w != self.wartosc for w, _ in self._opcje):
            self.wartosc = None
        if self._zywy():
            self.widzet.configure(values=[e for _, e in self._opcje])
            self._pokaz()

    def ustaw(self, wartosc: Any) -> None:
        self.wartosc = wartosc
        if self._zywy():
            self._pokaz()

    def _zywy(self) -> bool:
        return self.widzet is not None and bool(self.widzet.winfo_exists())

    def _pokaz(self) -> None:
        for i, (w, _) in enumerate(self._opcje):
            if w == self.wartosc:
                self.widzet.current(i)
                return
        self.widzet.set("")

    def _wybrano(self, _zdarzenie=None) -> None:
        i = self.widzet.current()
        self.wartosc = self._opcje[i][0] if i >= 0 else None
        if self.przy_zmianie:
            self.przy_zmianie(self.wartosc)


class PoleTekstu:
    def __init__(self, tekst: str | None = ""):
        self.tekst = tekst or ""
        self.widzet: tk.Text | None = None

    def zbuduj(self, rodzic: tk.Misc, **opcje) -> ttk.Frame:
        """Zwraca ramkę z polem i paskiem przewijania — do umieszczenia w oknie.
        Samo pole tekstowe jest w self.widzet."""
        opcje.setdefault("height", 5)
        opcje.setdefault("wrap", "word")
        ramka = ttk.Frame(rodzic)
        self.widzet = tk.Text(ramka, undo=True, **opcje)
        przewijak = ttk.Scrollbar(ramka, orient="vertical", command=self.widzet.yview)
        self.widzet.configure(yscrollcommand=przewijak.set)
        # pasek PRZED treścią: przy braku miejsca pack odbiera je ostatniemu widżetowi
        przewijak.pack(side="right", fill="y")
        self.widzet.pack(side="left", fill="both", expand=True)
        self.widzet.insert("1.0", self.tekst)
        return ramka

    def zapamietaj(self) -> str:
        if self.widzet is not None and self.widzet.winfo_exists():
            self.tekst = self.widzet.get("1.0", "end-1c")
        return self.tekst

    def ustaw(self, tekst: str) -> None:
        self.tekst = tekst or ""
        if self.widzet is not None and self.widzet.winfo_exists():
            self.widzet.delete("1.0", "end")
            self.widzet.insert("1.0", self.tekst)


class PolePojemnosci:
    """Pojemność: liczba + jednostka (B, KB, MB, GB) w jednej linii.
    Stan w obiekcie (StringVar + PoleWyboru) — przeżywa przebudowę okna.
    Atari 2600: „128” i „B”, zamiast „0,125” w polu na sztywno w KB."""

    def __init__(self, bajty: int | None, przy_zmianie=None):
        liczba, jednostka = rozbij_pojemnosc(bajty)
        self.liczba = tk.StringVar(value=liczba)
        self.jednostka = PoleWyboru(lambda: [(j, j) for j, _ in JEDNOSTKI_POJEMNOSCI], jednostka,
                                    przy_zmianie=lambda _w: przy_zmianie() if przy_zmianie else None)
        if przy_zmianie:
            self.liczba.trace_add("write", lambda *_: przy_zmianie())

    def zbuduj(self, rodzic: tk.Misc) -> ttk.Frame:
        ramka = ttk.Frame(rodzic)
        ttk.Entry(ramka, textvariable=self.liczba, width=14).pack(side="left", fill="x", expand=True)
        self.jednostka.zbuduj(ramka, width=5).pack(side="left", padx=(6, 0))
        return ramka

    def tekst(self) -> str:
        """„128 B” — albo pusty napis, gdy liczba nie jest wpisana."""
        liczba = self.liczba.get().strip()
        return f"{liczba} {self.jednostka.wartosc or 'KB'}" if liczba else ""

    def ustaw(self, bajty: int | None) -> None:
        liczba, jednostka = rozbij_pojemnosc(bajty)
        self.jednostka.ustaw(jednostka)
        self.liczba.set(liczba)

    def bajty(self) -> int | None:
        """Zgłasza ValueError przy niepoprawnej liczbie."""
        liczba = self.liczba.get().strip()
        return tekst_na_bajty(liczba, self.jednostka.wartosc or "KB") if liczba else None


class FormularzAtrybutow:
    """Pola atrybutów budowane z szablonu kategorii (wspólne dla modelu
    i egzemplarza). Klucze spoza szablonu (np. z importu) są zachowywane.

    Dziedziczenie (egzemplarz po modelu): pola są WYPEŁNIONE wartościami
    modelu, ale zbierz() zwraca tylko wartości RÓŻNE od modelu. Niezmienione
    pole nie trafia do egzemplarza, więc poprawka w modelu obejmie wszystkie
    egzemplarze, które tej wartości nie nadpisały. Obok pola widać, czy
    wartość jest z modelu, czy zmieniona.
    """

    def __init__(self, wartosci: dict | None, dziedziczone: dict | None = None):
        self.oryginal = dict(wartosci or {})
        self.dziedziczone = dict(dziedziczone or {})
        self.pola: dict[str, tk.StringVar | PoleWyboru] = {}
        self._opisy: dict[str, dict] = {}
        self._podpowiedzi: dict[str, ttk.Label] = {}   # przebudowywane razem z widżetami

    # ------------------------------------------------------------- wartości
    def _tekst(self, wartosc, kod: str | None = None) -> str:
        """Wartość z JSON -> napis do wyświetlenia (pojemność z jednostką)."""
        if kod is not None and self._opisy.get(kod, {}).get("typ") == "pojemnosc":
            return pojemnosc_na_tekst(wartosc) if isinstance(wartosc, (int, float)) else liczba_na_tekst(wartosc)
        return liczba_na_tekst(wartosc)

    def _odczyt(self, kod: str) -> str:
        pole = self.pola[kod]
        if isinstance(pole, PolePojemnosci):
            return pole.tekst()
        return ((pole.wartosc if isinstance(pole, PoleWyboru) else pole.get()) or "").strip()

    def _zapis(self, kod: str, wartosc) -> None:
        """wartosc: surowa wartość z JSON (dziedziczona z modelu) albo None."""
        pole = self.pola[kod]
        if isinstance(pole, PolePojemnosci):
            pole.ustaw(wartosc if isinstance(wartosc, (int, float)) else None)
        elif isinstance(pole, PoleWyboru):
            pole.ustaw(liczba_na_tekst(wartosc))
        else:
            pole.set(liczba_na_tekst(wartosc))

    def _konwertuj(self, opis: dict, surowa: str):
        """Tekst z pola -> wartość do JSON. Zgłasza ValueError."""
        if opis["typ"] == "pojemnosc":
            return self.pola[opis["kod"]].bajty()
        if opis["typ"] == "int":
            return int(surowa)
        if opis["typ"] == "real":
            return float(surowa.replace(",", "."))
        if opis["typ"] == "bool":
            return surowa == "true"
        return surowa

    def _pole(self, opis: dict):
        kod = opis["kod"]
        self._opisy[kod] = opis
        if kod not in self.pola:
            zrodlo = self.oryginal if kod in self.oryginal else self.dziedziczone
            poczatkowa = self._tekst(zrodlo.get(kod))
            odswiez = lambda *_a, k=kod: self._odswiez_podpowiedz(k)  # noqa: E731
            if opis["typ"] == "pojemnosc":
                wartosc = zrodlo.get(kod)
                self.pola[kod] = PolePojemnosci(wartosc if isinstance(wartosc, (int, float)) else None, odswiez)
            elif opis["typ"] == "bool":
                self.pola[kod] = PoleWyboru(lambda: [("", "—"), ("true", t("ogolne.tak")),
                                                     ("false", t("ogolne.nie"))], poczatkowa, odswiez)
            elif opis["typ"] == "enum":
                # opcje czytane z BIEŻĄCEGO opisu pola (aktualizowanego przy każdym zbuduj) —
                # nie z listy zapamiętanej przy pierwszym utworzeniu pola
                self.pola[kod] = PoleWyboru(lambda k=kod: [("", "—")] + [(x, x) for x in
                                                                         self._opisy[k].get("wartosci", [])],
                                            poczatkowa, odswiez)
            else:
                zmienna = tk.StringVar(value=poczatkowa)
                # Śledzenie dodane RAZ, przy tworzeniu zmiennej. Zmienna przeżywa
                # przebudowę okna, więc dokładanie śledzenia przy każdej budowie
                # mnożyłoby wywołania i sięgało po zniszczone etykiety.
                zmienna.trace_add("write", odswiez)
                self.pola[kod] = zmienna
        return self.pola[kod]

    def _rowne_modelowi(self, kod: str) -> bool:
        if kod not in self.dziedziczone:
            return False
        surowa = self._odczyt(kod)
        try:
            return self._konwertuj(self._opisy[kod], surowa) == self.dziedziczone[kod]
        except ValueError:
            return False

    def _odswiez_podpowiedz(self, kod: str) -> None:
        etykieta = self._podpowiedzi.get(kod)
        if etykieta is None or not etykieta.winfo_exists():
            return
        if kod not in self.dziedziczone:
            tekst = ""
        elif self._rowne_modelowi(kod):
            tekst = t("formularz.z_modelu")
        else:
            tekst = t("formularz.wartosc_modelu", wartosc=self._tekst(self.dziedziczone[kod], kod))
        etykieta.configure(text=tekst)

    def ustaw_dziedziczone(self, nowe: dict | None) -> None:
        """Zmiana modelu: pola, które trzymały wartość starego modelu (albo są
        puste), dostają wartość nowego. Wartości wpisane ręcznie zostają."""
        nowe = dict(nowe or {})
        for kod in list(self.pola):
            biezaca = self._odczyt(kod)
            if biezaca == "" or (kod in self.dziedziczone and self._rowne_modelowi(kod)):
                self._zapis(kod, nowe.get(kod))
        self.dziedziczone = nowe
        for kod in self.pola:
            self._odswiez_podpowiedz(kod)

    def wstaw(self, szablon: list[dict], wartosci: dict, nadpisz: bool = False) -> list[str]:
        """Wartości z zewnątrz (np. The Retro Web) do pól formularza. Pola już
        wypełnione zostają, chyba że nadpisz=True. Zwraca kody wstawionych pól."""
        wstawione = []
        opisy = {o["kod"]: o for o in szablon}
        for kod, wartosc in wartosci.items():
            if kod not in opisy:
                continue
            self._pole(opisy[kod])
            if self._odczyt(kod) and not nadpisz:
                continue
            self._zapis(kod, wartosc)
            self._odswiez_podpowiedz(kod)
            wstawione.append(kod)
        return wstawione

    # ---------------------------------------------------------------- widok
    def zbuduj(self, rodzic: tk.Misc, szablon: list[dict]) -> None:
        from i18n.tlumacz import nazwa
        for dziecko in rodzic.winfo_children():
            dziecko.destroy()
        self._podpowiedzi = {}
        if not szablon:
            ttk.Label(rodzic, text=t("formularz.brak_parametrow"), style="Opis.TLabel").grid(
                row=0, column=0, sticky="w", pady=8)
            return
        for wiersz, opis in enumerate(szablon):
            etykieta = nazwa(opis["nazwy"])
            if opis.get("jednostka"):
                etykieta = f"{etykieta} [{opis['jednostka']}]"
            ttk.Label(rodzic, text=etykieta, style="Pole.TLabel").grid(
                row=wiersz, column=0, sticky="w", padx=(0, 10), pady=3)
            pole = self._pole(opis)
            if isinstance(pole, PolePojemnosci):
                pole.zbuduj(rodzic).grid(row=wiersz, column=1, sticky="we", pady=3)
            elif isinstance(pole, PoleWyboru):
                pole.zbuduj(rodzic, width=28).grid(row=wiersz, column=1, sticky="we", pady=3)
            else:
                ttk.Entry(rodzic, textvariable=pole, width=30).grid(row=wiersz, column=1, sticky="we", pady=3)
            self._podpowiedzi[opis["kod"]] = ttk.Label(rodzic, style="Opis.TLabel")
            self._podpowiedzi[opis["kod"]].grid(row=wiersz, column=2, sticky="w", padx=(10, 0))
            self._odswiez_podpowiedz(opis["kod"])
        rodzic.columnconfigure(1, weight=1)

    # ---------------------------------------------------------------- zapis
    def zbierz(self, szablon: list[dict]) -> dict:
        """Słownik atrybutów do zapisu: bez pustych pól i bez wartości
        równych dziedziczonym z modelu. Zgłasza BladNornicy."""
        from i18n.tlumacz import nazwa
        kody = {o["kod"] for o in szablon}
        wynik = {k: v for k, v in self.oryginal.items() if k not in kody}
        for opis in szablon:
            self._pole(opis)
            surowa = self._odczyt(opis["kod"])
            if not surowa:
                continue
            try:
                wartosc = self._konwertuj(opis, surowa)
            except ValueError:
                raise BladNornicy("blad.wartosc_liczbowa", pole=nazwa(opis["nazwy"])) from None
            if opis["kod"] in self.dziedziczone and wartosc == self.dziedziczone[opis["kod"]]:
                continue
            wynik[opis["kod"]] = wartosc
        return wynik
