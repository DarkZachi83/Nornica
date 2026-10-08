# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno etykiet z kodami QR: wybór zakresu i formatu, zapis PDF do druku.

Format i przesunięcie (kalibracja drukarki) są zapamiętywane w ustawieniach —
to cecha drukarki i naklejek, a nie pojedynczego wydruku.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from baza.repozytoria import egzemplarze, lokalizacje, ustawienia
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import rozbierz_iid
from gui.pola import PoleWyboru
from i18n.tlumacz import t
from uslugi import etykiety, pliki
from uslugi.formatowanie import liczba_na_tekst
from wyjatki import BladNornicy

POLA_WLASNE = ("szerokosc", "wysokosc", "kolumny", "wiersze", "lewy", "gorny", "odstep_x", "odstep_y")
DOMYSLNE_WLASNE = {"szerokosc": "70", "wysokosc": "37", "kolumny": "3", "wiersze": "8",
                   "lewy": "0", "gorny": "0.5", "odstep_x": "0", "odstep_y": "0"}


class OknoEtykiet(OknoDialogowe):
    def __init__(self, glowne, iid: str | None):
        super().__init__(glowne)
        self.rodzaj, self.ident = rozbierz_iid(iid)
        # lokalizacja zakresu: zaznaczona lokalizacja albo miejsce zaznaczonego egzemplarza
        if self.rodzaj == "L":
            self.lok_zakresu = self.ident
        elif self.rodzaj == "E":
            self.lok_zakresu = egzemplarze.efektywna_lokalizacja(self.db, self.ident)
        else:
            self.lok_zakresu = None
        self.zakres = tk.StringVar(value="zaznaczony" if self.rodzaj in ("E", "L") else "wszystko")
        self.z_lokalizacjami = tk.BooleanVar(value=True)
        self.format = PoleWyboru(self._opcje_formatow,
                                 ustawienia.pobierz(self.db, "etykiety_format", "avery_3474"),
                                 przy_zmianie=lambda _w: self._zmiana())
        self.start = tk.StringVar(value="1")
        self.przesuniecie = {os_: tk.StringVar(value=ustawienia.pobierz(self.db, f"etykiety_przesuniecie_{os_}", "0"))
                             for os_ in ("x", "y")}
        self.wlasne = {k: tk.StringVar(value=ustawienia.pobierz(self.db, f"etykiety_wlasny_{k}", v))
                       for k, v in DOMYSLNE_WLASNE.items()}
        self.ramki = tk.BooleanVar(value=False)
        # Tryb druku: obraz (rastrowy) działa z każdą drukarką i filtrem — domyślny.
        self.tryb = PoleWyboru(lambda: [(tr, t(f"etykiety.tryb_{tr}")) for tr in etykiety.TRYBY],
                               ustawienia.pobierz(self.db, "etykiety_tryb", "obraz"))
        self.otworz_po = tk.BooleanVar(value=True)
        # Śledzenie dodane raz, przy tworzeniu zmiennych (zmienne przeżywają przebudowę okna)
        for zmienna in (self.start, *self.wlasne.values()):
            zmienna.trace_add("write", lambda *_: self._odswiez_podsumowanie())
        self._podsumowanie: ttk.Label | None = None
        self._ramka_wlasna: ttk.Frame | None = None

    # ------------------------------------------------------------------ opcje
    def _opcje_formatow(self):
        wynik = []
        for f in etykiety.FORMATY.values():
            wymiary = f"{liczba_na_tekst(float(f.szerokosc))} × {liczba_na_tekst(float(f.wysokosc))} mm"
            opis = (t("etykiety.opis_a4", liczba=f.na_stronie) if f.rodzaj == "a4"
                    else t("etykiety.opis_rolka"))
            wynik.append((f.kod, f"{f.nazwa} — {wymiary}, {opis}"))
        wynik.append(("wlasny", t("etykiety.format_wlasny")))
        return wynik

    def _format(self) -> etykiety.Format:
        if self.format.wartosc != "wlasny":
            return etykiety.FORMATY.get(self.format.wartosc, etykiety.FORMATY["avery_3474"])
        try:
            w = {k: float(v.get().replace(",", ".")) for k, v in self.wlasne.items()}
        except ValueError:
            raise BladNornicy("blad.zly_format_etykiet") from None
        return etykiety.format_wlasny(w["szerokosc"], w["wysokosc"], int(w["kolumny"]), int(w["wiersze"]),
                                      w["lewy"], w["gorny"], w["odstep_x"], w["odstep_y"])

    def _etykiety(self) -> list[etykiety.Etykieta]:
        zakres = self.zakres.get()
        if zakres == "zaznaczony":
            if self.rodzaj == "E":
                return etykiety.etykiety_egzemplarzy(self.db, [self.ident])
            if self.rodzaj == "L":
                return etykiety.etykiety_lokalizacji(self.db, [self.ident])
            return []
        if zakres == "lokalizacja":
            return etykiety.zakres(self.db, self.lok_zakresu, self.z_lokalizacjami.get())
        return etykiety.zakres(self.db, None, self.z_lokalizacjami.get())

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("okno.etykiety"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)

        # --- co drukować
        co = ttk.LabelFrame(ramka, text=t("etykiety.co"), padding=10)
        co.pack(fill="x")
        zaznaczony = None
        if self.rodzaj == "E":
            zaznaczony = egzemplarze.nazwa_wyswietlana(egzemplarze.pobierz(self.db, self.ident))
        elif self.rodzaj == "L":
            zaznaczony = lokalizacje.pobierz(self.db, self.ident)["nazwa"]
        warianty = [("zaznaczony", t("etykiety.zakres_zaznaczony", nazwa=zaznaczony or "—"), zaznaczony is not None)]
        if self.lok_zakresu is not None:
            nazwa_lok = lokalizacje.sciezki(self.db).get(self.lok_zakresu, "")
            warianty.append(("lokalizacja", t("etykiety.zakres_lokalizacja", nazwa=nazwa_lok), True))
        warianty.append(("wszystko", t("etykiety.zakres_wszystko"), True))
        for wartosc, opis, aktywny in warianty:
            ttk.Radiobutton(co, text=opis, value=wartosc, variable=self.zakres, command=self._zmiana,
                            state="normal" if aktywny else "disabled").pack(anchor="w")
        ttk.Checkbutton(co, text=t("etykiety.z_lokalizacjami"), variable=self.z_lokalizacjami,
                        command=self._zmiana).pack(anchor="w", pady=(6, 0))

        # --- format
        jak = ttk.LabelFrame(ramka, text=t("etykiety.format"), padding=10)
        jak.pack(fill="x", pady=(10, 0))
        self.format.zbuduj(jak, width=58).grid(row=0, column=0, columnspan=4, sticky="we")
        self._ramka_wlasna = ttk.Frame(jak)
        self._ramka_wlasna.grid(row=1, column=0, columnspan=4, sticky="we", pady=(8, 0))
        for i, pole in enumerate(POLA_WLASNE):
            ttk.Label(self._ramka_wlasna, text=t(f"etykiety.{pole}"), style="Pole.TLabel").grid(
                row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 6), pady=2)
            ttk.Entry(self._ramka_wlasna, textvariable=self.wlasne[pole], width=8).grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 16), pady=2)
        ttk.Label(jak, text=t("etykiety.start"), style="Pole.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(jak, from_=1, to=200, width=5, textvariable=self.start).grid(
            row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(jak, text=t("etykiety.start_podpowiedz"), style="Opis.TLabel").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=(8, 0))

        # --- kalibracja
        kal = ttk.LabelFrame(ramka, text=t("etykiety.kalibracja"), padding=10)
        kal.pack(fill="x", pady=(10, 0))
        for i, os_ in enumerate(("x", "y")):
            ttk.Label(kal, text=t(f"etykiety.przesuniecie_{os_}"), style="Pole.TLabel").grid(
                row=0, column=i * 2, sticky="w", padx=(0 if i == 0 else 16, 6))
            ttk.Entry(kal, textvariable=self.przesuniecie[os_], width=6).grid(row=0, column=i * 2 + 1, sticky="w")
        ttk.Checkbutton(kal, text=t("etykiety.ramki"), variable=self.ramki).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(kal, text=t("etykiety.kalibracja_podpowiedz"), style="Opis.TLabel", wraplength=460,
                  justify="left").grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # --- tryb druku
        druk = ttk.LabelFrame(ramka, text=t("etykiety.tryb"), padding=10)
        druk.pack(fill="x", pady=(10, 0))
        self.tryb.zbuduj(druk, width=70).pack(anchor="w", fill="x")
        ttk.Label(druk, text=t("etykiety.tryb_podpowiedz"), style="Opis.TLabel", wraplength=460,
                  justify="left").pack(anchor="w", pady=(4, 0))

        # --- podsumowanie i zapis
        self._podsumowanie = ttk.Label(ramka, style="Pole.TLabel")
        self._podsumowanie.pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(ramka, text=t("etykiety.otworz_po"), variable=self.otworz_po).pack(anchor="w", pady=(4, 0))
        przyciski = ttk.Frame(ramka)
        przyciski.pack(fill="x", pady=(12, 0))
        ttk.Button(przyciski, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        ttk.Button(przyciski, text=t("etykiety.zapisz_pdf"), style="Akcent.TButton",
                   command=self.zapisz).pack(side="right", padx=(0, 8))
        self._zmiana()

    def _zmiana(self) -> None:
        if self._ramka_wlasna is not None and self._ramka_wlasna.winfo_exists():
            if self.format.wartosc == "wlasny":
                self._ramka_wlasna.grid()
            else:
                self._ramka_wlasna.grid_remove()
        self._odswiez_podsumowanie()

    def _odswiez_podsumowanie(self) -> None:
        if self._podsumowanie is None or not self._podsumowanie.winfo_exists():
            return
        try:
            f = self._format()
            liczba = len(self._etykiety())
            start = max(1, int(self.start.get() or 1)) if f.rodzaj == "a4" else 1
            zajete = min(start, f.na_stronie) - 1 + liczba
            strony = -(-zajete // f.na_stronie) if liczba else 0
            self._podsumowanie.configure(text=t("etykiety.podsumowanie", liczba=liczba, strony=strony))
        except (BladNornicy, ValueError):
            self._podsumowanie.configure(text=t("blad.zly_format_etykiet"))

    # ------------------------------------------------------------------ zapis
    def zapisz(self, sciezka: str | None = None) -> str | None:
        try:
            f = self._format()
            lista = self._etykiety()
            przesuniecie = tuple(float(self.przesuniecie[o].get().replace(",", ".") or 0) for o in ("x", "y"))
            start = int(self.start.get() or 1)
        except ValueError:
            pokaz_blad(self, BladNornicy("blad.zly_format_etykiet"))
            return None
        except BladNornicy as blad:
            pokaz_blad(self, blad)
            return None
        tryb = self.tryb.wartosc or "obraz"
        rozszerzenie, typ = (".png", ("PNG", "*.png")) if tryb == "png" else (".pdf", ("PDF", "*.pdf"))
        if sciezka is None:
            katalog = ustawienia.pobierz(self.db, "etykiety_katalog", str(Path.home()))
            sciezka = filedialog.asksaveasfilename(
                parent=self, title=t("etykiety.zapisz_pdf"), defaultextension=rozszerzenie,
                initialdir=katalog, initialfile=f"etykiety_nornica{rozszerzenie}",
                filetypes=[typ, (t("plik.wszystkie"), "*")])
            if not sciezka:
                return None
        try:
            pliki_wynikowe = etykiety.generuj(sciezka, lista, f, start, przesuniecie, self.ramki.get(), tryb=tryb)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return None
        sciezka = str(pliki_wynikowe[0])
        # zapamiętane ustawienia drukarki
        ustawienia.zapisz(self.db, "etykiety_format", self.format.wartosc)
        ustawienia.zapisz(self.db, "etykiety_tryb", self.tryb.wartosc or "obraz")
        ustawienia.zapisz(self.db, "etykiety_katalog", str(Path(sciezka).parent))
        for os_ in ("x", "y"):
            ustawienia.zapisz(self.db, f"etykiety_przesuniecie_{os_}", self.przesuniecie[os_].get())
        for pole, zmienna in self.wlasne.items():
            ustawienia.zapisz(self.db, f"etykiety_wlasny_{pole}", zmienna.get())
        if self.otworz_po.get():
            try:
                pliki.otworz(sciezka)
            except Exception as blad:   # noqa: BLE001
                pokaz_blad(self, blad)
        return sciezka
