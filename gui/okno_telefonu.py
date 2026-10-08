# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Telefon jako skaner”: uruchomienie serwera, kod QR do sparowania,
instrukcja instalacji certyfikatu na iPhonie, podpowiedź o zaporze sieciowej.

Serwer należy do okna głównego (glowne.serwer), nie do tego okna: zamknięcie
okna nie przerywa skanowania; serwer kończy pracę razem z programem.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import konfiguracja
from baza.repozytoria import ustawienia
from gui import styl
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleWyboru
from i18n.tlumacz import t
from uslugi import certyfikaty, etykiety
from uslugi.serwer_mobilny import (PORT_DOMYSLNY, SerwerMobilny, adresy_lokalne, generuj_klucz,
                                   wskazowka_zapory)

BOK_QR = 230


class OknoTelefonu(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.adresy = adresy_lokalne()
        self.adres = PoleWyboru(lambda: [(a, a) for a in self.adresy],
                                ustawienia.pobierz(self.db, "serwer_adres") if
                                ustawienia.pobierz(self.db, "serwer_adres") in self.adresy else self.adresy[0],
                                przy_zmianie=lambda _w: self.przebuduj())

    # ------------------------------------------------------------------ stan
    def _klucz(self) -> str:
        klucz = ustawienia.pobierz(self.db, "serwer_klucz")
        if not klucz:
            klucz = generuj_klucz()
            ustawienia.zapisz(self.db, "serwer_klucz", klucz)
        return klucz

    @property
    def serwer(self) -> SerwerMobilny | None:
        return self.glowne.serwer

    def uruchom(self, port: int | None = None) -> None:
        try:
            if self.glowne.serwer is None:
                self.glowne.serwer = SerwerMobilny(self.glowne.most, self._klucz())
            pliki_cert = None
            if certyfikaty.dostepne():
                pliki_cert = certyfikaty.przygotuj(konfiguracja.katalog_danych() / "certyfikat", self.adresy)
            port = port if port is not None else int(ustawienia.pobierz(self.db, "serwer_port", PORT_DOMYSLNY))
            self.glowne.serwer.uruchom(port, pliki_cert)
            ustawienia.zapisz(self.db, "serwer_adres", self.adres.wartosc)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
        self.przebuduj()
        self.glowne._pokaz_stan_skanera()

    def zatrzymaj(self) -> None:
        if self.serwer is not None:
            self.serwer.zatrzymaj()
        self.przebuduj()
        self.glowne._pokaz_stan_skanera()

    def nowy_klucz(self) -> None:
        """Odłącza wszystkie sparowane telefony — każdy musi zeskanować nowy kod."""
        klucz = generuj_klucz()
        ustawienia.zapisz(self.db, "serwer_klucz", klucz)
        if self.serwer is not None:
            self.serwer.ustaw_klucz(klucz)
        self.przebuduj()

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("okno.telefon"))
        ramka = ttk.Frame(self, padding=16)
        ramka.pack(fill="both", expand=True)
        dziala = self.serwer is not None and self.serwer.dziala

        if not dziala:
            ttk.Label(ramka, text=t("telefon.wstep"), wraplength=460, justify="left").pack(anchor="w")
            if not certyfikaty.dostepne():
                ttk.Label(ramka, text=t("telefon.bez_szyfrowania"), style="Opis.TLabel", wraplength=460,
                          justify="left").pack(anchor="w", pady=(8, 0))
            wybor = ttk.Frame(ramka)
            wybor.pack(fill="x", pady=(12, 0))
            ttk.Label(wybor, text=t("telefon.adres"), style="Pole.TLabel").pack(side="left")
            self.adres.zbuduj(wybor, width=18).pack(side="left", padx=(8, 0))
            przyciski = ttk.Frame(ramka)
            przyciski.pack(fill="x", pady=(16, 0))
            ttk.Button(przyciski, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
            ttk.Button(przyciski, text=t("telefon.uruchom"), style="Akcent.TButton",
                       command=self.uruchom).pack(side="right", padx=(0, 8))
            return

        ip = self.adres.wartosc or self.adresy[0]
        adres = self.serwer.adres_parowania(ip)
        gora = ttk.Frame(ramka)
        gora.pack(fill="x")
        plotno = tk.Canvas(gora, width=BOK_QR, height=BOK_QR, highlightthickness=0, background="#FFFFFF")
        plotno.pack(side="left", anchor="n")
        self._rysuj_qr(plotno, adres)
        prawa = ttk.Frame(gora, padding=(16, 0, 0, 0))
        prawa.pack(side="left", fill="both", expand=True)
        ttk.Label(prawa, text=t("telefon.dziala", port=self.serwer.port), style="Naglowek.TLabel").pack(anchor="w")
        ttk.Label(prawa, text=t("telefon.kroki"), wraplength=300, justify="left").pack(anchor="w", pady=(8, 0))
        wybor = ttk.Frame(prawa)
        wybor.pack(anchor="w", pady=(10, 0))
        ttk.Label(wybor, text=t("telefon.adres"), style="Pole.TLabel").pack(side="left")
        self.adres.zbuduj(wybor, width=16).pack(side="left", padx=(8, 0))
        ttk.Label(prawa, text=t("telefon.adres_podpowiedz"), style="Opis.TLabel", wraplength=300,
                  justify="left").pack(anchor="w", pady=(4, 0))

        if self.serwer.https:
            iphone = ttk.LabelFrame(ramka, text=t("telefon.iphone_tytul"), padding=10)
            iphone.pack(fill="x", pady=(14, 0))
            ttk.Label(iphone, text=t("telefon.iphone_kroki", adres=self.serwer.adres_certyfikatu(ip)),
                      wraplength=480, justify="left").pack(anchor="w")
        else:
            ttk.Label(ramka, text=t("telefon.bez_szyfrowania"), style="Opis.TLabel", wraplength=480,
                      justify="left").pack(anchor="w", pady=(14, 0))

        zapora = ttk.LabelFrame(ramka, text=t("telefon.zapora_tytul"), padding=10)
        zapora.pack(fill="x", pady=(10, 0))
        klucz, pola = wskazowka_zapory(self.serwer.port)
        tekst = tk.Text(zapora, height=3, wrap="word", relief="flat", borderwidth=0, highlightthickness=0,
                        background=styl.KOLORY["tlo"], font=self.glowne.czcionki["maly"])
        tekst.insert("1.0", t(klucz, **pola))
        tekst.configure(state="disabled")      # tylko do odczytu, ale polecenie da się skopiować
        tekst.pack(fill="x")

        przyciski = ttk.Frame(ramka)
        przyciski.pack(fill="x", pady=(14, 0))
        ttk.Button(przyciski, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        ttk.Button(przyciski, text=t("telefon.zatrzymaj"), command=self.zatrzymaj).pack(side="right", padx=(0, 8))
        ttk.Button(przyciski, text=t("telefon.nowy_klucz"), command=self.nowy_klucz).pack(side="left")

    @staticmethod
    def _rysuj_qr(plotno: tk.Canvas, tekst: str) -> None:
        macierz = etykiety.macierz_qr(tekst)
        margines = 3
        modul = BOK_QR / (len(macierz) + 2 * margines)
        for r, wiersz in enumerate(macierz):
            for k, ciemny in enumerate(wiersz):
                if ciemny:
                    x0, y0 = (k + margines) * modul, (r + margines) * modul
                    plotno.create_rectangle(x0, y0, x0 + modul, y0 + modul, fill="#000000", outline="",
                                            tags=("modul",))
