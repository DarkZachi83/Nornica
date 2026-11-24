# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Asystent AI — kilka przedmiotów” (Plik → Asystent AI…).

Jedna linia = jeden przedmiot, na końcu opcjonalnie ilość („× 3”). Asystent
przechodzi linie po kolei (z możliwością przerwania), a wyniki pokazuje
w drzewie: pozycja, pod nią propozycje parametrów — z tą samą oceną co
w oknie modelu. Dopiero „Utwórz zaznaczone” (po potwierdzeniu) zapisuje
modele i — na życzenie — egzemplarze w wybranej lokalizacji.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from asystent import wsad
from asystent.ollama import Przerwano
from baza.repozytoria import slowniki
from gui import styl
from gui.asystent_wspolne import (PracaAsystenta, domyslnie_zaznaczona, fabryka_domyslna,
                                  lista_modeli_domyslna, ocena)
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import jezyk_biezacy, nazwa, t
from wyjatki import BladNornicy


class OknoWsadowe(PracaAsystenta, OknoDialogowe):
    def __init__(self, glowne, fabryka=fabryka_domyslna, lista_modeli=lista_modeli_domyslna):
        super().__init__(glowne)
        ram = slowniki.kategoria_po_kodzie(self.db, "pamieci_ram")
        self.kategoria = PoleWyboru(self._opcje_kategorii, ram["id"] if ram else None)
        self.linie = PoleTekstu("")
        self.tryb = tk.StringVar(value="modele")             # "modele" albo "egzemplarze"
        self.lokalizacja = PoleWyboru(self._opcje_lokalizacji, None)
        self.status = PoleWyboru(self._opcje_statusow, slowniki.status_id(self.db, "nietestowany"))
        self.pozycje: list[wsad.Pozycja] = []
        self.biezaca: int | None = None
        self.podsumowanie: wsad.Podsumowanie | None = None
        self._przygotuj_asystenta(fabryka, lista_modeli)

    def _opcje_kategorii(self):
        return [(kid, "    " * g + n) for kid, g, n in slowniki.kategorie_plasko(self.db)]

    def _opcje_lokalizacji(self):
        from baza.polaczenie import klucz_sortowania
        from baza.repozytoria import lokalizacje
        return [(None, t("lokalizacja.brak"))] + sorted(lokalizacje.sciezki(self.db).items(),
                                                        key=lambda p: klucz_sortowania(p[1]))

    def _opcje_statusow(self):
        return [(s["id"], nazwa(s["nazwy"])) for s in slowniki.statusy(self.db)]

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("wsad.tytul"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        self._sekcja_ustawien(ramka)
        self._sekcja_przedmiotow(ramka)
        self._stan = ttk.Label(ramka, style="Opis.TLabel", wraplength=820, justify="left")
        self._stan.pack(fill="x", pady=(8, 0))
        self._pasek = ttk.Progressbar(ramka, mode="indeterminate")
        self._pasek.pack(fill="x", pady=(4, 0))
        self._sekcja_wynikow(ramka)
        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(10, 0))
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        self._utworz = ttk.Button(dol, text=t("wsad.utworz"), style="Akcent.TButton", command=self.utworz)
        self._utworz.pack(side="right", padx=(0, 8))
        self._odswiez()

    def _sekcja_przedmiotow(self, ramka: ttk.Frame) -> None:
        sekcja = ttk.LabelFrame(ramka, text=t("wsad.przedmioty"), padding=10)
        sekcja.pack(fill="x", pady=(10, 0))
        ttk.Label(sekcja, text=t("pole.kategoria"), style="Pole.TLabel").grid(row=0, column=0, sticky="w")
        self.kategoria.zbuduj(sekcja, width=36).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.linie.zbuduj(sekcja, height=5, width=70, font=self.glowne.czcionki["zwykla"]).grid(
            row=1, column=0, columnspan=4, sticky="we", pady=(6, 0))
        ttk.Label(sekcja, text=t("wsad.linie_podpowiedz"), style="Opis.TLabel", wraplength=780,
                  justify="left").grid(row=2, column=0, columnspan=4, sticky="w")
        tworz = ttk.Frame(sekcja)
        tworz.grid(row=3, column=0, columnspan=4, sticky="we", pady=(8, 0))
        for tryb in ("modele", "egzemplarze"):
            ttk.Radiobutton(tworz, text=t(f"wsad.tryb_{tryb}"), value=tryb, variable=self.tryb,
                            command=self._odswiez).pack(side="left", padx=(0, 12))
        ttk.Label(tworz, text=t("pole.lokalizacja"), style="Pole.TLabel").pack(side="left", padx=(8, 6))
        self._pole_lokalizacji = self.lokalizacja.zbuduj(tworz, width=26)
        self._pole_lokalizacji.pack(side="left")
        ttk.Label(tworz, text=t("pole.status"), style="Pole.TLabel").pack(side="left", padx=(12, 6))
        self._pole_statusu = self.status.zbuduj(tworz, width=16)
        self._pole_statusu.pack(side="left")
        przyciski = ttk.Frame(sekcja)
        przyciski.grid(row=4, column=0, columnspan=4, sticky="e", pady=(8, 0))
        self._start = ttk.Button(przyciski, text=t("asystent.szukaj"), style="Akcent.TButton", command=self.uruchom)
        self._start.pack(side="left")
        self._stop = ttk.Button(przyciski, text=t("asystent.przerwij"), command=self.przerwij)
        self._stop.pack(side="left", padx=(6, 0))
        sekcja.columnconfigure(3, weight=1)

    def _sekcja_wynikow(self, ramka: ttk.Frame) -> None:
        obszar = ttk.Frame(ramka)
        obszar.pack(fill="both", expand=True, pady=(10, 0))
        kolumny = (("wstaw", 60), ("propozycja", 220), ("pewnosc", 240))
        drzewo = ttk.Treeview(obszar, columns=[k for k, _ in kolumny], height=10, selectmode="browse")
        drzewo.heading("#0", text=t("wsad.kolumna_pozycja"), anchor="w")
        drzewo.column("#0", width=300, stretch=True)
        for kod, szerokosc in kolumny:
            drzewo.heading(kod, text=t(f"asystent.kolumna_{kod}"), anchor="w")
            drzewo.column(kod, width=szerokosc, stretch=kod != "wstaw", anchor="w")
        przewijak = ttk.Scrollbar(obszar, orient="vertical", command=drzewo.yview)
        drzewo.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")
        drzewo.pack(side="left", fill="both", expand=True)
        drzewo.tag_configure("niepotwierdzona", foreground=styl.KOLORY_STATUSOW["w_naprawie"])
        drzewo.tag_configure("bledna", foreground=styl.KOLORY_STATUSOW["uszkodzony"])
        drzewo.tag_configure("pozycja", font=self.glowne.czcionki["pogrubiona"])
        drzewo.bind("<Button-1>", self._klik)
        drzewo.bind("<space>", lambda _e: self.przelacz(drzewo.focus()))
        drzewo.bind("<<TreeviewSelect>>", lambda _e: self._pokaz_szczegoly())
        self._drzewo = drzewo
        self._szczegoly = ttk.Label(ramka, wraplength=820, justify="left")
        self._szczegoly.pack(fill="x", pady=(6, 0))
        self._adres = ttk.Label(ramka, style="Odnosnik.TLabel", cursor="hand2")
        self._adres.pack(anchor="w")
        self._adres.bind("<Button-1>", lambda _e: self._otworz_zrodlo())

    def _odswiez(self) -> None:
        if not hasattr(self, "_drzewo") or not self._drzewo.winfo_exists():
            return
        self._odswiez_ustawienia()
        self._odswiez_pracy(self._start, self._stop, self._pasek)
        stan_pol = ["!disabled"] if self.tryb.get() == "egzemplarze" else ["disabled"]
        for pole in (self._pole_lokalizacji, self._pole_statusu):
            pole.state(stan_pol)
        self._utworz.state(["!disabled"] if self.pozycje and not self.pracuje else ["disabled"])
        if self.pracuje:
            tekst, styl_ = self.postep, "Opis.TLabel"
        elif self.blad is not None:
            tekst = self.blad.komunikat() if isinstance(self.blad, BladNornicy) else str(self.blad)
            styl_ = "Ostrzezenie.TLabel"
        elif self.podsumowanie is not None:
            tekst, styl_ = self._tekst_podsumowania(), "Opis.TLabel"
        elif self.pozycje:
            tekst, styl_ = t("wsad.gotowe", ile=len(self.pozycje)), "Opis.TLabel"
        else:
            tekst, styl_ = t("wsad.wstep"), "Opis.TLabel"
        self._stan.configure(text=tekst, style=styl_)
        self._wypelnij_drzewo()

    def _tekst_pozycji(self, numer: int, p: wsad.Pozycja) -> tuple[str, str]:
        """Nagłówek pozycji i jej stan (kolumna „Ocena”)."""
        tekst = f"{numer + 1}. {p.tekst}" + (f" × {p.ilosc}" if p.ilosc > 1 else "")
        if p.blad is not None:
            return tekst, p.blad.komunikat() if isinstance(p.blad, BladNornicy) else str(p.blad)
        if p.wynik is not None:
            return tekst, t("wsad.stan_gotowa", ile=len(p.wynik.wartosci), wybrane=len(p.zaznaczone))
        return tekst, t("wsad.stan_szukam") if self.pracuje and numer == self.biezaca else t("wsad.stan_czeka")

    def _wypelnij_drzewo(self) -> None:
        drzewo = self._drzewo
        biezacy = drzewo.focus()
        drzewo.delete(*drzewo.get_children())
        for i, p in enumerate(self.pozycje):
            tekst, stan = self._tekst_pozycji(i, p)
            znak = "☑" if p.utworz else "☐"
            drzewo.insert("", "end", iid=f"p{i}", text=tekst, open=True,
                          tags=("pozycja",) + (("bledna",) if p.blad else ()), values=(znak, "", stan))
            for w in (p.wynik.wartosci if p.wynik else []):
                pewnosc, ostrzezenie = ocena(w)
                znaczniki = ("bledna",) if w.blad else ("niepotwierdzona",) if ostrzezenie else ()
                znak = "—" if w.blad else "☑" if w.kod in p.zaznaczone else "☐"
                drzewo.insert(f"p{i}", "end", iid=f"p{i}:{w.kod}", text=w.etykieta, tags=znaczniki,
                              values=(znak, w.tekst, pewnosc))
        if biezacy and drzewo.exists(biezacy):
            drzewo.focus(biezacy)
            drzewo.selection_set(biezacy)
        self._pokaz_szczegoly()

    def _element(self, iid: str):
        """(pozycja, wartość albo None) dla wiersza drzewa."""
        if not iid or not iid.startswith("p"):
            return None, None
        numer, _, kod = iid[1:].partition(":")
        try:
            p = self.pozycje[int(numer)]
        except (ValueError, IndexError):
            return None, None
        return p, (p.wynik.wartosc(kod) if kod and p.wynik else None)

    def _pokaz_szczegoly(self) -> None:
        p, w = self._element(self._drzewo.focus())
        if w is not None:
            cytat = f"„{w.cytat}”" if w.cytat else t("asystent.bez_cytatu")
            self._szczegoly.configure(text=t("asystent.cytat", cytat=cytat))
            self._adres.configure(text=f"{w.zrodlo.tytul} — {w.zrodlo.adres}" if w.zrodlo else t("asystent.bez_zrodla"))
        elif p is not None and p.wynik is not None and p.wynik.uwagi:
            self._szczegoly.configure(text=t("asystent.uwagi", uwagi=p.wynik.uwagi))
            self._adres.configure(text="")
        else:
            self._szczegoly.configure(text=t("asystent.wybierz_wiersz") if self.pozycje else "")
            self._adres.configure(text="")

    def _otworz_zrodlo(self) -> None:
        _p, w = self._element(self._drzewo.focus())
        if w is not None and w.zrodlo is not None:
            webbrowser.open(w.zrodlo.adres)

    def _klik(self, zdarzenie) -> None:
        if self._drzewo.identify_column(zdarzenie.x) == "#1":
            self.przelacz(self._drzewo.identify_row(zdarzenie.y))

    def przelacz(self, iid: str) -> None:
        """Pozycja: tworzyć czy nie. Propozycja: wpisać do modelu czy nie."""
        p, w = self._element(iid)
        if p is None:
            return
        if ":" not in iid:
            p.utworz = not p.utworz
            self._drzewo.set(iid, "wstaw", "☑" if p.utworz else "☐")
            return
        if w is None or not w.mozna_wstawic:
            return
        p.zaznaczone.symmetric_difference_update({w.kod})
        self._drzewo.set(iid, "wstaw", "☑" if w.kod in p.zaznaczone else "☐")
        _tekst, stan = self._tekst_pozycji(int(iid[1:].partition(":")[0]), p)
        self._drzewo.set(iid.partition(":")[0], "pewnosc", stan)

    # ------------------------------------------------------------------ praca
    def uruchom(self) -> None:
        pozycje = wsad.parsuj(self.linie.zapamietaj())
        if not pozycje:
            self.blad = BladNornicy("wsad.brak_linii")
            self._odswiez()
            return
        if len(pozycje) > wsad.MAKS_POZYCJI:
            self.blad = BladNornicy("wsad.za_duzo", ile=len(pozycje), maks=wsad.MAKS_POZYCJI)
            self._odswiez()
            return
        if not self.kategoria.wartosc:
            self.blad = BladNornicy("asystent.wybierz_kategorie")
            self._odswiez()
            return
        if not self._gotowy_do_pracy():
            return
        kategoria = slowniki.kategoria(self.db, self.kategoria.wartosc)
        szablon = slowniki.szablon(self.db, self.kategoria.wartosc)
        self.pozycje, self.biezaca, self.podsumowanie, self.blad = pozycje, 0, None, None
        self.pracuje, self.postep = True, t("asystent.krok_start")
        anuluj, jezyk, u = self._anuluj, jezyk_biezacy(), self.ustawienia()
        teksty = [(p.tekst, nazwa(kategoria["nazwy"])) for p in pozycje]
        kolejka, fabryka = self._kolejka, self._fabryka

        def w_tle():                         # bez odwołań do okna — patrz _uruchom_watek
            try:
                asystent = fabryka(u)
                for numer, (tekst, nazwa_kategorii) in enumerate(teksty):
                    kolejka.put(("pozycja", numer, None))
                    dane = {"kategoria": nazwa_kategorii, "oznaczenia": tekst}
                    try:
                        wynik = asystent.zaproponuj(szablon, dane, None, anuluj,
                                                    lambda klucz, **p: kolejka.put(("krok", klucz, p)), jezyk)
                        kolejka.put(("pozycja", numer, wynik))
                    except Przerwano:
                        raise
                    except Exception as blad:   # noqa: BLE001 — jedna pozycja nie zatrzymuje reszty
                        kolejka.put(("pozycja", numer, blad))
                kolejka.put(("koniec", None, None))
            except Przerwano:
                kolejka.put(("przerwano", None, None))
            except Exception as blad:   # noqa: BLE001
                kolejka.put(("blad", None, blad))

        self._uruchom_watek(w_tle, "asystent-wsad")
        self._odswiez()

    def _odbierz(self, rodzaj: str, wartosc, dodatek) -> None:
        if rodzaj == "pozycja":
            p = self.pozycje[wartosc]
            if dodatek is None:
                self.biezaca = wartosc
            elif isinstance(dodatek, Exception):
                p.blad, p.utworz = dodatek, False
            else:
                p.wynik = dodatek
                p.zaznaczone = {w.kod for w in dodatek.wartosci if domyslnie_zaznaczona(w)}
        elif rodzaj == "koniec":
            self.pracuje, self.biezaca = False, None

    def _tekst_podsumowania(self) -> str:
        s = self.podsumowanie
        tekst = t("wsad.utworzono", nowe=s.modele_nowe, istniejace=s.modele_istniejace, egzemplarze=s.egzemplarze)
        if s.blad is not None:
            opis = s.blad.komunikat() if isinstance(s.blad, BladNornicy) else str(s.blad)
            tekst += "\n" + t("wsad.przerwany_zapis", linia=s.nieudana, opis=opis)
        return tekst

    def utworz(self) -> None:
        do_zapisu = [p for p in self.pozycje if p.utworz]
        if not do_zapisu or self.pracuje:
            return
        egzemplarze = self.tryb.get() == "egzemplarze"
        if egzemplarze and not self.status.wartosc:
            pokaz_blad(self, BladNornicy("blad.wybierz_status"))
            return
        sztuk = sum(p.ilosc for p in do_zapisu)
        pytanie = (t("wsad.potwierdz_egzemplarze", modele=len(do_zapisu), sztuk=sztuk,
                     lokalizacja=dict(self._opcje_lokalizacji()).get(self.lokalizacja.wartosc) or t("lokalizacja.brak"))
                   if egzemplarze else t("wsad.potwierdz_modele", modele=len(do_zapisu)))
        if not messagebox.askyesno(t("wsad.tytul"), pytanie, parent=self):
            return
        self.podsumowanie = wsad.utworz(self.db, do_zapisu, self.kategoria.wartosc, self.lokalizacja.wartosc,
                                        self.status.wartosc, egzemplarze)
        zapisane = len(do_zapisu) if self.podsumowanie.blad is None else \
            next(i for i, p in enumerate(do_zapisu) if p.tekst == self.podsumowanie.nieudana)
        for p in do_zapisu[:zapisane]:
            p.utworz = False                 # drugie kliknięcie nie zdubluje egzemplarzy
        self.glowne.odswiez()
        self._odswiez()

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.linie.zapamietaj()
