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
from tkinter import ttk

from baza.repozytoria import egzemplarze, lokalizacje, ustawienia
from gui import styl
from gui.akcje_glowne import AkcjeGlowne
from gui.menu_glowne import TRYB_KLUCZ, zbuduj_menu
from gui.model_drzewa import TRYBY, rozbierz_iid, zbuduj_wezly
from gui.skaner_glowny import SkanerGlowny
from gui.szczegoly import PanelSzczegolow
from i18n.tlumacz import jezyk_biezacy, t, ustaw_jezyk
from konfiguracja import KATALOG_PROGRAMU

KOLUMNY = (("kod", "kolumna.kod", 105), ("status", "kolumna.status", 100),
           ("kategoria", "kolumna.kategoria", 150))


@dataclass
class StanWidoku:
    tryb: str = "lokalizacje"
    rozwiniete: set = field(default_factory=set)
    zaznaczone: str | None = None
    przewiniecie: float = 0.0
    zakladka: int = 0
    podzial: int | None = None


class OknoGlowne(AkcjeGlowne, SkanerGlowny, tk.Tk):
    def __init__(self, polaczenie, pokaz_powitanie: bool = True):
        super().__init__(className="Nornica")
        self.db = polaczenie
        if pokaz_powitanie:
            self.withdraw()
        self.motyw = styl.nazwa_motywu(ustawienia.pobierz(self.db, "motyw"))
        self.czcionki = styl.ustaw(self, self.motyw)
        self._grafiki = self._wczytaj_grafiki()
        if self._grafiki.get("ikony"):
            self.iconphoto(True, *self._grafiki["ikony"])

        # Stan trwały: żyje w obiekcie, przeżywa przebudowę okna
        self.stan = StanWidoku()
        self.filtr_var = tk.StringVar()
        self.filtr_var.trace_add("write", self._filtr_zmieniony)
        self.tryb_var = tk.StringVar(value=self.stan.tryb)
        self.jezyk_var = tk.StringVar(value=jezyk_biezacy())
        self.motyw_var = tk.StringVar(value=self.motyw)
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
        self.bind("<Control-b>", lambda _e: self.kopia_zapasowa())
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
        zbuduj_menu(self)
        self._zbuduj_pasek()
        podzial = ttk.Panedwindow(self, orient="horizontal")
        podzial.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self._widzety["podzial"] = podzial
        podzial.add(self._zbuduj_drzewo(podzial), weight=3)
        prawa = ttk.Frame(podzial, padding=(14, 0, 0, 0))
        self._widzety["szczegoly"] = PanelSzczegolow(self, prawa)
        podzial.add(prawa, weight=2)
        self._zbuduj_stopke()

    def _zbuduj_pasek(self) -> None:
        """Przyciski, przełącznik widoku, pole skanera i wyszukiwarka."""
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
                            command=self.tryb_zmieniony).pack(side="left", padx=(0, 8))
        napis, inny = styl.przelacznik(self.motyw)
        self._widzety["motyw"] = ttk.Button(pasek, text=napis, style="Motyw.TButton", width=3,
                                            command=lambda: self.przelacz_motyw(inny))
        self._widzety["motyw"].pack(side="right", padx=(10, 0))
        # Skaner i wyszukiwarka w ramce pakowanej NA KOŃCU, a pole wyszukiwania
        # ostatnie w ramce: przy wąskim oknie kurczy się ono, nie napisy
        # (wcześniej przy 1180 px „Skanuj” dostawało 1 piksel).
        szukanie = ttk.Frame(pasek)
        szukanie.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ttk.Label(szukanie, text=t("pasek.skanuj")).pack(side="left", padx=(0, 6))
        # Pole skanera: czytnik USB/Bluetooth „wpisuje” kod i naciska Enter
        skan = ttk.Entry(szukanie, textvariable=self.skan_var, width=11)
        skan.pack(side="left", padx=(0, 14))
        skan.bind("<Return>", lambda _e: self._skan_z_pola())
        skan.bind("<KP_Enter>", lambda _e: self._skan_z_pola())
        ttk.Label(szukanie, text=t("pasek.szukaj")).pack(side="left", padx=(0, 6))
        szukaj = ttk.Entry(szukanie, textvariable=self.filtr_var, width=8)
        szukaj.pack(side="left", fill="x", expand=True)
        self._widzety["skan"] = skan
        self._widzety["szukaj"] = szukaj
        self.bind("<Control-f>", lambda _e: self._widzety["szukaj"].focus_set())

    def _zbuduj_drzewo(self, podzial: ttk.Panedwindow) -> ttk.Frame:
        """Drzewo lokalizacji i egzemplarzy z przewijakiem; kolory według statusu."""
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
        return lewa

    def _zbuduj_stopke(self) -> None:
        stopka = ttk.Frame(self, padding=(10, 4))
        stopka.pack(fill="x")
        self._widzety["licznik"] = ttk.Label(stopka, style="Opis.TLabel")
        self._widzety["licznik"].pack(side="left")
        self._widzety["skan_info"] = ttk.Label(stopka, style="Opis.TLabel")
        self._widzety["skan_info"].pack(side="right")
        self._pokaz_stan_skanera()

    # ----------------------------------------------------- język i przebudowa
    def przelacz_jezyk(self, jezyk: str | None = None) -> None:
        jezyk = ustaw_jezyk(jezyk or self.jezyk_var.get())
        self.jezyk_var.set(jezyk)
        ustawienia.zapisz(self.db, "jezyk", jezyk)
        self.przebuduj()

    def przelacz_motyw(self, motyw: str | None = None) -> None:
        """Jasny ↔ ciemny: przycisk ☀/☾ na pasku albo menu Widok. Zapamiętany w bazie."""
        self.motyw = styl.nazwa_motywu(motyw or self.motyw_var.get())
        self.motyw_var.set(self.motyw)
        styl.ustaw(self, self.motyw, self.czcionki)
        ustawienia.zapisz(self.db, "motyw", self.motyw)
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
        self.powiadom_okna()

    def powiadom_okna(self) -> None:
        """Otwarte okna liczą swoje dane od nowa (bez przebudowy drzewa)."""
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

    def tryb_zmieniony(self) -> None:
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
        # Zaplanowane zadania (most telefonu, filtr, podział) anulowane jawnie:
        # ttkbootstrap trzyma odwołanie do okna, więc interpreter Tcl żyje dłużej
        # i bez tego zadania odpaliłyby po zamknięciu (w testach — w cudzym oknie).
        try:
            for zadanie in self.tk.splitlist(self.tk.call("after", "info")):
                self.after_cancel(zadanie)
        except tk.TclError:
            pass
        super().destroy()
