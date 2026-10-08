# SPDX-License-Identifier: GPL-3.0-or-later
"""Edytor złączy — wspólny dla modelu i egzemplarza.

Stan (słownik złączy, wybrany wiersz, pola dodawania) żyje w obiekcie,
więc edytor przeżywa przebudowę okna po zmianie języka.

W trybie egzemplarza złącza modelu są dziedziczone: wiersz pokazuje, czy
złącze jest „z modelu”, zmienione, dodane, czy usunięte (dolutowany port,
wylutowane gniazdo). Zapis zachowuje tylko różnice od modelu, więc poprawka
złączy w modelu obejmie wszystkie egzemplarze, które ich nie zmieniły.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tkinter import messagebox

from baza.enumy import etykieta, opcje
from baza.repozytoria import zlacza as repo
from baza.repozytoria.slowniki import klucz_kolejnosci
from gui.pola import PoleWyboru
from i18n.tlumacz import nazwa, t

KOLEJNOSC_RODZAJOW = {"port": 0, "slot": 1, "gniazdo": 2, "interfejs": 3}


class EdytorZlaczy:
    def __init__(self, db, wartosci: repo.Zlacza, dziedziczone: repo.Zlacza | None = None, glowne=None):
        self.db = db
        self.glowne = glowne
        self.tryb_egzemplarza = dziedziczone is not None
        self.dziedziczone = dict(dziedziczone or {})
        self.wartosci = dict(wartosci)
        self.zaznaczony: tuple | None = None
        self._typy = {w["id"]: w for w in repo.typy(db)}
        self.nowy_typ = PoleWyboru(self._opcje_typow, przy_zmianie=lambda _w: self._odswiez_przyciski())
        self._przyciski_wiersza: list[ttk.Button] = []
        self._przyciski_typu: list[ttk.Button] = []
        self.nowa_rola = PoleWyboru(lambda: opcje("model_zlacze.rola"), "posiada")
        self.nowa_ilosc = tk.StringVar(value="1")
        self._lista: ttk.Treeview | None = None

    # ---------------------------------------------------------------- opcje
    def _opcje_typow(self):
        self._typy = {w["id"]: w for w in repo.typy(self.db)}   # czytane od nowa: mogły dojść własne
        typy = sorted(self._typy.values(), key=lambda w: (KOLEJNOSC_RODZAJOW.get(w["rodzaj"], 9), *klucz_kolejnosci(w)))
        return [(w["id"], f"{etykieta('zlacze_typ.rodzaj', w['rodzaj'])}: {nazwa(w['nazwy'])}"
                 + ("" if w["kod"] else f"  ({t('zlacza.wlasny')})")) for w in typy]

    # ---------------------------------------------------------------- widok
    def zbuduj(self, rodzic: tk.Misc) -> None:
        for dziecko in rodzic.winfo_children():
            dziecko.destroy()
        kolumny = [("rola", "kolumna.rola", 90), ("zlacze", "kolumna.zlacze", 230), ("ilosc", "kolumna.ilosc", 55)]
        if self.tryb_egzemplarza:
            kolumny.append(("zrodlo", "kolumna.pochodzenie", 175))
        ramka = ttk.Frame(rodzic)
        ramka.pack(fill="both", expand=True)
        self._lista = ttk.Treeview(ramka, columns=[k for k, _, _ in kolumny], show="headings",
                                   height=8, selectmode="browse")
        for kod, klucz, szerokosc in kolumny:
            self._lista.heading(kod, text=t(klucz), anchor="w")
            self._lista.column(kod, width=szerokosc, stretch=kod == "zlacze")
        przewijak = ttk.Scrollbar(ramka, orient="vertical", command=self._lista.yview)
        self._lista.configure(yscrollcommand=przewijak.set)
        # pasek PRZED treścią: przy braku miejsca pack odbiera je ostatniemu widżetowi
        przewijak.pack(side="right", fill="y")
        self._lista.pack(side="left", fill="both", expand=True)
        self._lista.bind("<<TreeviewSelect>>", self._wybrano)
        self._lista.bind("<Delete>", lambda _e: self.usun())
        self._lista.bind("<Button-3>", self._menu_wiersza)
        self._lista.bind("<Button-2>", self._menu_wiersza)

        zmiana = ttk.Frame(rodzic)
        zmiana.pack(fill="x", pady=(6, 0))
        self._przyciski_wiersza = [
            ttk.Button(zmiana, text="+1", width=4, command=lambda: self.zmien(1)),
            ttk.Button(zmiana, text="−1", width=4, command=lambda: self.zmien(-1)),
            ttk.Button(zmiana, text=t("akcja.usun"), command=self.usun),
        ]
        if self.tryb_egzemplarza:
            self._przyciski_wiersza.append(ttk.Button(zmiana, text=t("akcja.przywroc_z_modelu"),
                                                      command=self.przywroc))
        for i, przycisk in enumerate(self._przyciski_wiersza):
            przycisk.pack(side="left", padx=(0 if i == 0 else 4, 0))
        ttk.Label(rodzic, text=t("zlacza.podpowiedz_wiersz"), style="Opis.TLabel").pack(anchor="w", pady=(4, 10))

        dodaj = ttk.LabelFrame(rodzic, text=t("zlacza.dodaj"), padding=8)
        dodaj.pack(fill="x")
        self.nowy_typ.zbuduj(dodaj, width=34).grid(row=0, column=0, sticky="we")
        self.nowa_rola.zbuduj(dodaj, width=10).grid(row=0, column=1, padx=(6, 0))
        ttk.Spinbox(dodaj, from_=1, to=64, width=4, textvariable=self.nowa_ilosc).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(dodaj, text=t("akcja.dodaj"), command=self.dodaj).grid(row=0, column=3, padx=(6, 0))
        if self.glowne is not None:
            typy = ttk.Frame(dodaj)
            typy.grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
            ttk.Button(typy, text=t("akcja.nowy_typ_zlacza"), command=self.nowy_typ_zlacza).pack(side="left")
            self._przyciski_typu = [
                ttk.Button(typy, text=t("akcja.edytuj_typ_zlacza"), command=self.edytuj_typ_zlacza),
                ttk.Button(typy, text=t("akcja.usun_typ_zlacza"), command=self.usun_typ_zlacza),
            ]
            for przycisk in self._przyciski_typu:
                przycisk.pack(side="left", padx=(4, 0))
            self._podpowiedz_typu = ttk.Label(dodaj, style="Opis.TLabel")
            self._podpowiedz_typu.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        dodaj.columnconfigure(0, weight=1)
        self.wypelnij()

    def _opis_zrodla(self, klucz: tuple) -> str:
        if klucz not in self.dziedziczone:
            return t("zlacza.dodane")
        ilosc, z_modelu = self.wartosci.get(klucz, 0), self.dziedziczone[klucz]
        if ilosc == z_modelu:
            return t("formularz.z_modelu")
        if ilosc == 0:
            return t("zlacza.usuniete", ilosc=z_modelu)
        return t("formularz.wartosc_modelu", wartosc=z_modelu)

    def wypelnij(self) -> None:
        lista = self._lista
        if lista is None or not lista.winfo_exists():
            return
        lista.delete(*lista.get_children())
        self._typy = {w["id"]: w for w in repo.typy(self.db)}
        klucze = set(self.wartosci) | set(self.dziedziczone)
        klucze = [k for k in klucze if self.wartosci.get(k, 0) > 0 or k in self.dziedziczone]
        klucze.sort(key=lambda k: (k[1], KOLEJNOSC_RODZAJOW.get(self._typy[k[0]]["rodzaj"], 9),
                                   *klucz_kolejnosci(self._typy[k[0]])))
        for klucz in klucze:
            typ_id, rola = klucz
            wartosci = [etykieta("model_zlacze.rola", rola), nazwa(self._typy[typ_id]["nazwy"]),
                        self.wartosci.get(klucz, 0)]
            if self.tryb_egzemplarza:
                wartosci.append(self._opis_zrodla(klucz))
            lista.insert("", "end", iid=f"{typ_id}|{rola}", values=wartosci)
        if self.zaznaczony and lista.exists(f"{self.zaznaczony[0]}|{self.zaznaczony[1]}"):
            lista.selection_set(f"{self.zaznaczony[0]}|{self.zaznaczony[1]}")
        if not klucze:
            lista.insert("", "end", iid="pusto", values=("", t("zlacza.brak"), ""))
        self._odswiez_przyciski()

    def _wybrano(self, _e=None) -> None:
        wybor = self._lista.selection()
        if wybor and wybor[0] != "pusto":
            typ, rola = wybor[0].split("|")
            self.zaznaczony = (int(typ), rola)
        else:
            self.zaznaczony = None
        self._odswiez_przyciski()

    def _odswiez_przyciski(self) -> None:
        """Przyciski wiersza aktywne dopiero po zaznaczeniu wiersza; edycja i usuwanie
        typu — tylko dla typu dopisanego przez użytkownika."""
        for przycisk in self._przyciski_wiersza:
            if przycisk.winfo_exists():
                przycisk.configure(state="normal" if self.zaznaczony else "disabled")
        typ = self._typy.get(self.nowy_typ.wartosc) if self.nowy_typ.wartosc else None
        wlasny = typ is not None and typ["kod"] is None
        for przycisk in self._przyciski_typu:
            if przycisk.winfo_exists():
                przycisk.configure(state="normal" if wlasny else "disabled")
        podpowiedz = getattr(self, "_podpowiedz_typu", None)
        if podpowiedz is not None and podpowiedz.winfo_exists():
            podpowiedz.configure(text=t("zlacza.typ_wbudowany") if typ is not None and not wlasny
                                 else t("zlacza.brak_na_liscie"))

    def _menu_wiersza(self, zdarzenie) -> None:
        iid = self._lista.identify_row(zdarzenie.y)
        if not iid or iid == "pusto":
            return
        self._lista.selection_set(iid)
        self._wybrano()
        menu = tk.Menu(self._lista, tearoff=False)
        menu.add_command(label="+1", command=lambda: self.zmien(1))
        menu.add_command(label="−1", command=lambda: self.zmien(-1))
        if self.tryb_egzemplarza and self.zaznaczony in self.dziedziczone:
            menu.add_command(label=t("akcja.przywroc_z_modelu"), command=self.przywroc)
        menu.add_separator()
        menu.add_command(label=t("akcja.usun"), command=self.usun)
        try:
            menu.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
        finally:
            menu.grab_release()

    # ---------------------------------------------------------------- zmiany
    def zmien(self, roznica: int) -> None:
        if self.zaznaczony is None:
            return
        nowa = max(0, self.wartosci.get(self.zaznaczony, 0) + roznica)
        if nowa == 0 and self.zaznaczony not in self.dziedziczone:
            self.wartosci.pop(self.zaznaczony, None)
            self.zaznaczony = None
        else:
            self.wartosci[self.zaznaczony] = nowa
        self.wypelnij()

    def usun(self) -> None:
        if self.zaznaczony is None:
            return
        if self.zaznaczony in self.dziedziczone:
            self.wartosci[self.zaznaczony] = 0        # usunięte względem modelu — widoczne, do przywrócenia
        else:
            self.wartosci.pop(self.zaznaczony, None)
            self.zaznaczony = None
        self.wypelnij()

    def przywroc(self) -> None:
        if self.zaznaczony in self.dziedziczone:
            self.wartosci[self.zaznaczony] = self.dziedziczone[self.zaznaczony]
            self.wypelnij()

    def dodaj(self) -> None:
        if not self.nowy_typ.wartosc or not self.nowa_rola.wartosc:
            return
        try:
            ilosc = max(1, int(self.nowa_ilosc.get()))
        except ValueError:
            ilosc = 1
        klucz = (self.nowy_typ.wartosc, self.nowa_rola.wartosc)
        self.wartosci[klucz] = (self.wartosci.get(klucz, 0) + ilosc) if self.wartosci.get(klucz) else ilosc
        self.zaznaczony = klucz
        self.wypelnij()

    def nowy_typ_zlacza(self) -> None:
        from gui.okno_typu_zlacza import OknoTypuZlacza
        rodzaj = self._typy[self.nowy_typ.wartosc]["rodzaj"] if self.nowy_typ.wartosc in self._typy else None
        OknoTypuZlacza(self.glowne, rodzaj, po_zapisie=self._typ_dodany).pokaz()

    def _typ_dodany(self, typ_id: int) -> None:
        self.nowy_typ.odswiez_opcje()
        self.nowy_typ.ustaw(typ_id)        # gotowe do kliknięcia „Dodaj”
        self.wypelnij()                    # poprawiona nazwa także w wierszach listy

    def edytuj_typ_zlacza(self) -> None:
        from gui.okno_typu_zlacza import OknoTypuZlacza
        if self.nowy_typ.wartosc:
            OknoTypuZlacza(self.glowne, po_zapisie=self._typ_dodany, typ_id=self.nowy_typ.wartosc).pokaz()

    def usun_typ_zlacza(self) -> None:
        from gui.bazowe import pokaz_blad
        from uslugi import inwentarz
        typ_id = self.nowy_typ.wartosc
        if not typ_id:
            return
        okno = self._lista.winfo_toplevel()
        # Złącze tego typu dodane w tym oknie, jeszcze niezapisane — baza o nim nie wie
        if any(k[0] == typ_id and v > 0 for k, v in self.wartosci.items()):
            messagebox.showwarning(t("okno.uwaga"), t("blad.typ_w_uzyciu_tutaj"), parent=okno)
            return
        if not messagebox.askyesno(t("okno.potwierdzenie"),
                                   t("pytanie.usun_typ_zlacza", nazwa=nazwa(self._typy[typ_id]["nazwy"])),
                                   parent=okno):
            return
        try:
            inwentarz.usun_typ_zlacza(self.db, typ_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(okno, blad)
            return
        self.nowy_typ.odswiez_opcje()      # usunięty typ znika z listy, wybór się czyści
        self._odswiez_przyciski()
        self.glowne.odswiez()              # pozostałe otwarte edytory też go usuną

    def dane_zmienione(self) -> None:
        """Wołane przez okno dialogowe po zmianie danych (np. nowy typ złącza
        dodany z innego okna)."""
        self.nowy_typ.odswiez_opcje()
        self.wypelnij()

    def ustaw_dziedziczone(self, nowe: repo.Zlacza) -> None:
        """Zmiana modelu: zmiany wprowadzone w egzemplarzu zostają, reszta
        pochodzi z nowego modelu."""
        nadpisania = repo.roznice(self.wartosci, self.dziedziczone)
        self.dziedziczone = dict(nowe)
        self.wartosci = repo.efektywne(self.dziedziczone, nadpisania)
        self.wypelnij()

    def wstaw(self, zlacza: dict, nadpisz: bool = False) -> int:
        """Złącza z zewnątrz (np. The Retro Web): brakujące dopisane, istniejące
        zostają, chyba że nadpisz=True. Zwraca liczbę zmienionych wierszy."""
        zmienione = 0
        for klucz, ilosc in zlacza.items():
            if self.wartosci.get(klucz, 0) > 0 and not nadpisz:
                continue
            if self.wartosci.get(klucz) != ilosc:
                self.wartosci[klucz] = ilosc
                zmienione += 1
        self.wypelnij()
        return zmienione

    def wynik(self) -> repo.Zlacza:
        return {k: v for k, v in self.wartosci.items() if v > 0}
