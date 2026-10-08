# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Dane z The Retro Web”: adres strony produktu (albo strona zapisana
w przeglądarce), podgląd, co trafi do formularza modelu, i zastosowanie.

Nic nie jest zapisywane w bazie — okno uzupełnia FORMULARZ modelu, a zapis
następuje dopiero przyciskiem „Zapisz” w oknie modelu.

Sieć działa w wątku pobocznym; wynik wraca do wątku interfejsu przez kolejkę
sprawdzaną pętlą after(). Okno przechowuje odczytaną STRONĘ, a nie gotowe
napisy — podgląd powstaje przy wyświetleniu, więc przeżywa zmianę języka.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

from gui import styl
from gui.bazowe import OknoDialogowe, pokaz_blad
from i18n.tlumacz import nazwa, t
from uslugi import retroweb
from uslugi.formatowanie import liczba_na_tekst, pojemnosc_na_tekst


class OknoRetroWeb(OknoDialogowe):
    def __init__(self, glowne, adres: str = "", producent: str = "", nazwa_modelu: str = "", po_zastosowaniu=None):
        super().__init__(glowne)
        self.adres = tk.StringVar(value=adres if adres and retroweb.HOST in adres else "")
        self.producent, self.nazwa_modelu = producent, nazwa_modelu
        self.nadpisz = tk.BooleanVar(value=False)
        self.po_zastosowaniu = po_zastosowaniu
        self.strona: retroweb.Strona | None = None
        self.blad = None
        self.pobieranie = False
        self._wyniki: queue.Queue = queue.Queue()
        self._podglad: tk.Text | None = None
        self._przyciski: dict[str, ttk.Button] = {}

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("okno.retroweb"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("trw.wstep"), wraplength=560, justify="left").pack(anchor="w")
        wiersz = ttk.Frame(ramka)
        wiersz.pack(fill="x", pady=(10, 0))
        ttk.Label(wiersz, text=t("trw.adres"), style="Pole.TLabel").pack(side="left")
        pole = ttk.Entry(wiersz, textvariable=self.adres, width=56)
        pole.pack(side="left", fill="x", expand=True, padx=(8, 0))
        pole.bind("<Return>", lambda _e: self.pobierz())
        akcje = ttk.Frame(ramka)
        akcje.pack(fill="x", pady=(8, 0))
        self._przyciski = {
            "szukaj": ttk.Button(akcje, text=t("trw.szukaj"), command=self.szukaj),
            "pobierz": ttk.Button(akcje, text=t("trw.pobierz"), command=self.pobierz),
            "plik": ttk.Button(akcje, text=t("trw.z_pliku"), command=self.z_pliku),
        }
        for przycisk in self._przyciski.values():
            przycisk.pack(side="left", padx=(0, 6))

        obszar = ttk.Frame(ramka)
        obszar.pack(fill="both", expand=True, pady=(10, 0))
        self._podglad = tk.Text(obszar, height=18, width=76, wrap="word", relief="flat", borderwidth=0,
                                highlightthickness=0, background=styl.KOLORY["panel"], padx=10, pady=8,
                                font=self.glowne.czcionki["zwykla"])
        przewijak = ttk.Scrollbar(obszar, orient="vertical", command=self._podglad.yview)
        self._podglad.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")      # PRZED treścią — inaczej pack go „zje”
        self._podglad.pack(side="left", fill="both", expand=True)
        self._podglad.tag_configure("naglowek", font=self.glowne.czcionki["pogrubiona"], spacing1=6)
        self._podglad.tag_configure("opis", foreground=styl.KOLORY["przygaszony"])
        self._podglad.tag_configure("blad", foreground=styl.KOLORY_STATUSOW["uszkodzony"])

        ttk.Checkbutton(ramka, text=t("trw.nadpisz"), variable=self.nadpisz).pack(anchor="w", pady=(8, 0))
        ttk.Label(ramka, text=t("trw.licencja_info"), style="Opis.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(4, 0))
        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(12, 0))
        ttk.Button(dol, text=t("przycisk.anuluj"), command=self.zamknij).pack(side="right")
        self._przyciski["zastosuj"] = ttk.Button(dol, text=t("trw.zastosuj"), style="Akcent.TButton",
                                                 command=self.zastosuj)
        self._przyciski["zastosuj"].pack(side="right", padx=(0, 8))
        self._odswiez()

    def _odswiez(self) -> None:
        if self._podglad is None or not self._podglad.winfo_exists():
            return
        tekst = self._podglad
        tekst.configure(state="normal")
        tekst.delete("1.0", "end")
        if self.pobieranie:
            tekst.insert("end", t("trw.pobieranie"), ("opis",))
        elif self.blad is not None:
            tekst.insert("end", self.blad.komunikat() if hasattr(self.blad, "komunikat") else str(self.blad),
                         ("blad",))
        elif self.strona is None:
            tekst.insert("end", t("trw.instrukcja"), ("opis",))
        else:
            self._wypisz_podglad(tekst)
        tekst.configure(state="disabled")
        for kod, przycisk in self._przyciski.items():
            if przycisk.winfo_exists():
                stan = "disabled" if self.pobieranie or (kod == "zastosuj" and self.strona is None) else "normal"
                przycisk.configure(state=stan)

    def _wypisz_podglad(self, tekst: tk.Text) -> None:
        from baza.repozytoria import slowniki
        p = retroweb.propozycja(self.db, self.strona)
        kat = self.db.execute("SELECT id, nazwy FROM kategoria WHERE kod = ?", (p.kategoria_kod,)).fetchone()
        tekst.insert("end", t("trw.ogolne") + "\n", ("naglowek",))
        for etykieta, wartosc in ((t("pole.kategoria"), nazwa(kat["nazwy"])), (t("pole.producent"), p.producent),
                                  (t("pole.nazwa_modelu"), p.nazwa), (t("pole.rok_od"), p.rok_od),
                                  (t("pole.zrodlo_url"), p.zrodlo_url)):
            if wartosc:
                tekst.insert("end", f"  • {etykieta}: {wartosc}\n")
        if p.atrybuty:
            pola = {o["kod"]: o for o in slowniki.szablon(self.db, kat["id"])}
            tekst.insert("end", t("zakladka.parametry") + "\n", ("naglowek",))
            for kod, wartosc in p.atrybuty.items():
                opis = pola.get(kod, {})
                pokaz = pojemnosc_na_tekst(wartosc) if opis.get("typ") == "pojemnosc" else liczba_na_tekst(wartosc)
                tekst.insert("end", f"  • {nazwa(opis['nazwy']) if opis else kod}: {pokaz}\n")
        if p.zlacza_opis:
            tekst.insert("end", t("zakladka.zlacza") + "\n", ("naglowek",))
            for rola, nazwa_zlacza, ilosc in p.zlacza_opis:
                tekst.insert("end", f"  • {t(f'trw.rola.{rola}')}: {ilosc}× {nazwa_zlacza}\n")
        tekst.insert("end", t("trw.do_opisu") + "\n", ("naglowek",))
        tekst.insert("end", p.opis + "\n", ("opis",))

    # ------------------------------------------------------------------ akcje
    def szukaj(self) -> None:
        webbrowser.open(retroweb.adres_wyszukiwania(self.producent, self.nazwa_modelu))

    def pobierz(self) -> None:
        try:
            adres = retroweb.sprawdz_adres(self.adres.get())
        except Exception as blad:   # noqa: BLE001
            self.blad, self.strona = blad, None
            self._odswiez()
            return
        self.pobieranie, self.blad = True, None
        self._odswiez()

        def w_tle():
            try:
                self._wyniki.put(("ok", retroweb.pobierz(adres), adres))
            except Exception as blad:   # noqa: BLE001 — wynik wraca do wątku interfejsu
                self._wyniki.put(("blad", blad, adres))

        threading.Thread(target=w_tle, name="retroweb", daemon=True).start()
        self.after(100, self._czekaj)

    def _czekaj(self) -> None:
        try:
            rodzaj, wynik, adres = self._wyniki.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, self._czekaj)
            return
        self.pobieranie = False
        if rodzaj == "ok":
            self._wczytaj(wynik, adres)
        else:
            self.blad, self.strona = wynik, None
            self._odswiez()

    def z_pliku(self, sciezka: str | None = None) -> None:
        if sciezka is None:
            sciezka = filedialog.askopenfilename(parent=self, title=t("trw.z_pliku"),
                                                 filetypes=[("HTML", "*.html *.htm"), (t("plik.wszystkie"), "*")])
            if not sciezka:
                return
        try:
            html = retroweb.wczytaj_plik(sciezka)
        except Exception as blad:   # noqa: BLE001
            self.blad, self.strona = blad, None
            self._odswiez()
            return
        # adres wpisany w oknie (np. z pola „Strona źródłowa”) — gdy strona zapisana bez niego
        adres = self.adres.get().strip()
        self._wczytaj(html, adres if retroweb.HOST in adres else None)

    def _wczytaj(self, html: str, adres: str | None) -> None:
        try:
            self.strona, self.blad = retroweb.parsuj(html, adres), None
            if self.strona.url:
                self.adres.set(self.strona.url)
        except Exception as blad:   # noqa: BLE001
            self.strona, self.blad = None, blad
        self._odswiez()

    def zastosuj(self) -> None:
        if self.strona is None:
            return
        try:
            propozycja = retroweb.propozycja(self.db, self.strona)
            if self.po_zastosowaniu:
                self.po_zastosowaniu(propozycja, self.nadpisz.get())
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
