# SPDX-License-Identifier: GPL-3.0-or-later
"""Karta szczegółów zaznaczonego elementu.

Panel jest „widokiem”: przy każdej zmianie zaznaczenia czyści treść
i buduje ją od nowa z bazy. Nie przechowuje stanu, który musiałby
przeżyć przebudowę okna — zakładkę pamięta StanWidoku okna głównego.
"""
from __future__ import annotations

import base64
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from baza.enumy import etykieta
from baza.repozytoria import egzemplarze, lokalizacje, slowniki
from baza.repozytoria import ustawienia
from baza.repozytoria.szczegoly import (cel_powiazania, zasoby_dziedziczone, zdarzenia,
                                        zlacza_egzemplarza)
from gui import styl
from gui.bazowe import pokaz_blad
from konfiguracja import KATALOG_PROGRAMU
from gui.model_drzewa import WEZEL_BEZ_LOKALIZACJI, rozbierz_iid
from i18n.tlumacz import nazwa, t
from uslugi import etykiety, pliki
from wyjatki import BladNornicy
from uslugi.formatowanie import data_lokalna, liczba_na_tekst, minor_na_tekst, pojemnosc_na_tekst

# Linux: wzorce plików w oknie wyboru rozróżniają wielkość liter — aparaty
# zapisują „IMG_0001.JPG”, więc wielkie litery muszą być na liście.
WZORCE_ZDJEC = " ".join(f"*{r} *{r.upper()}" for r in sorted(pliki.ROZSZERZENIA_ZDJEC))
SKALA_PASKA = 2          # miniatury 160 px w bazie, w pasku pokazane w połowie
ROZMIAR_ZDJECIA = (280, 210)   # pełny rozmiar ramki zdjęcia głównego; zgodny z narzedzia/generuj_grafiki.py
MIEJSCE_NA_DANE = 320          # szerokość nazwy i przycisków (2 w rzędzie) obok zdjęcia
MIN_KOLUMNA_WARTOSCI = 120     # minimalna szerokość kolumny wartości na karcie Ogólne
BOK_QR = (96, 170)             # najmniejszy i największy bok kodu QR na karcie, px
MIEJSCE_OBOK_QR = 400          # szerokość etykiet i wartości obok kodu QR


def skroc_adres(adres: str, limit: int = 30) -> str:
    """'https://www.mit.krakow.pl/zbior/mim-1726-vii-142-2/' -> 'www.mit.krakow.pl/…'.
    Adres bez spacji nie zawija się w naturalnym miejscu, więc długi adres
    pokazujemy jako domenę; kliknięcie otwiera pełny adres."""
    from urllib.parse import urlsplit
    czesci = urlsplit(adres)
    tekst = (czesci.netloc + czesci.path).rstrip("/") or adres
    if len(tekst) <= limit:
        return tekst
    return f"{czesci.netloc}/…" if czesci.netloc else tekst[:limit - 1] + "…"

ZAKLADKI = ("zakladka.ogolne", "zakladka.parametry", "zakladka.zlacza",
            "zakladka.zasoby", "zakladka.historia")


