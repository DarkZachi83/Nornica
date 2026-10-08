# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno główne NORNICA / VOLE.

Przełączenie języka = przebudowa okna (zasada z Jaźwca):
  1. _zapamietaj_stan() — stan mieszkający w widżetach (rozwinięte węzły,
     zaznaczenie, przewinięcie, zakładka, podział okna) trafia do StanWidoku,
  2. niszczymy dzieci okna — ale NIE okna podrzędne (Toplevel)! W Jaźwcu
     wszystkie dzieci były widżetami; tu otwarte okna dialogowe też są
     dziećmi okna głównego i zniknęłyby razem z wpisanymi danymi,
  3. _zbuduj_ui() od zera; słownik self._widzety z referencjami jest tworzony
     na nowo, więc nic nie sięga po zniszczone widżety,
  4. odświeżenie drzewa i przywrócenie stanu,
  5. przebudowa zarejestrowanych okien podrzędnych.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk

from baza.repozytoria import egzemplarze, lokalizacje, ustawienia
from baza.zaleznosci import opis, zaleznosci
from gui import styl
from gui.bazowe import pokaz_blad
from gui.model_drzewa import (TRYBY, iid_egzemplarza, iid_lokalizacji, rozbierz_iid,
                              zbuduj_wezly)
from gui.szczegoly import PanelSzczegolow
from i18n.tlumacz import JEZYKI, jezyk_biezacy, t, ustaw_jezyk
from konfiguracja import KATALOG_PROGRAMU
from uslugi import inwentarz

KOLUMNY = (("kod", "kolumna.kod", 105), ("status", "kolumna.status", 100),
           ("kategoria", "kolumna.kategoria", 150))
TRYB_KLUCZ = {"lokalizacje": "widok.lokalizacje", "montaz": "widok.montaz"}


@dataclass
class StanWidoku:
    tryb: str = "lokalizacje"
    rozwiniete: set = field(default_factory=set)
    zaznaczone: str | None = None
    przewiniecie: float = 0.0
    zakladka: int = 0
    podzial: int | None = None


