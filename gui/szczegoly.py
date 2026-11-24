# SPDX-License-Identifier: GPL-3.0-or-later
"""Karta szczegółów zaznaczonego elementu.

Panel jest „widokiem”: przy każdej zmianie zaznaczenia czyści treść
i buduje ją od nowa z bazy. Nie przechowuje stanu, który musiałby
przeżyć przebudowę okna — zakładkę pamięta StanWidoku okna głównego.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from baza.enumy import etykieta
from baza.repozytoria import egzemplarze, lokalizacje, slowniki
from baza.repozytoria.szczegoly import zlacza_egzemplarza
from gui import styl
from gui.bazowe import pokaz_blad
from gui.karta_historia import HistoriaKarty
from gui.karta_zasoby import ZasobyKarty
from gui.karta_zdjecie import ZdjecieIQr
from gui.model_drzewa import WEZEL_BEZ_LOKALIZACJI, rozbierz_iid
from i18n.tlumacz import nazwa, t
from uslugi import pliki
from uslugi.formatowanie import data_lokalna, liczba_na_tekst, minor_na_tekst, pojemnosc_na_tekst

MIN_KOLUMNA_WARTOSCI = 120     # minimalna szerokość kolumny wartości na karcie Ogólne


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


class PanelSzczegolow(ZdjecieIQr, HistoriaKarty, ZasobyKarty):
    """Karty Ogólne, Parametry i Złącza; zdjęcie i kod QR, historia oraz zasoby
    pochodzą z klas pomocniczych w gui/karta_*.py."""

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
        liczba = lokalizacje.liczba_egzemplarzy(self.db, lok_id)
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
        self._ogolne_egzemplarza(e)
        wiersze = self._wiersze_parametrow(e)
        if wiersze:
            self._tabela_pol(self.karty[1], wiersze)
        else:
            ttk.Label(self.karty[1], text=t("pusty.parametry"), style="Opis.TLabel").pack(anchor="w")
        self._zlacza(egz_id)
        self._zasoby(self.karty[3], egz_id)        # z dziedziczeniem po modelu i kategorii
        self._historia(self.karty[4], egz_id)

    def _ogolne_egzemplarza(self, e) -> None:
        """Karta Ogólne: dane egzemplarza, kod QR, nabycie, model, data zmiany."""
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

    def _wiersze_parametrow(self, e) -> list[tuple[str, str]]:
        """Parametry: wartości modelu + nadpisania egzemplarza, w kolejności szablonu
        kategorii; na końcu wartości spoza szablonu (np. po zmianie kategorii)."""
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
        return wiersze

    def _zlacza(self, egz_id: int) -> None:
        ttk.Button(self.karty[2], text=t("akcja.edytuj_zlacza"),
                   command=lambda: self.glowne.edytuj_egzemplarz(egz_id, zakladka=2)).pack(anchor="w", pady=(0, 8))
        self._lista(self.karty[2],
                    [(t("kolumna.rola"), 90), (t("kolumna.zlacze"), 220), (t("kolumna.ilosc"), 60)],
                    [(etykieta("model_zlacze.rola", z["rola"]),
                      nazwa(z["nazwy"]) + (f"  ({t('parametry.zmienione')})" if z["zmienione"] else ""),
                      z["ilosc"]) for z in zlacza_egzemplarza(self.db, egz_id)],
                    "pusty.zlacza")

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
            pliki.otworz_adres(adres)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