class PanelSzczegolow:
    def __init__(self, glowne, rodzic: ttk.Frame):
        self.glowne = glowne
        self.db = glowne.db
        # Górna część panelu: nazwa, podtytuł i przyciski po lewej, zdjęcie główne
        # po prawej. Zdjęcie jest NAD zakładkami, więc widać je przy każdej z nich.
        self.rodzic = rodzic
        self.gora = ttk.Frame(rodzic)
        self.gora.pack(fill="x", pady=(0, 8))
        self.gora.columnconfigure(0, weight=1)
        lewa = ttk.Frame(self.gora)
        lewa.grid(row=0, column=0, sticky="nw")
        self.naglowek = ttk.Label(lewa, style="Naglowek.TLabel", wraplength=420, justify="left")
        self.naglowek.pack(anchor="w", pady=(4, 2))
        self.podtytul = ttk.Label(lewa, style="Opis.TLabel", wraplength=420, justify="left")
        self.podtytul.pack(anchor="w")
        self.akcje = ttk.Frame(lewa)
        self.akcje.pack(fill="x", pady=(10, 0))
        rodzic.bind("<Configure>", lambda e: self._dopasuj_zdjecie(e.width))
        self.notatnik = ttk.Notebook(rodzic)
        self.notatnik.pack(fill="both", expand=True)
        self.karty = []
        self._miniatury: list[tk.PhotoImage] = []   # referencje: bez nich tkinter zgubi obrazy
        self._zawijane: list[ttk.Label] = []          # wartości zawijane do szerokości karty
        self._wybor_glownego: list[tk.IntVar] = []    # zmienne pól „Główne” w pasku miniatur
        self.zdjecie_na_karcie: int | None = None
        self._ramka_zdjecia: dict = {}
        self._qr: dict = {}
        for klucz in ZAKLADKI:
            karta = ttk.Frame(self.notatnik, padding=10)
            self.notatnik.add(karta, text=t(klucz))
            self.karty.append(karta)
        # Kolumna wartości nigdy nie znika do zera przy skrajnie wąskim oknie.
        self.karty[0].columnconfigure(1, minsize=MIN_KOLUMNA_WARTOSCI)
        # Wiązanie PO utworzeniu kart — wcześniej lista była pusta i zmiana
        # rozmiaru okna nie docierała do zawijania.
        for karta in self.karty:
            karta.bind("<Configure>", lambda e, k=karta: self._dopasuj_zawijanie(k, e.width))

    def zakladka(self) -> int:
        try:
            return self.notatnik.index("current")
        except tk.TclError:
            return 0

    # ------------------------------------------------------------------ wejście
    def pokaz(self, iid: str | None, zakladka: int = 0) -> None:
        for kontener in (self.akcje, *self.karty):
            for dziecko in kontener.winfo_children():
                dziecko.destroy()
        self._usun_zdjecie()           # lokalizacja i pusty wybór nie mają zdjęcia
        self._qr = {}                  # płótno kodu QR zniknęło razem z dziećmi karty
        self._miniatury = []
        self._zawijane = []
        self._wybor_glownego = []
        for karta in self.karty:                    # wagi wierszy z poprzedniego elementu
            for wiersz in range(karta.grid_size()[1]):
                karta.rowconfigure(wiersz, weight=0)
        rodzaj, ident = rozbierz_iid(iid)
        if rodzaj == "E" and egzemplarze.pobierz(self.db, ident):
            self._zdjecie_glowne(ident)
            self._egzemplarz(ident)
            stan = "normal"
        elif rodzaj == "L" and lokalizacje.pobierz(self.db, ident):
            self._lokalizacja(ident)
            stan = "disabled"
        elif rodzaj == WEZEL_BEZ_LOKALIZACJI:
            self._bez_lokalizacji()
            stan = "disabled"
        else:
            self._pusto()
            stan = "disabled"
        for i in range(1, len(self.karty)):
            self.notatnik.tab(i, state=stan)
        self.notatnik.select(zakladka if stan == "normal" else 0)
        self.glowne.after_idle(lambda: [self._dopasuj_zawijanie(k, k.winfo_width()) for k in self.karty
                                        if k.winfo_exists()])

    def _dopasuj_zawijanie(self, karta: ttk.Frame, szerokosc: int) -> None:
        """Zawijanie wartości do faktycznej szerokości karty. Wiersze obok zdjęcia
        głównego (columnspan 1) mają mniej miejsca niż wiersze pod nim."""
        if szerokosc <= 1:
            return
        if karta is self.karty[0]:
            self._dopasuj_qr(szerokosc)
        try:
            kolumna_etykiet = karta.grid_bbox(0, 0)[2]
            kolumna_zdjecia = karta.grid_bbox(2, 0)[2]
        except tk.TclError:
            kolumna_etykiet = kolumna_zdjecia = 0
        szeroko = max(140, szerokosc - kolumna_etykiet - 40)
        waskie = max(120, szeroko - kolumna_zdjecia)
        for etykieta_ in self._zawijane:
            if etykieta_.winfo_exists() and etykieta_.master is karta:
                rozpietosc = int(etykieta_.grid_info().get("columnspan", 1))
                etykieta_.configure(wraplength=szeroko if rozpietosc > 1 else waskie)

    # ---------------------------------------------------------------- pomocnicze
    def _przycisk(self, klucz: str, polecenie, akcent: bool = False) -> None:
        """Przyciski w siatce po dwa: obok nich stoi zdjęcie główne, więc muszą
        zmieścić się w wąskiej kolumnie."""
        indeks = len(self.akcje.winfo_children())
        ttk.Button(self.akcje, text=t(klucz), command=polecenie,
                   style="Akcent.TButton" if akcent else "TButton").grid(
            row=indeks // 2, column=indeks % 2, sticky="we", padx=(0, 6), pady=(0, 4))

    def _tabela_pol(self, karta: ttk.Frame, wiersze: list[tuple[str, str]], start: int = 0,
                    rozpietosc: int = 1) -> int:
        """Pary etykieta–wartość. rozpietosc=2: wartość zajmuje też kolumnę zdjęcia
        (wiersze pod zdjęciem głównym)."""
        for i, (etykieta_, wartosc) in enumerate(wiersze, start):
            ttk.Label(karta, text=etykieta_, style="Pole.TLabel").grid(
                row=i, column=0, sticky="nw", padx=(0, 14), pady=2)
            pole = ttk.Label(karta, text=wartosc or "—", wraplength=320, justify="left")
            pole.grid(row=i, column=1, columnspan=rozpietosc, sticky="w", pady=2)
            self._zawijane.append(pole)
        return start + len(wiersze)

    @staticmethod
    def _lista(karta: ttk.Frame, kolumny: list[tuple[str, int]], wiersze: list[tuple],
               pusto_klucz: str) -> None:
        if not wiersze:
            ttk.Label(karta, text=t(pusto_klucz), style="Opis.TLabel", wraplength=380,
                      justify="left").pack(anchor="w")
            return
        lista = ttk.Treeview(karta, columns=[str(i) for i in range(len(kolumny))],
                             show="headings", height=8)
        for i, (naglowek, szerokosc) in enumerate(kolumny):
            lista.heading(str(i), text=naglowek, anchor="w")
            lista.column(str(i), width=szerokosc, stretch=i == len(kolumny) - 1)
        for wiersz in wiersze:
            lista.insert("", "end", values=wiersz)
        lista.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- warianty
    def _pusto(self) -> None:
        self.naglowek.configure(text=t("aplikacja.nazwa"))
        self.podtytul.configure(text="")
        ttk.Label(self.karty[0], text=t("pusty.wybierz"), wraplength=380, justify="left").pack(anchor="w")
        if not lokalizacje.wszystkie(self.db):
            self._przycisk("akcja.pierwsza_lokalizacja", self.glowne.nowa_lokalizacja, akcent=True)
        self._przycisk("akcja.nowy_egzemplarz", self.glowne.nowy_egzemplarz)

    def _bez_lokalizacji(self) -> None:
        self.naglowek.configure(text=t("lokalizacja.brak"))
        self.podtytul.configure(text="")
        ttk.Label(self.karty[0], text=t("pusty.bez_lokalizacji"), wraplength=380,
                  justify="left").pack(anchor="w")

    def _lokalizacja(self, lok_id: int) -> None:
        l = lokalizacje.pobierz(self.db, lok_id)
        sciezka = lokalizacje.sciezki(self.db).get(lok_id, l["nazwa"])
        self.naglowek.configure(text=l["nazwa"])
        self.podtytul.configure(text=sciezka)
        self._przycisk("akcja.edytuj", lambda: self.glowne.edytuj_lokalizacje(lok_id))
        self._przycisk("akcja.dodaj_tutaj", lambda: self.glowne.nowy_egzemplarz(lokalizacja_id=lok_id),
                       akcent=True)
        self._przycisk("akcja.podlokalizacja", lambda: self.glowne.nowa_lokalizacja(rodzic_id=lok_id))
        self._przycisk("akcja.usun", lambda: self.glowne.usun_lokalizacje(lok_id))
        liczba = self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE lokalizacja_id = ?",
                                 (lok_id,)).fetchone()[0]
        self._kod_qr(self.karty[0], l["kod_etykiety"], 4)
        self._tabela_pol(self.karty[0], [
            (t("pole.typ"), etykieta("lokalizacja.typ", l["typ"]) if l["typ"] else ""),
            (t("pole.kod_etykiety"), l["kod_etykiety"]),
            (t("pole.liczba_egzemplarzy"), str(liczba)),
            (t("pole.uwagi"), l["uwagi"]),
        ])

    def _egzemplarz(self, egz_id: int) -> None:
        e = egzemplarze.pobierz(self.db, egz_id)
        self.naglowek.configure(text=egzemplarze.nazwa_wyswietlana(e))
        self.podtytul.configure(text=" ".join(c for c in (e["kod_inwentarzowy"],
                                                          nazwa(e["kategoria_nazwy"])) if c))
        self._przycisk("akcja.edytuj", lambda: self.glowne.edytuj_egzemplarz(egz_id), akcent=True)
        if e["ilosc"] == 1:
            self._przycisk("akcja.dodaj_czesc", lambda: self.glowne.nowy_egzemplarz(rodzic_id=egz_id))
        else:
            self._przycisk("akcja.wydziel", lambda: self.glowne.wydziel_z_partii(egz_id))
        if e["model_id"]:
            self._przycisk("akcja.edytuj_model", lambda: self.glowne.edytuj_model(e["model_id"]))
        self._przycisk("akcja.usun", lambda: self.glowne.usun_egzemplarz(egz_id))

        # --- Ogólne
        if e["rodzic_id"]:
            rodzic = egzemplarze.pobierz(self.db, e["rodzic_id"])
            miejsce = t("pole.zamontowany_w_wartosc", nazwa=egzemplarze.nazwa_wyswietlana(rodzic),
                        pozycja=e["pozycja_montazu"] or "—")
        else:
            miejsce = (lokalizacje.sciezki(self.db).get(e["lokalizacja_id"])
                       if e["lokalizacja_id"] else t("lokalizacja.brak"))
        model = " ".join(c for c in (e["producent"], e["model_nazwa"]) if c)
        wiersze = [
            (t("pole.model"), f"{model} ({e['numer_czesci']})" if e["numer_czesci"] else model),
            (t("pole.status"), nazwa(e["status_nazwy"])),
            (t("pole.stan_wizualny"),
             etykieta("egzemplarz.stan_wizualny", e["stan_wizualny"]) if e["stan_wizualny"] else ""),
            (t("pole.miejsce"), miejsce),
            (t("pole.numer_seryjny"), e["numer_seryjny"]),
            (t("pole.rewizja"), e["rewizja"]),
            (t("pole.ilosc"), str(e["ilosc"])),
            (t("pole.uwagi"), e["uwagi"]),
        ]
        wiersz = self._tabela_pol(self.karty[0], wiersze)
        self._kod_qr(self.karty[0], e["kod_inwentarzowy"], len(wiersze))
        if e["data_nabycia"] or e["zrodlo_nabycia"] or e["cena_minor"] is not None:
            ttk.Separator(self.karty[0]).grid(row=wiersz, column=0, columnspan=3, sticky="we", pady=8)
            cena = ""
            if e["cena_minor"] is not None:
                miejsca = slowniki.miejsca_dziesietne(self.db, e["waluta_kod"])
                cena = f"{minor_na_tekst(e['cena_minor'], miejsca)} {e['waluta_kod']}"
            wiersz = self._tabela_pol(self.karty[0], [
                (t("pole.data_nabycia"), e["data_nabycia"]),
                (t("pole.zrodlo_nabycia"), e["zrodlo_nabycia"]),
                (t("pole.cena"), cena),
            ], wiersz + 1, rozpietosc=2)
        if e["model_id"]:
            wiersz = self._informacje_o_modelu(self.karty[0], e["model_id"], wiersz)
        ttk.Label(self.karty[0], text=t("pole.zmieniono_wartosc", data=data_lokalna(e["zmieniono"])),
                  style="Opis.TLabel").grid(row=wiersz + 1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # --- Parametry: model + nadpisania egzemplarza
        z_modelu = json.loads(e["model_atrybuty"] or "{}")
        wlasne = json.loads(e["atrybuty"] or "{}")
        szablon = slowniki.szablon(self.db, e["kat_id"])
        znane = {p["kod"] for p in szablon}
        wiersze = []
        for pole in szablon:
            if pole["kod"] in wlasne or pole["kod"] in z_modelu:
                wartosc = wlasne.get(pole["kod"], z_modelu.get(pole["kod"]))
                tekst = liczba_na_tekst(wartosc)
                if isinstance(wartosc, bool):
                    tekst = t("ogolne.tak") if wartosc else t("ogolne.nie")
                elif pole.get("typ") == "pojemnosc" and isinstance(wartosc, (int, float)):
                    tekst = pojemnosc_na_tekst(wartosc)          # 128 B, 64 KB, 4 MB
                if pole.get("jednostka"):
                    tekst = f"{tekst} {pole['jednostka']}"
                if pole["kod"] in wlasne and pole["kod"] in z_modelu:
                    tekst = f"{tekst}  ({t('parametry.zmienione')})"
                wiersze.append((nazwa(pole["nazwy"]), tekst))
        for kod, wartosc in {**z_modelu, **wlasne}.items():
            if kod not in znane:
                wiersze.append((kod, liczba_na_tekst(wartosc)))
        if wiersze:
            self._tabela_pol(self.karty[1], wiersze)
        else:
            ttk.Label(self.karty[1], text=t("pusty.parametry"), style="Opis.TLabel").pack(anchor="w")

        # --- Złącza
        ttk.Button(self.karty[2], text=t("akcja.edytuj_zlacza"),
                   command=lambda: self.glowne.edytuj_egzemplarz(egz_id, zakladka=2)).pack(anchor="w", pady=(0, 8))
        self._lista(self.karty[2],
                    [(t("kolumna.rola"), 90), (t("kolumna.zlacze"), 220), (t("kolumna.ilosc"), 60)],
                    [(etykieta("model_zlacze.rola", z["rola"]),
                      nazwa(z["nazwy"]) + (f"  ({t('parametry.zmienione')})" if z["zmienione"] else ""),
                      z["ilosc"]) for z in zlacza_egzemplarza(self.db, egz_id)],
                    "pusty.zlacza")

        # --- Zasoby (z dziedziczeniem po modelu i kategorii)
        self._zasoby(self.karty[3], egz_id)

        # --- Historia
        self._historia(self.karty[4], egz_id)

    # ---------------------------------------------------------------- model
    def _informacje_o_modelu(self, karta: ttk.Frame, model_id: int, wiersz: int) -> int:
        """Lata produkcji, strona źródłowa i opis modelu — widoczne przy każdym egzemplarzu.
        Opis jest ostatni: przewijane pole zajmuje całe wolne miejsce karty."""
        from baza.repozytoria import modele
        m = modele.pobierz(self.db, model_id)
        if not (m["rok_od"] or m["rok_do"] or m["opis"] or m["zrodlo_url"]):
            return wiersz
        ttk.Separator(karta).grid(row=wiersz, column=0, columnspan=3, sticky="we", pady=8)
        wiersz += 1
        if m["rok_od"] or m["rok_do"]:
            lata = f"{m['rok_od'] or '?'}–{m['rok_do'] or '?'}" if m["rok_od"] != m["rok_do"] else str(m["rok_od"])
            wiersz = self._tabela_pol(karta, [(t("pole.produkcja"), lata)], wiersz, rozpietosc=2)
        if m["zrodlo_url"]:
            ttk.Label(karta, text=t("pole.zrodlo_url"), style="Pole.TLabel").grid(
                row=wiersz, column=0, sticky="nw", padx=(0, 14), pady=2)
            odnosnik = ttk.Label(karta, text=skroc_adres(m["zrodlo_url"]), style="Odnosnik.TLabel",
                                 cursor="hand2", wraplength=320, justify="left")
            odnosnik.grid(row=wiersz, column=1, columnspan=2, sticky="w", pady=2)
            odnosnik.bind("<Button-1>", lambda _e, u=m["zrodlo_url"]: self._otworz_adres(u))
            self._zawijane.append(odnosnik)
            wiersz += 1
        if m["opis"]:
            ttk.Label(karta, text=t("pole.opis_modelu"), style="Pole.TLabel").grid(
                row=wiersz, column=0, sticky="nw", padx=(0, 14), pady=2)
            self._tekst_przewijany(karta, m["opis"]).grid(row=wiersz, column=1, columnspan=2,
                                                          sticky="nsew", pady=2)
            karta.rowconfigure(wiersz, weight=1)     # opis rośnie razem z oknem
            karta.columnconfigure(1, weight=1)
            wiersz += 1
        return wiersz

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

    def _tekst_przewijany(self, rodzic: ttk.Frame, tekst: str) -> ttk.Frame:
        """Długi tekst tylko do odczytu: zawija się do szerokości, przewija pionowo,
        da się go zaznaczyć i skopiować."""
        ramka = ttk.Frame(rodzic)
        pole = tk.Text(ramka, wrap="word", height=4, width=30, relief="flat", borderwidth=0,
                       highlightthickness=0, padx=0, pady=0, cursor="arrow",
                       background=styl.KOLORY["tlo"], foreground=styl.KOLORY["tusz"],
                       font=self.glowne.czcionki["zwykla"])
        przewijak = ttk.Scrollbar(ramka, orient="vertical", command=pole.yview)
        pole.configure(yscrollcommand=przewijak.set)
        pole.insert("1.0", tekst)
        pole.configure(state="disabled")           # tylko do odczytu, zaznaczanie nadal działa
        # pasek PRZED treścią: przy braku miejsca pack odbiera je ostatniemu widżetowi
        przewijak.pack(side="right", fill="y")
        pole.pack(side="left", fill="both", expand=True)
        return ramka

    def _otworz_adres(self, adres: str) -> None:
        try:
            pliki.otworz(adres)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)

    # -------------------------------------------------------------- historia
    def _historia(self, karta: ttk.Frame, egz_id: int) -> None:
        przyciski = ttk.Frame(karta)
        przyciski.pack(fill="x", pady=(0, 8))
        ttk.Button(przyciski, text=t("akcja.dodaj_test"),
                   command=lambda: self.okno_zdarzenia(egz_id, typ="test")).pack(side="left")
        ttk.Button(przyciski, text=t("akcja.dodaj_naprawe"),
                   command=lambda: self.okno_zdarzenia(egz_id, typ="naprawa")).pack(side="left", padx=(6, 0))
        wpisy = zdarzenia(self.db, egz_id)
        if not wpisy:
            ttk.Label(karta, text=t("pusty.historia"), style="Opis.TLabel").pack(anchor="w")
            return
        lista = ttk.Treeview(karta, columns=("data", "typ", "wynik", "opis"), show="headings", height=8,
                             selectmode="browse")
        for kod, klucz, szerokosc in (("data", "kolumna.data", 90), ("typ", "kolumna.typ", 105),
                                      ("wynik", "kolumna.wynik", 85), ("opis", "kolumna.opis", 200)):
            lista.heading(kod, text=t(klucz), anchor="w")
            lista.column(kod, width=szerokosc, stretch=kod == "opis")
        for z in wpisy:
            rodzaj = (etykieta("zdarzenie.podtyp", z["podtyp"]) if z["podtyp"]
                      else etykieta("zdarzenie.typ", z["typ"]))
            lista.insert("", "end", iid=str(z["id"]), values=(
                z["data"], rodzaj, etykieta("zdarzenie.wynik", z["wynik"]) if z["wynik"] else "",
                (z["opis"] or "").replace("\n", " ")))
        lista.pack(fill="both", expand=True)

        def wybrany():
            wybor = lista.selection()
            return int(wybor[0]) if wybor else None

        def menu(zdarzenie):
            wiersz_ = lista.identify_row(zdarzenie.y)
            if not wiersz_:
                return
            lista.selection_set(wiersz_)
            m = tk.Menu(self.glowne, tearoff=False)
            m.add_command(label=t("akcja.edytuj"),
                          command=lambda: self.okno_zdarzenia(egz_id, zdarzenie_id=int(wiersz_)))
            m.add_command(label=t("akcja.usun"), command=lambda: self._usun_zdarzenie(int(wiersz_)))
            try:
                m.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
            finally:
                m.grab_release()

        lista.bind("<Double-1>", lambda _e: wybrany() and self.okno_zdarzenia(egz_id, zdarzenie_id=wybrany()))
        lista.bind("<Button-3>", menu)
        lista.bind("<Button-2>", menu)

    def okno_zdarzenia(self, egz_id: int, zdarzenie_id: int | None = None, typ: str = "test"):
        from gui.okno_zdarzenia import OknoZdarzenia
        okno = OknoZdarzenia(self.glowne, egz_id, zdarzenie_id, typ)
        okno.pokaz()
        return okno

    def _usun_zdarzenie(self, zdarzenie_id: int) -> None:
        if not messagebox.askyesno(t("okno.potwierdzenie"), t("pytanie.usun_zdarzenie"), parent=self.glowne):
            return
        try:
            from uslugi import inwentarz
            inwentarz.usun_zdarzenie(self.db, zdarzenie_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()

    # ------------------------------------------------------------------ zasoby
    def _zasoby(self, karta: ttk.Frame, egz_id: int) -> None:
        przyciski = ttk.Frame(karta)
        przyciski.pack(fill="x", pady=(0, 8))
        for i, (klucz, polecenie) in enumerate((
                ("akcja.dodaj_zdjecia", lambda: self.dodaj_zdjecia(egz_id)),
                ("akcja.dodaj_plik", lambda: self._dodaj_plik(egz_id)),
                ("akcja.dodaj_odnosnik", lambda: self._okno_zasobu(egz_id, "link")),
                ("akcja.dodaj_notatke", lambda: self._okno_zasobu(egz_id, "notatka")))):
            ttk.Button(przyciski, text=t(klucz), command=polecenie).grid(
                row=i // 2, column=i % 2, sticky="we", padx=(0, 6), pady=(0, 4))

        zasoby = zasoby_dziedziczone(self.db, egz_id)
        zdjecia = [z for z in zasoby if z["typ"] == "zdjecie"]
        pozostale = [z for z in zasoby if z["typ"] != "zdjecie"]
        if not zasoby:
            ttk.Label(karta, text=t("pusty.zasoby"), style="Opis.TLabel", wraplength=380,
                      justify="left").pack(anchor="w")
            return
        if zdjecia:
            self._pasek_miniatur(karta, egz_id, zdjecia)
        if zdjecia and not pliki.pillow_dostepne():
            ttk.Label(karta, text=t("zasoby.brak_pillow"), style="Opis.TLabel", wraplength=380,
                      justify="left").pack(anchor="w", pady=(0, 6))
        if pozostale:
            lista = ttk.Treeview(karta, columns=("typ", "tytul", "wersja", "skad"), show="headings", height=6)
            for kod, klucz, szerokosc in (("typ", "kolumna.typ", 90), ("tytul", "kolumna.tytul", 150),
                                          ("wersja", "kolumna.wersja", 60),
                                          ("skad", "kolumna.pochodzenie", 115)):
                lista.heading(kod, text=t(klucz), anchor="w")
                lista.column(kod, width=szerokosc, stretch=kod == "tytul")
            po_iid = {}
            for z in pozostale:
                iid = lista.insert("", "end", values=(etykieta("zasob.typ", z["typ"]), z["tytul"],
                                                       z["wersja"] or "", t(f"pochodzenie.{z['pochodzenie']}")))
                po_iid[iid] = z
            lista.pack(fill="both", expand=True)
            wybrany = lambda: po_iid.get(next(iter(lista.selection()), None))  # noqa: E731
            lista.bind("<Double-1>", lambda _e: wybrany() and self._otworz(egz_id, wybrany()))
            menu = lambda e: (lista.selection_set(lista.identify_row(e.y)) if lista.identify_row(e.y) else None,  # noqa: E731
                              wybrany() and self._menu_zasobu(e, egz_id, wybrany()))
            lista.bind("<Button-3>", menu)
            lista.bind("<Button-2>", menu)
        ttk.Label(karta, text=t("zasoby.podpowiedz"), style="Opis.TLabel", wraplength=380,
                  justify="left").pack(anchor="w", pady=(6, 0))

    def _pasek_miniatur(self, karta: ttk.Frame, egz_id: int, zdjecia: list) -> None:
        """Poziomy, przewijany pasek miniatur. Kliknięcie otwiera zdjęcie,
        prawy przycisk — menu (opis, odpięcie). Pole „Główne” wybiera zdjęcie
        pokazywane na karcie Ogólne (zaznaczenie innego odznacza poprzednie)."""
        glowne_ = pliki.zdjecie_glowne(self.db, egz_id)
        glowne_id = glowne_["id"] if glowne_ is not None else None
        ramka = ttk.Frame(karta)
        ramka.pack(fill="x", pady=(0, 8))
        wysokosc = 160 // SKALA_PASKA + 30
        plotno = tk.Canvas(ramka, height=wysokosc, highlightthickness=0,
                           background=self.glowne.cget("background"))
        przewijak = ttk.Scrollbar(ramka, orient="horizontal", command=plotno.xview)
        plotno.configure(xscrollcommand=przewijak.set)
        plotno.pack(fill="x")
        wnetrze = ttk.Frame(plotno)
        plotno.create_window(0, 0, window=wnetrze, anchor="nw")
        for z in zdjecia:
            komorka = ttk.Frame(wnetrze, padding=(0, 0, 8, 0))
            komorka.pack(side="left", anchor="n")
            obraz = None
            if z["miniatura"]:
                try:
                    obraz = tk.PhotoImage(master=self.glowne,
                                          data=base64.b64encode(z["miniatura"])).subsample(SKALA_PASKA)
                    self._miniatury.append(obraz)
                except tk.TclError:
                    obraz = None
            if obraz is not None:
                podglad = ttk.Label(komorka, image=obraz, cursor="hand2")
            else:
                podglad = ttk.Label(komorka, text=t("zasoby.bez_podgladu"), width=10, anchor="center",
                                    style="Opis.TLabel", cursor="hand2")
            podglad.pack()
            podpis = z["tytul"] if len(z["tytul"]) <= 14 else z["tytul"][:13] + "…"
            ttk.Label(komorka, text=podpis, style="Opis.TLabel").pack()
            if z["plik_sciezka"] and not pliki.sciezka_pliku(self.db, z["plik_sciezka"]).exists():
                # plik usunięty z dysku poza programem — miniatura w bazie została
                ttk.Label(komorka, text=t("zasoby.brak_pliku"), style="Ostrzezenie.TLabel").pack()
            zaznaczone = tk.IntVar(master=self.glowne, value=int(z["id"] == glowne_id))
            self._wybor_glownego.append(zaznaczone)
            ttk.Checkbutton(komorka, text=t("zasoby.glowne"), variable=zaznaczone,
                            command=lambda z=z, v=zaznaczone: self.ustaw_glowne(egz_id, z["id"] if v.get() else None)
                            ).pack()
            ttk.Button(komorka, text=t("akcja.usun_zdjecie"), style="Maly.TButton",
                       command=lambda z=z: self.usun_zdjecie(z)).pack(pady=(2, 0))
            podglad.bind("<Button-1>", lambda _e, z=z: self._otworz(egz_id, z))
            podglad.bind("<Button-3>", lambda e, z=z: self._menu_zasobu(e, egz_id, z))
            podglad.bind("<Button-2>", lambda e, z=z: self._menu_zasobu(e, egz_id, z))

        def dopasuj(_e=None):
            # wysokość paska = wysokość miniatur z podpisem (zdjęcia poziome są niższe)
            plotno.configure(scrollregion=plotno.bbox("all"), height=wnetrze.winfo_reqheight())
            if wnetrze.winfo_reqwidth() > plotno.winfo_width():
                przewijak.pack(side="bottom", fill="x", before=plotno)
            else:
                przewijak.pack_forget()

        wnetrze.bind("<Configure>", dopasuj)
        plotno.bind("<Configure>", dopasuj)

    def _menu_zasobu(self, zdarzenie, egz_id: int, zasob) -> None:
        menu = tk.Menu(self.glowne, tearoff=False)
        menu.add_command(label=t("akcja.otworz"), command=lambda: self._otworz(egz_id, zasob))
        menu.add_command(label=t("akcja.edytuj_opis"),
                         command=lambda: self._okno_zasobu(egz_id, "edycja", zasob_id=zasob["id"]))
        if zasob["typ"] == "zdjecie":
            menu.add_command(label=t("akcja.ustaw_glowne"), command=lambda: self.ustaw_glowne(egz_id, zasob["id"]))
        menu.add_separator()
        if zasob["typ"] == "zdjecie":
            menu.add_command(label=t("akcja.usun_zdjecie_pelne"), command=lambda: self.usun_zdjecie(zasob))
        menu.add_command(label=t("akcja.odepnij"), command=lambda: self._odepnij(zasob))
        try:
            menu.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
        finally:
            menu.grab_release()

    # ---------------------------------------------------------------- akcje
    def _okno_zasobu(self, egz_id: int, tryb: str, **opcje):
        from gui.okno_zasobu import OknoZasobu
        okno = OknoZasobu(self.glowne, egz_id, tryb, **opcje)
        okno.pokaz()
        return okno

    def _katalog_startowy(self) -> str:
        return ustawienia.pobierz(self.db, "ostatni_katalog", str(Path.home())) or str(Path.home())

    def _zapamietaj_katalog(self, sciezka: str) -> None:
        ustawienia.zapisz(self.db, "ostatni_katalog", str(Path(sciezka).parent))

    def dodaj_zdjecia(self, egz_id: int) -> None:
        """Wybór wielu zdjęć naraz; każde podpinane do tego egzemplarza."""
        sciezki = filedialog.askopenfilenames(
            parent=self.glowne, title=t("okno.wybierz_zdjecia"), initialdir=self._katalog_startowy(),
            filetypes=[(t("plik.zdjecia"), WZORCE_ZDJEC), (t("plik.wszystkie"), "*")])
        if not sciezki:
            return
        self._zapamietaj_katalog(sciezki[0])
        self.dodaj_pliki_zdjec(egz_id, list(sciezki))

    def dodaj_pliki_zdjec(self, egz_id: int, sciezki: list[str]) -> None:
        bledy = []
        for sciezka in sciezki:
            try:
                pliki.dodaj_plik(self.db, sciezka, {"egzemplarz_id": egz_id}, typ="zdjecie")
            except Exception as blad:   # noqa: BLE001 — jeden zły plik nie zatrzymuje reszty
                bledy.append(f"{Path(sciezka).name}: {blad}")
        self.glowne.odswiez()
        if bledy:
            messagebox.showwarning(t("okno.uwaga"), t("zasoby.bledy_dodawania", lista="\n".join(bledy)),
                                   parent=self.glowne)

    def _dodaj_plik(self, egz_id: int) -> None:
        sciezka = filedialog.askopenfilename(parent=self.glowne, title=t("okno.wybierz_plik"),
                                             initialdir=self._katalog_startowy())
        if sciezka:
            self._zapamietaj_katalog(sciezka)
            self._okno_zasobu(egz_id, "plik", sciezka=sciezka)

    def _otworz(self, egz_id: int, zasob) -> None:
        if zasob["typ"] == "notatka" and not zasob["plik_sciezka"]:
            self._okno_zasobu(egz_id, "edycja", zasob_id=zasob["id"])
            return
        try:
            pliki.otworz_zasob(self.db, zasob)
        except BladNornicy as blad:
            if blad.klucz == "blad.brak_pliku":
                # plik usunięty poza programem: zamiast samego błędu — propozycja sprzątnięcia wpisu
                if messagebox.askyesno(t("okno.potwierdzenie"),
                                       t("pytanie.brak_pliku_usun_wpis", tytul=zasob["tytul"],
                                         sciezka=blad.pola.get("sciezka", "")), parent=self.glowne):
                    self._usun_zasob(zasob)
                return
            pokaz_blad(self.glowne, blad)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)

    def ustaw_glowne(self, egz_id: int, zasob_id: int | None) -> None:
        try:
            pliki.ustaw_zdjecie_glowne(self.db, egz_id, zasob_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()       # odświeża kartę: nowe zdjęcie, jedno zaznaczone pole

    def usun_zdjecie(self, zasob) -> None:
        """Przycisk „Usuń” pod miniaturą: jedno potwierdzenie, odpięcie i — gdy nic
        innego z niego nie korzysta — usunięcie pliku z dysku. Zdjęcie dziedziczone
        z modelu lub kategorii znika ze wszystkich egzemplarzy, więc pytanie to mówi."""
        if zasob["pochodzenie"] == "egzemplarz":
            pytanie = t("pytanie.usun_zdjecie", tytul=zasob["tytul"])
        else:
            pytanie = t("pytanie.usun_zdjecie_wspolne", tytul=zasob["tytul"],
                        skad=t(f"pochodzenie.{zasob['pochodzenie']}"))
        if messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self.glowne):
            self._usun_zasob(zasob)

    def _usun_zasob(self, zasob) -> None:
        """Odpięcie, a gdy zasób został sierotą — usunięcie rekordu i pliku.
        Plik używany gdzie indziej (np. przez model) zostaje."""
        try:
            if pliki.odepnij(self.db, zasob["id"], cel_powiazania(zasob)):
                pliki.usun_sieroty_z_plikami(self.db, [zasob["id"]])
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()

    def _odepnij(self, zasob) -> None:
        if zasob["pochodzenie"] == "egzemplarz":
            pytanie = t("pytanie.odepnij", tytul=zasob["tytul"])
        else:
            pytanie = t("pytanie.odepnij_wspolny", tytul=zasob["tytul"],
                        skad=t(f"pochodzenie.{zasob['pochodzenie']}"))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self.glowne):
            return
        try:
            sierota = pliki.odepnij(self.db, zasob["id"], cel_powiazania(zasob))
            if sierota and messagebox.askyesno(t("okno.potwierdzenie"),
                                               t("pytanie.usun_sierote", tytul=zasob["tytul"]),
                                               parent=self.glowne):
                pliki.usun_sieroty_z_plikami(self.db, [zasob["id"]])
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()