class OknoGlowne(tk.Tk):
    def __init__(self, polaczenie, pokaz_powitanie: bool = True):
        super().__init__(className="Nornica")
        self.db = polaczenie
        if pokaz_powitanie:
            self.withdraw()
        self.czcionki = styl.ustaw(self)
        self._grafiki = self._wczytaj_grafiki()
        if self._grafiki.get("ikony"):
            self.iconphoto(True, *self._grafiki["ikony"])

        # Stan trwały: żyje w obiekcie, przeżywa przebudowę okna
        self.stan = StanWidoku()
        self.filtr_var = tk.StringVar()
        self.filtr_var.trace_add("write", self._filtr_zmieniony)
        self.tryb_var = tk.StringVar(value=self.stan.tryb)
        self.jezyk_var = tk.StringVar(value=jezyk_biezacy())
        self._dialogi: list[tk.Toplevel] = []
        self._zadanie_filtra = None
        # Skaner: pole „Skanuj” i serwer telefonu. Stan w obiekcie (przeżywa przebudowę),
        # komunikat ostatniego skanu jako klucz + pola — tekst powstaje przy wyświetleniu.
        self.skan_var = tk.StringVar()
        self._ostatni_skan: tuple[str, dict] | None = None
        from uslugi.serwer_mobilny import Most
        self.most = Most()
        self.serwer = None                  # SerwerMobilny, tworzony przez okno telefonu
        self._widzety: dict = {}

        self.geometry("1180x720")
        self.minsize(900, 560)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        # Skróty wiązane raz, na oknie, które nie jest niszczone
        self.bind("<Control-n>", lambda _e: self.nowy_egzemplarz())
        self.bind("<Control-q>", lambda _e: self.destroy())
        self.bind("<F5>", lambda _e: self.odswiez())
        self.bind("<Control-m>", lambda _e: self.katalog_modeli())
        self.bind("<Control-p>", lambda _e: self.drukuj_etykiety())
        self.bind("<Control-e>", lambda _e: self.eksportuj())
        self.bind("<Control-t>", lambda _e: self.telefon())
        self.bind("<F2>", lambda _e: self._fokus_skanera())

        self._zbuduj_ui()
        self.odswiez(zapamietaj=False)
        self.after(100, self._pompuj_most)
        if pokaz_powitanie:
            from gui.okna_info import EkranPowitalny
            EkranPowitalny(self, po_zamknieciu=self.deiconify)

    # ------------------------------------------------------------------ grafika
    def _wczytaj_grafiki(self) -> dict:
        katalog = KATALOG_PROGRAMU / "zasoby"
        grafiki = {}
        try:
            grafiki["ikony"] = [tk.PhotoImage(master=self, file=str(katalog / f"ikona_{r}.png"))
                                for r in (64, 32, 16)]
            grafiki["ikona_duza"] = tk.PhotoImage(master=self, file=str(katalog / "ikona_256.png"))
            grafiki["powitanie"] = tk.PhotoImage(master=self, file=str(katalog / "powitanie.png"))
            grafiki["brak_zdjecia"] = tk.PhotoImage(master=self, file=str(katalog / "brak_zdjecia.png"))
        except tk.TclError:
            pass   # brak grafik nie może zablokować programu
        return grafiki

    def grafika(self, nazwa: str):
        return self._grafiki.get(nazwa)

    # --------------------------------------------------------- okna podrzędne
    def zarejestruj(self, okno: tk.Toplevel) -> None:
        self._dialogi.append(okno)

    def wyrejestruj(self, okno: tk.Toplevel) -> None:
        if okno in self._dialogi:
            self._dialogi.remove(okno)

    # ------------------------------------------------------------- budowanie
    def _zbuduj_ui(self) -> None:
        # Stare referencje idą do śmieci. Uwaga: NIE nazywać tego „self._w” —
        # tkinter trzyma pod tą nazwą ścieżkę okna w Tcl i nadpisanie jej
        # psuje każde wywołanie metody okna.
        self._widzety = {}
        self.title(t("aplikacja.nazwa"))
        self._zbuduj_menu()

        pasek = ttk.Frame(self, padding=(10, 8, 10, 4))
        pasek.pack(fill="x")
        ttk.Button(pasek, text=t("akcja.nowy_egzemplarz"),
                   command=self.nowy_egzemplarz).pack(side="left")
        ttk.Button(pasek, text=t("akcja.nowa_lokalizacja"),
                   command=self.nowa_lokalizacja).pack(side="left", padx=(6, 0))
        ttk.Button(pasek, text=t("akcja.katalog_modeli"),
                   command=self.katalog_modeli).pack(side="left", padx=(6, 18))
        for tryb in TRYBY:
            ttk.Radiobutton(pasek, text=t(TRYB_KLUCZ[tryb]), value=tryb, variable=self.tryb_var,
                            command=self._tryb_zmieniony).pack(side="left", padx=(0, 8))
        szukaj = ttk.Entry(pasek, textvariable=self.filtr_var, width=26)
        szukaj.pack(side="right")
        ttk.Label(pasek, text=t("pasek.szukaj")).pack(side="right", padx=(0, 6))
        # Pole skanera: czytnik USB/Bluetooth „wpisuje” kod i naciska Enter
        skan = ttk.Entry(pasek, textvariable=self.skan_var, width=14)
        skan.pack(side="right", padx=(0, 16))
        skan.bind("<Return>", lambda _e: self._skan_z_pola())
        skan.bind("<KP_Enter>", lambda _e: self._skan_z_pola())
        ttk.Label(pasek, text=t("pasek.skanuj")).pack(side="right", padx=(0, 6))
        self._widzety["skan"] = skan
        self._widzety["szukaj"] = szukaj
        self.bind("<Control-f>", lambda _e: self._widzety["szukaj"].focus_set())

        podzial = ttk.Panedwindow(self, orient="horizontal")
        podzial.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self._widzety["podzial"] = podzial

        lewa = ttk.Frame(podzial)
        drzewo = ttk.Treeview(lewa, columns=[k for k, _, _ in KOLUMNY], selectmode="browse")
        drzewo.heading("#0", text=t("kolumna.nazwa"), anchor="w")
        drzewo.column("#0", width=340, minwidth=200, stretch=True)
        for kod, klucz, szerokosc in KOLUMNY:
            drzewo.heading(kod, text=t(klucz), anchor="w")
            drzewo.column(kod, width=szerokosc, minwidth=60, stretch=False)
        przewijak = ttk.Scrollbar(lewa, orient="vertical", command=drzewo.yview)
        drzewo.configure(yscrollcommand=przewijak.set)
        # pasek PRZED treścią: przy braku miejsca pack odbiera je ostatniemu widżetowi
        przewijak.pack(side="right", fill="y")
        drzewo.pack(side="left", fill="both", expand=True)
        drzewo.tag_configure("lokalizacja", foreground=styl.KOLORY["drewno"],
                             font=self.czcionki["pogrubiona"])
        drzewo.tag_configure("bez_lokalizacji", foreground=styl.KOLORY["przygaszony"])
        for kod, kolor in styl.KOLORY_STATUSOW.items():
            drzewo.tag_configure(f"status_{kod}", foreground=kolor)
        drzewo.bind("<<TreeviewSelect>>", self._wybrano)
        drzewo.bind("<Double-1>", self._dwuklik)
        drzewo.bind("<Delete>", lambda _e: self.usun_zaznaczone())
        drzewo.bind("<Button-3>", self._menu_kontekstowe)          # Linux, Windows
        drzewo.bind("<Button-2>", self._menu_kontekstowe)          # macOS
        self._widzety["drzewo"] = drzewo
        podzial.add(lewa, weight=3)

        prawa = ttk.Frame(podzial, padding=(14, 0, 0, 0))
        self._widzety["szczegoly"] = PanelSzczegolow(self, prawa)
        podzial.add(prawa, weight=2)

        stopka = ttk.Frame(self, padding=(10, 4))
        stopka.pack(fill="x")
        self._widzety["licznik"] = ttk.Label(stopka, style="Opis.TLabel")
        self._widzety["licznik"].pack(side="left")
        self._widzety["skan_info"] = ttk.Label(stopka, style="Opis.TLabel")
        self._widzety["skan_info"].pack(side="right")
        self._pokaz_stan_skanera()

    def _zbuduj_menu(self) -> None:
        menu = tk.Menu(self)
        plik = tk.Menu(menu, tearoff=False)
        plik.add_command(label=t("akcja.nowy_egzemplarz"), accelerator="Ctrl+N",
                         command=self.nowy_egzemplarz)
        plik.add_command(label=t("akcja.nowa_lokalizacja"), command=self.nowa_lokalizacja)
        plik.add_command(label=t("akcja.katalog_modeli"), accelerator="Ctrl+M",
                         command=self.katalog_modeli)
        plik.add_command(label=t("akcja.etykiety"), accelerator="Ctrl+P", command=self.drukuj_etykiety)
        plik.add_command(label=t("akcja.eksport"), accelerator="Ctrl+E", command=self.eksportuj)
        plik.add_command(label=t("akcja.slowniki"), command=self.slowniki)
        plik.add_separator()
        plik.add_command(label=t("akcja.telefon"), accelerator="Ctrl+T", command=self.telefon)
        plik.add_separator()
        plik.add_command(label=t("akcja.zakoncz"), accelerator="Ctrl+Q", command=self.destroy)
        menu.add_cascade(label=t("menu.plik"), menu=plik)

        widok = tk.Menu(menu, tearoff=False)
        for tryb in TRYBY:
            widok.add_radiobutton(label=t(TRYB_KLUCZ[tryb]), value=tryb, variable=self.tryb_var,
                                  command=self._tryb_zmieniony)
        widok.add_separator()
        widok.add_command(label=t("akcja.odswiez"), accelerator="F5", command=self.odswiez)
        menu.add_cascade(label=t("menu.widok"), menu=widok)

        jezyk = tk.Menu(menu, tearoff=False)
        for kod in JEZYKI:
            jezyk.add_radiobutton(label=t(f"jezyk.{kod}"), value=kod, variable=self.jezyk_var,
                                  command=self.przelacz_jezyk)
        menu.add_cascade(label=t("menu.jezyk"), menu=jezyk)

        pomoc = tk.Menu(menu, tearoff=False)
        pomoc.add_command(label=t("akcja.o_programie"), command=self.o_programie)
        menu.add_cascade(label=t("menu.pomoc"), menu=pomoc)
        self.configure(menu=menu)

    # ----------------------------------------------------- język i przebudowa
    def przelacz_jezyk(self, jezyk: str | None = None) -> None:
        jezyk = ustaw_jezyk(jezyk or self.jezyk_var.get())
        self.jezyk_var.set(jezyk)
        ustawienia.zapisz(self.db, "jezyk", jezyk)
        self.przebuduj()

    def przebuduj(self) -> None:
        self._zapamietaj_stan()
        for dziecko in self.winfo_children():
            if not isinstance(dziecko, tk.Toplevel):
                dziecko.destroy()
        self.configure(menu="")
        self._zbuduj_ui()
        self.odswiez(zapamietaj=False)
        for okno in list(self._dialogi):
            if okno.winfo_exists():
                okno.przebuduj()
            else:
                self.wyrejestruj(okno)

    def _zapamietaj_stan(self) -> None:
        drzewo = self._widzety.get("drzewo")
        if drzewo is None or not drzewo.winfo_exists():
            return
        self.stan.tryb = self.tryb_var.get()
        self.stan.rozwiniete = {iid for iid in self._wszystkie_iid() if drzewo.item(iid, "open")}
        zaznaczenie = drzewo.selection()
        self.stan.zaznaczone = zaznaczenie[0] if zaznaczenie else None
        self.stan.przewiniecie = drzewo.yview()[0]
        self.stan.zakladka = self._widzety["szczegoly"].zakladka()
        try:
            self.stan.podzial = self._widzety["podzial"].sashpos(0)
        except tk.TclError:
            pass

    def _wszystkie_iid(self) -> list[str]:
        drzewo, wynik, stos = self._widzety["drzewo"], [], list(self._widzety["drzewo"].get_children())
        while stos:
            iid = stos.pop()
            wynik.append(iid)
            stos.extend(drzewo.get_children(iid))
        return wynik

    # --------------------------------------------------------------- dane
    def odswiez(self, zaznacz: str | None = None, zapamietaj: bool = True) -> None:
        """Wczytuje dane od nowa i odtwarza stan drzewa."""
        if zapamietaj:
            self._zapamietaj_stan()
        if zaznacz:
            self.stan.zaznaczone = zaznacz
        drzewo = self._widzety["drzewo"]
        lok = lokalizacje.wszystkie(self.db)
        egz = egzemplarze.lista(self.db)
        filtr = self.filtr_var.get()
        wezly = zbuduj_wezly(lok, egz, self.tryb_var.get(), filtr)

        drzewo.delete(*drzewo.get_children())
        for w in wezly:
            drzewo.insert(w.rodzic, "end", iid=w.iid, text=w.tekst, values=w.wartosci,
                          tags=w.tagi, open=bool(filtr) or w.iid in self.stan.rozwiniete)

        zaznaczone = self.stan.zaznaczone
        if zaznaczone and drzewo.exists(zaznaczone):
            rodzic = drzewo.parent(zaznaczone)
            while rodzic:                       # nowy element ma być widoczny
                drzewo.item(rodzic, open=True)
                rodzic = drzewo.parent(rodzic)
            drzewo.selection_set(zaznaczone)
            drzewo.focus(zaznaczone)
        else:
            self.stan.zaznaczone = None
            self._widzety["szczegoly"].pokaz(None)
        self.update_idletasks()
        drzewo.yview_moveto(self.stan.przewiniecie)
        if zaznaczone and drzewo.exists(zaznaczone):
            drzewo.see(zaznaczone)
            self._widzety["szczegoly"].pokaz(zaznaczone, self.stan.zakladka)
        self.after_idle(self._przywroc_podzial)
        self._widzety["licznik"].configure(text=t("pasek.licznik", egzemplarze=len(egz),
                                           lokalizacje=len(lok)))
        for okno in list(self._dialogi):
            if okno.winfo_exists() and hasattr(okno, "dane_zmienione"):
                okno.dane_zmienione()

    def _przywroc_podzial(self) -> None:
        try:
            podzial = self._widzety["podzial"]
            if self.stan.podzial is None:      # pierwsze uruchomienie: ok. 58% dla drzewa
                szerokosc = podzial.winfo_width()
                if szerokosc <= 1:
                    return
                self.stan.podzial = int(szerokosc * 0.58)
            podzial.sashpos(0, self.stan.podzial)
        except (tk.TclError, KeyError):
            pass

    # --------------------------------------------------------------- zdarzenia
    def _wybrano(self, _zdarzenie=None) -> None:
        zaznaczenie = self._widzety["drzewo"].selection()
        self.stan.zaznaczone = zaznaczenie[0] if zaznaczenie else None
        self._widzety["szczegoly"].pokaz(self.stan.zaznaczone, self._widzety["szczegoly"].zakladka())

    def _dwuklik(self, _zdarzenie=None) -> None:
        rodzaj, ident = rozbierz_iid(self.stan.zaznaczone)
        if rodzaj == "E":
            self.edytuj_egzemplarz(ident)
        elif rodzaj == "L":
            self.edytuj_lokalizacje(ident)

    def _menu_kontekstowe(self, zdarzenie) -> None:
        drzewo = self._widzety["drzewo"]
        iid = drzewo.identify_row(zdarzenie.y)
        if not iid:
            return
        drzewo.selection_set(iid)
        rodzaj, ident = rozbierz_iid(iid)
        menu = tk.Menu(self, tearoff=False)
        if rodzaj == "L":
            menu.add_command(label=t("akcja.edytuj"), command=lambda: self.edytuj_lokalizacje(ident))
            menu.add_command(label=t("akcja.dodaj_tutaj"),
                             command=lambda: self.nowy_egzemplarz(lokalizacja_id=ident))
            menu.add_command(label=t("akcja.podlokalizacja"),
                             command=lambda: self.nowa_lokalizacja(rodzic_id=ident))
            menu.add_separator()
            menu.add_command(label=t("akcja.usun"), command=lambda: self.usun_lokalizacje(ident))
        elif rodzaj == "E":
            menu.add_command(label=t("akcja.edytuj"), command=lambda: self.edytuj_egzemplarz(ident))
            menu.add_command(label=t("akcja.dodaj_czesc"),
                             command=lambda: self.nowy_egzemplarz(rodzic_id=ident))
            menu.add_command(label=t("akcja.dodaj_zdjecia"),
                             command=lambda: self._widzety["szczegoly"].dodaj_zdjecia(ident))
            menu.add_separator()
            menu.add_command(label=t("akcja.przenies_kategorie"), command=lambda: self.przenies_kategorie(ident))
            menu.add_separator()
            menu.add_command(label=t("akcja.usun"), command=lambda: self.usun_egzemplarz(ident))
        else:
            return
        try:
            menu.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
        finally:
            menu.grab_release()

    def _tryb_zmieniony(self) -> None:
        self.stan.tryb = self.tryb_var.get()
        self.odswiez()

    def _filtr_zmieniony(self, *_):
        # Opóźnienie, żeby nie przebudowywać drzewa po każdym znaku
        if self._zadanie_filtra:
            self.after_cancel(self._zadanie_filtra)
        self._zadanie_filtra = self.after(250, self._zastosuj_filtr)

    def _zastosuj_filtr(self) -> None:
        self._zadanie_filtra = None
        if self._widzety.get("drzewo") is not None and self._widzety["drzewo"].winfo_exists():
            self.odswiez()

    # ------------------------------------------------------------------ akcje
    def nowy_egzemplarz(self, lokalizacja_id: int | None = None, rodzic_id: int | None = None):
        from gui.okno_egzemplarza import OknoEgzemplarza
        if lokalizacja_id is None and rodzic_id is None:
            rodzaj, ident = rozbierz_iid(self.stan.zaznaczone)
            if rodzaj == "L":
                lokalizacja_id = ident
        okno = OknoEgzemplarza(self, None, lokalizacja_id=lokalizacja_id, rodzic_id=rodzic_id)
        okno.pokaz()
        return okno

    def edytuj_egzemplarz(self, egz_id: int, zakladka: int = 0):
        from gui.okno_egzemplarza import OknoEgzemplarza
        okno = OknoEgzemplarza(self, egz_id, zakladka=zakladka)
        okno.pokaz()
        return okno

    def nowa_lokalizacja(self, rodzic_id: int | None = None):
        from gui.okno_lokalizacji import OknoLokalizacji
        okno = OknoLokalizacji(self, None, rodzic_id=rodzic_id)
        okno.pokaz()
        return okno

    def edytuj_lokalizacje(self, lok_id: int):
        from gui.okno_lokalizacji import OknoLokalizacji
        okno = OknoLokalizacji(self, lok_id)
        okno.pokaz()
        return okno

    def edytuj_model(self, model_id: int):
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self, model_id, po_zapisie=lambda _id: self.odswiez())
        okno.pokaz()
        return okno

    def katalog_modeli(self):
        """Jedno okno katalogu: ponowne wywołanie wyciąga istniejące na wierzch."""
        from gui.okno_katalogu import OknoKataloguModeli
        for okno in self._dialogi:
            if isinstance(okno, OknoKataloguModeli) and okno.winfo_exists():
                okno.lift()
                return okno
        okno = OknoKataloguModeli(self)
        okno.pokaz()
        return okno

    def drukuj_etykiety(self):
        """Okno etykiet dla bieżącego zaznaczenia (egzemplarz, lokalizacja albo całość)."""
        from gui.okno_etykiet import OknoEtykiet
        okno = OknoEtykiet(self, self.stan.zaznaczone)
        okno.pokaz()
        return okno

    def eksportuj(self):
        from gui.okno_eksportu import OknoEksportu
        okno = OknoEksportu(self, self.stan.zaznaczone)
        okno.pokaz()
        return okno

    # ------------------------------------------------------------------ skaner
    def _fokus_skanera(self) -> None:
        pole = self._widzety.get("skan")
        if pole is not None and pole.winfo_exists():
            pole.focus_set()
            pole.select_range(0, "end")

    def _skan_z_pola(self) -> None:
        kod = self.skan_var.get()
        self.skan_var.set("")
        if kod.strip():
            self.obsluz_skan(kod, "klawiatura")

    def obsluz_skan(self, kod: str, zrodlo: str):
        """Wspólna obsługa skanu z każdego źródła: pole „Skanuj” albo telefon.
        Egzemplarz i lokalizacja są pokazywane w drzewie; nieznany kod — komunikat
        w stopce (bez okna modalnego: skanuje się seriami)."""
        from uslugi import skaner
        wynik = skaner.rozpoznaj(self.db, kod)
        if wynik.typ == "nieznany":
            self.bell()
            self._ostatni_skan = ("skaner.nieznany", {"kod": wynik.kod or "—"})
        else:
            iid = (iid_egzemplarza if wynik.typ == "egzemplarz" else iid_lokalizacji)(wynik.ident)
            if self.filtr_var.get():
                self.filtr_var.set("")      # filtr mógłby ukryć zeskanowany element
            self.odswiez(zaznacz=iid)
            if wynik.typ == "lokalizacja":
                # rozwinięcie PO odświeżeniu — odświeżenie zapisuje bieżący stan drzewa
                # i nadpisałoby wcześniejszy wpis; pudełko ma pokazać zawartość
                self._widzety["drzewo"].item(iid, open=True)
                self.stan.rozwiniete.add(iid)
            self._ostatni_skan = ("skaner.ostatni_telefon" if zrodlo == "telefon" else "skaner.ostatni",
                                  {"kod": wynik.kod})
        self._pokaz_stan_skanera()
        return wynik

    def _pokaz_stan_skanera(self) -> None:
        etykieta = self._widzety.get("skan_info")
        if etykieta is None or not etykieta.winfo_exists():
            return
        czesci = []
        if self._ostatni_skan:
            klucz, pola = self._ostatni_skan
            czesci.append(t(klucz, **pola))
        if self.serwer is not None and self.serwer.dziala:
            czesci.append(t("skaner.serwer_dziala"))
        etykieta.configure(text="   ".join(czesci))

    def _obsluga_mostu(self, rodzaj: str, dane):
        """Zapytania serwera telefonu — wykonywane tutaj, w wątku interfejsu."""
        from uslugi import skaner
        if rodzaj == "skan":
            wynik = self.obsluz_skan(dane, "telefon")
            return skaner.karta_mobilna(self.db, wynik)
        if rodzaj == "zdjecie":
            return self._zdjecie_z_telefonu(dane)
        raise ValueError(rodzaj)

    def _zdjecie_z_telefonu(self, dane: dict) -> dict:
        """Zapis zdjęcia przysłanego z telefonu. Miniatura i suma są już policzone
        w wątku serwera — tu tylko kopia do magazynu i rekord w bazie."""
        from datetime import datetime
        from pathlib import Path
        from uslugi import pliki, skaner
        wynik = skaner.rozpoznaj(self.db, dane["kod"])
        if wynik.typ != "egzemplarz":
            from wyjatki import BladNornicy
            raise BladNornicy("mobilny.zdjecie_tylko_egzemplarz")
        # iPhone nazywa każde zdjęcie „image.jpg” — wtedy tytuł z datą
        nazwa = Path(dane.get("nazwa") or "").stem
        if nazwa.lower() in ("", "image", "blob", "photo"):
            nazwa = t("mobilny.tytul_zdjecia", data=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        zasob = pliki.dodaj_plik(self.db, dane["sciezka"], {"egzemplarz_id": wynik.ident}, typ="zdjecie",
                                 tytul=nazwa, wstepnie=dane.get("wstepnie"))
        if dane.get("glowne"):          # decyduje pole na telefonie (domyślnie zaznaczone, gdy brak głównego)
            pliki.ustaw_zdjecie_glowne(self.db, wynik.ident, zasob)
        self.odswiez(zaznacz=iid_egzemplarza(wynik.ident))
        self._ostatni_skan = ("skaner.zdjecie_z_telefonu", {"kod": wynik.kod})
        self._pokaz_stan_skanera()
        karta = skaner.karta_mobilna(self.db, wynik)
        karta["komunikat"] = t("mobilny.zdjecie_dodane")
        return karta

    def _pompuj_most(self) -> None:
        try:
            self.most.obsluz_oczekujace(self._obsluga_mostu)
        finally:
            try:
                self.after(100, self._pompuj_most)
            except tk.TclError:
                pass                       # okno już zamknięte

    def telefon(self):
        """Jedno okno telefonu: ponowne wywołanie wyciąga istniejące na wierzch."""
        from gui.okno_telefonu import OknoTelefonu
        for okno in self._dialogi:
            if isinstance(okno, OknoTelefonu) and okno.winfo_exists():
                okno.lift()
                return okno
        okno = OknoTelefonu(self)
        okno.pokaz()
        return okno

    def report_callback_exception(self, typ, wartosc, slad) -> None:
        """Błąd w obsłudze zdarzenia (kliknięcie, zmiana rozmiaru…): do dziennika,
        do terminala i w okienku — zamiast cichego śladu w terminalu."""
        import time
        import traceback
        import dziennik
        from tkinter import messagebox
        from wyjatki import BladNornicy
        dziennik.blad("Błąd w obsłudze zdarzenia okna", exc_info=(typ, wartosc, slad))
        traceback.print_exception(typ, wartosc, slad)
        if isinstance(wartosc, BladNornicy):
            messagebox.showerror(t("okno.blad"), wartosc.komunikat(), parent=self)
            return
        teraz = time.monotonic()
        if teraz - getattr(self, "_ostatni_komunikat_bledu", 0) < 3:
            return                         # seria błędów (np. przy zmianie rozmiaru) — jeden komunikat
        self._ostatni_komunikat_bledu = teraz
        messagebox.showerror(t("okno.blad"), t("blad.wewnetrzny", plik=str(dziennik.plik() or "—"),
                                                 opis=f"{typ.__name__}: {wartosc}"), parent=self)

    def destroy(self) -> None:
        if self.serwer is not None:
            self.serwer.zatrzymaj()        # serwer nie może przeżyć programu
        super().destroy()

    def przenies_kategorie(self, egz_id: int):
        """Egzemplarz z modelem: przenosi się model (kategoria należy do niego)."""
        from gui.okno_przeniesienia import OknoPrzeniesienia
        model_id = self.db.execute("SELECT model_id FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()[0]
        okno = (OknoPrzeniesienia(self, model_id=model_id) if model_id is not None
                else OknoPrzeniesienia(self, egz_id=egz_id))
        okno.pokaz()
        return okno

    def slowniki(self):
        """Jedno okno słowników: ponowne wywołanie wyciąga istniejące na wierzch."""
        from gui.okno_slownikow import OknoSlownikow
        for okno in self._dialogi:
            if isinstance(okno, OknoSlownikow) and okno.winfo_exists():
                okno.lift()
                return okno
        okno = OknoSlownikow(self)
        okno.pokaz()
        return okno

    def o_programie(self) -> None:
        from gui.okna_info import OknoOProgramie
        OknoOProgramie(self).pokaz()

    def usun_zaznaczone(self) -> None:
        rodzaj, ident = rozbierz_iid(self.stan.zaznaczone)
        if rodzaj == "E":
            self.usun_egzemplarz(ident)
        elif rodzaj == "L":
            self.usun_lokalizacje(ident)

    def usun_egzemplarz(self, egz_id: int) -> None:
        blokujace, kaskadowe = zaleznosci(self.db, "egzemplarz", egz_id)
        czesci = blokujace.pop(("egzemplarz", "rodzic_id"), 0)
        if blokujace:
            messagebox.showwarning(t("okno.uwaga"), t("blad.usuwanie_zablokowane",
                                                      lista=opis(blokujace)), parent=self)
            return
        wiersz = egzemplarze.pobierz(self.db, egz_id)
        pytanie = t("pytanie.usun_egzemplarz", nazwa=egzemplarze.nazwa_wyswietlana(wiersz))
        if czesci:
            pytanie += "\n\n" + t("pytanie.usun_z_czesciami", liczba=czesci)
        if kaskadowe:
            pytanie += "\n\n" + t("pytanie.usun_tez", lista=opis(kaskadowe))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            inwentarz.usun_egzemplarz(self.db, egz_id)
        except Exception as blad:   # noqa: BLE001 — każdy błąd trafia do użytkownika
            pokaz_blad(self, blad)
            return
        self.stan.zaznaczone = None
        self.odswiez()

    def usun_lokalizacje(self, lok_id: int) -> None:
        wiersz = lokalizacje.pobierz(self.db, lok_id)
        blokujace, _ = zaleznosci(self.db, "lokalizacja", lok_id)
        przenies = False
        if blokujace:
            cel = (lokalizacje.pobierz(self.db, wiersz["rodzic_id"])["nazwa"]
                   if wiersz["rodzic_id"] else t("lokalizacja.brak"))
            pytanie = t("pytanie.usun_lokalizacje_z_zawartoscia", nazwa=wiersz["nazwa"],
                        lista=opis(blokujace), cel=cel)
            przenies = True
        else:
            pytanie = t("pytanie.usun_lokalizacje", nazwa=wiersz["nazwa"])
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            inwentarz.usun_lokalizacje(self.db, lok_id, przenies_zawartosc=przenies)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.stan.zaznaczone = iid_lokalizacji(wiersz["rodzic_id"]) if wiersz["rodzic_id"] else None
        self.odswiez()

    def wydziel_z_partii(self, egz_id: int) -> None:
        try:
            nowy = inwentarz.wydziel_z_partii(self.db, egz_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.odswiez(zaznacz=iid_egzemplarza(nowy))
        self.edytuj_egzemplarz(nowy)
