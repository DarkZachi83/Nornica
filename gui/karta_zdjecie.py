# SPDX-License-Identifier: GPL-3.0-or-later
"""Zdjęcie główne nad zakładkami i kod QR na karcie Ogólne.

Klasa pomocnicza panelu szczegółów (gui/szczegoly.py): korzysta z jego
atrybutów — glowne, db, notatnik, gora, rodzic — i nie działa samodzielnie.
"""
from __future__ import annotations

import base64
import tkinter as tk
from tkinter import ttk

from gui import styl
from i18n.tlumacz import t
from konfiguracja import KATALOG_PROGRAMU
from uslugi import etykiety, pliki

ROZMIAR_ZDJECIA = (280, 210)   # pełny rozmiar ramki zdjęcia głównego; zgodny z narzedzia/generuj_grafiki.py
MIEJSCE_NA_DANE = 320          # szerokość nazwy i przycisków (2 w rzędzie) obok zdjęcia
BOK_QR = (96, 170)             # najmniejszy i największy bok kodu QR na karcie, px
MIEJSCE_OBOK_QR = 400          # szerokość etykiet i wartości obok kodu QR

class ZdjecieIQr:
    """Ramka zdjęcia głównego (skalowana do panelu) i kod QR rysowany z prostokątów."""

    def _rozmiar_zdjecia(self, szerokosc_panelu: int) -> tuple[int, int]:
        """Ramka skalowana do szerokości panelu: obok niej musi zostać miejsce na
        nazwę i przyciski (MIEJSCE_NA_DANE). Od 45% do 100% pełnego rozmiaru."""
        wolne = szerokosc_panelu - MIEJSCE_NA_DANE
        skala = min(1.0, max(0.45, wolne / ROZMIAR_ZDJECIA[0]))
        return round(ROZMIAR_ZDJECIA[0] * skala), round(ROZMIAR_ZDJECIA[1] * skala)

    def _usun_zdjecie(self) -> None:
        stare = self._ramka_zdjecia.get("plotno")
        if stare is not None and stare.winfo_exists():
            stare.destroy()
        self._ramka_zdjecia = {}
        self.zdjecie_na_karcie = None
        self._zawin_naglowek(self.rodzic.winfo_width(), 0)

    def _zawin_naglowek(self, szerokosc_panelu: int, szerokosc_zdjecia: int) -> None:
        if szerokosc_panelu > 1:
            zawijanie = max(180, szerokosc_panelu - szerokosc_zdjecia - 30)
            self.naglowek.configure(wraplength=zawijanie)
            self.podtytul.configure(wraplength=zawijanie)

    def _zdjecie_glowne(self, egz_id: int, szerokosc_panelu: int | None = None) -> None:
        """Ramka zdjęcia głównego w górnej części panelu, widoczna przy każdej
        zakładce. Bez wybranego zdjęcia: przygaszona nornica z napisem
        „BRAK ZDJĘCIA” / „NO IMAGE” w bieżącym języku; kliknięcie przenosi wtedy
        do zakładki Zasoby, gdzie zdjęcie się wybiera."""
        szerokosc_panelu = szerokosc_panelu or self.rodzic.winfo_width()
        if szerokosc_panelu <= 1:                        # panel jeszcze nie narysowany
            szerokosc_panelu = self.glowne.winfo_width() // 2
        szerokosc, wysokosc = self._rozmiar_zdjecia(szerokosc_panelu)
        stare = self._ramka_zdjecia.get("plotno")   # PRZED podmianą słownika — inaczej stara ramka zostaje pod nową
        if stare is not None and stare.winfo_exists():
            stare.destroy()
        self._ramka_zdjecia = {"egz_id": egz_id, "rozmiar": (szerokosc, wysokosc)}
        plotno = tk.Canvas(self.gora, width=szerokosc, height=wysokosc, highlightthickness=1,
                           highlightbackground=styl.KOLORY["przygaszony"], borderwidth=0,
                           background=styl.KOLORY["panel"], cursor="hand2")
        plotno.grid(row=0, column=1, sticky="ne", padx=(12, 0), pady=(4, 0))
        self._ramka_zdjecia["plotno"] = plotno
        self._zawin_naglowek(szerokosc_panelu, szerokosc)
        zdjecie = pliki.zdjecie_glowne(self.db, egz_id)
        dane = pliki.podglad(self.db, zdjecie, szerokosc, wysokosc) if zdjecie is not None else None
        obraz = self._obraz(dane)
        if obraz is not None:
            plotno.create_image(szerokosc // 2, wysokosc // 2, image=obraz, anchor="center")
            plotno.bind("<Button-1>", lambda _e: self._otworz(egz_id, zdjecie))
            self.zdjecie_na_karcie = zdjecie["id"]
            return
        self.zdjecie_na_karcie = None
        # obrazek zastępczy: skalowany przez Pillow, bez niej wyśrodkowany w pełnym rozmiarze
        sciezka = KATALOG_PROGRAMU / "zasoby" / "brak_zdjecia.png"
        zastepczy = self._obraz(pliki.podglad_pliku(sciezka, szerokosc, wysokosc)) or self.glowne.grafika("brak_zdjecia")
        if zastepczy is not None:
            plotno.create_image(szerokosc // 2, wysokosc // 2, image=zastepczy, anchor="center")
        pas = max(26, round(38 * wysokosc / ROZMIAR_ZDJECIA[1]))
        plotno.create_rectangle(0, wysokosc - pas, szerokosc + 2, wysokosc + 2,
                                fill=styl.KOLORY["tusz"], outline="")
        plotno.create_text(szerokosc // 2, wysokosc - pas // 2, text=t("zdjecie.brak"),
                           fill=styl.KOLORY["panel"], font=self.glowne.czcionki["pogrubiona"],
                           tags=("napis_braku",))
        plotno.bind("<Button-1>", lambda _e: self.notatnik.select(3))

    def _obraz(self, dane: bytes | None) -> tk.PhotoImage | None:
        if not dane:
            return None
        try:
            obraz = tk.PhotoImage(master=self.glowne, data=base64.b64encode(dane))
        except tk.TclError:
            return None
        self._miniatury.append(obraz)       # referencja, inaczej tkinter zgubi obraz
        return obraz

    def _dopasuj_zdjecie(self, szerokosc_panelu: int) -> None:
        """Przy zmianie szerokości panelu przerysowuje ramkę zdjęcia, gdy jej
        rozmiar powinien się zmienić (próg 8 px — bez migotania przy drobnych zmianach)."""
        stan = self._ramka_zdjecia
        if not stan.get("plotno") or not stan["plotno"].winfo_exists():
            self._zawin_naglowek(szerokosc_panelu, 0)
            return
        nowy = self._rozmiar_zdjecia(szerokosc_panelu)
        if abs(nowy[0] - stan["rozmiar"][0]) >= 8:
            self._zdjecie_glowne(stan["egz_id"], szerokosc_panelu)
        else:
            self._zawin_naglowek(szerokosc_panelu, stan["rozmiar"][0])

    # ------------------------------------------------------------------ kod QR
    @staticmethod
    def _bok_qr(szerokosc_karty: int) -> int:
        """Bok kodu QR dopasowany do karty: obok musi zostać miejsce na dane."""
        return max(BOK_QR[0], min(BOK_QR[1], szerokosc_karty - MIEJSCE_OBOK_QR))

    def _kod_qr(self, karta: ttk.Frame, tekst: str | None, wierszy: int,
                szerokosc_karty: int | None = None) -> None:
        """Kod QR kodu inwentarzowego lub kodu lokalizacji, z kodem pod spodem.
        Rysowany z prostokątów — nie wymaga Pillow. Kliknięcie: druk etykiety."""
        if not tekst:
            return
        szerokosc_karty = szerokosc_karty or karta.winfo_width()
        if szerokosc_karty <= 1:
            szerokosc_karty = self.notatnik.winfo_width() - 20
        bok = self._bok_qr(szerokosc_karty)
        stare = self._qr.get("plotno")             # PRZED podmianą stanu — lekcja z ramki zdjęcia
        if stare is not None and stare.winfo_exists():
            stare.destroy()
        self._qr = {"karta": karta, "tekst": tekst, "wierszy": wierszy, "bok": bok}
        wysokosc_podpisu = 20
        plotno = tk.Canvas(karta, width=bok, height=bok + wysokosc_podpisu, highlightthickness=0,
                           borderwidth=0, background=styl.KOLORY["tlo"], cursor="hand2")
        plotno.grid(row=0, column=2, rowspan=max(wierszy, 1), sticky="ne", padx=(16, 0))
        self._qr["plotno"] = plotno
        try:
            macierz = etykiety.macierz_qr(tekst)
        except Exception:   # noqa: BLE001 — brak biblioteki qrcode: sam napis i podpowiedź
            plotno.create_text(bok // 2, bok // 2, text=t("etykiety.brak_qrcode_krotko"), width=bok - 10,
                               fill=styl.KOLORY["przygaszony"], justify="center")
            return
        margines = 2                                # moduły strefy ciszy
        modul = bok / (len(macierz) + 2 * margines)
        plotno.create_rectangle(0, 0, bok, bok, fill="#FFFFFF", outline="")
        for r, wiersz in enumerate(macierz):
            for k, ciemny in enumerate(wiersz):
                if ciemny:
                    x0, y0 = (k + margines) * modul, (r + margines) * modul
                    plotno.create_rectangle(x0, y0, x0 + modul, y0 + modul, fill="#000000", outline="",
                                            tags=("modul",))
        plotno.create_text(bok // 2, bok + wysokosc_podpisu // 2, text=tekst,
                           font=self.glowne.czcionki["pogrubiona"], fill=styl.KOLORY["tusz"], tags=("podpis",))
        plotno.bind("<Button-1>", lambda _e: self.glowne.drukuj_etykiety())

    def _dopasuj_qr(self, szerokosc_karty: int) -> None:
        stan = self._qr
        if not stan.get("plotno") or not stan["plotno"].winfo_exists():
            return
        if abs(self._bok_qr(szerokosc_karty) - stan["bok"]) >= 8:
            self._kod_qr(stan["karta"], stan["tekst"], stan["wierszy"], szerokosc_karty)
