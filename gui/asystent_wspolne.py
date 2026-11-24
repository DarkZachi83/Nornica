# SPDX-License-Identifier: GPL-3.0-or-later
"""Część wspólna okien asystenta AI (jeden model i tryb wsadowy).

  - ustawienia: model z Ollamy, wyszukiwarka, adres SearXNG / klucz API,
  - praca w wątkach pobocznych i odbiór wiadomości w wątku interfejsu,
  - ocena propozycji i domyślne zaznaczenie.

Klasa pomocnicza PracaAsystenta korzysta z atrybutów okna dialogowego (db,
after, winfo_exists) i wymaga od okna metod _odbierz() i _odswiez().
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from asystent import wyszukiwarki
from asystent.ollama import Ollama
from asystent.propozycje import BRAK, INNA_NAZWA, PELNE, PODOBNE, Asystent
from baza.repozytoria import ustawienia
from i18n.tlumacz import t
from wyjatki import BladNornicy

MODEL_DOMYSLNY = "qwen3:8b"
ADRES_KLUCZY = "https://ollama.com/settings/keys"
POSREDNIE = {"krok", "pozycja"}          # wiadomości w trakcie pracy wątku; pozostałe ją kończą


# Obie funkcje działają w wątku pobocznym, więc dostają gotowe wartości
# (słownik z ustawienia()), a nie zmienne tkintera — te wolno czytać tylko
# w wątku interfejsu.
def fabryka_domyslna(u: dict) -> Asystent:
    """Prawdziwa Ollama i wybrana wyszukiwarka (testy podstawiają własną fabrykę)."""
    return Asystent(Ollama(u["ollama"]), wyszukiwarki.wyszukiwarka(u["zrodlo"], u["searxng"], u["klucz"]),
                    u["model"])


def lista_modeli_domyslna(u: dict) -> list[str]:
    return Ollama(u["ollama"]).modele()


def ocena(w, obecna: str = "") -> tuple[str, bool]:
    """Tekst kolumny „Ocena” i czy to ostrzeżenie (wiersz na pomarańczowo).
    Kolejność: najpierw to, co dyskwalifikuje, potem porównanie z formularzem."""
    if w.blad:
        return t(w.blad), True
    if w.dopasowanie == INNA_NAZWA:
        return t("asystent.nazwa_innego_produktu"), True
    if w.zrodlo is not None and w.dopasowanie == BRAK:
        return t("asystent.zrodlo_bez_oznaczenia"), True
    if w.zrodlo is not None and w.dopasowanie == PODOBNE:
        return t("asystent.zrodlo_podobne", oznaczenie=w.podobne), True
    if not w.potwierdzona:
        return t("asystent.niepotwierdzona"), True
    obecna = (obecna or "").strip()
    if obecna and obecna.casefold() == w.tekst.casefold():
        return t("asystent.zgodna"), False
    if obecna:
        return t("asystent.inna_niz_w_formularzu"), True
    return t("asystent.potwierdzona"), False


def domyslnie_zaznaczona(w, obecna: str = "") -> bool:
    """Tylko pewne propozycje dla PUSTYCH pól: cytat potwierdzony, źródło wymienia
    oznaczenie przedmiotu. Zmianę wpisanej wartości użytkownik wybiera sam."""
    return (w.mozna_wstawic and w.potwierdzona and w.dopasowanie == PELNE
            and not (obecna or "").strip())


class PracaAsystenta:
    """Ustawienia asystenta i praca w tle — wspólne dla okien asystenta."""

    def _przygotuj_asystenta(self, fabryka, lista_modeli) -> None:
        self._fabryka, self._lista_modeli = fabryka, lista_modeli
        u = lambda klucz, domyslna="": ustawienia.pobierz(self.db, klucz) or domyslna  # noqa: E731
        self.model = tk.StringVar(value=u("asystent_model", MODEL_DOMYSLNY))
        self.zrodlo = tk.StringVar(value=u("asystent_zrodlo", "searxng"))
        self.searxng = tk.StringVar(value=u("asystent_searxng", "http://127.0.0.1:8888"))
        self.adres_ollamy = tk.StringVar(value=u("asystent_ollama", "http://127.0.0.1:11434"))
        self.klucz = tk.StringVar(value=wyszukiwarki.klucz_api())
        self.modele: list[str] = []
        self.stan_ollamy: BladNornicy | None = None
        self.blad: Exception | None = None
        self.postep = ""                     # opis bieżącego kroku (tekst)
        self.pracuje = False
        self._kolejka: queue.Queue = queue.Queue()
        self._w_tle = 0                      # wątki, na których wynik jeszcze czekamy
        self._anuluj = threading.Event()
        self.wczytaj_modele()

    # ------------------------------------------------------------------ widok
    def _sekcja_ustawien(self, ramka: ttk.Frame) -> None:
        sekcja = ttk.LabelFrame(ramka, text=t("asystent.ustawienia"), padding=10)
        sekcja.pack(fill="x")
        ttk.Label(sekcja, text=t("asystent.model"), style="Pole.TLabel").grid(row=0, column=0, sticky="w")
        self._modele = ttk.Combobox(sekcja, textvariable=self.model, values=self.modele, width=30)
        self._modele.grid(row=0, column=1, sticky="w", padx=(8, 6))
        ttk.Button(sekcja, text=t("asystent.odswiez_modele"), style="Maly.TButton",
                   command=self.wczytaj_modele).grid(row=0, column=2, sticky="w")
        self._stan_ollamy = ttk.Label(sekcja, style="Opis.TLabel", wraplength=420, justify="left")
        self._stan_ollamy.grid(row=0, column=3, sticky="w", padx=(10, 0))
        ttk.Label(sekcja, text=t("asystent.zrodlo"), style="Pole.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        wybor = ttk.Frame(sekcja)
        wybor.grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(6, 0))
        for zrodlo in wyszukiwarki.ZRODLA:
            ttk.Radiobutton(wybor, text=t(f"asystent.zrodlo_{zrodlo}"), value=zrodlo, variable=self.zrodlo,
                            command=self._buduj_pole_zrodla).pack(side="left", padx=(0, 12))
        self._ramka_zrodla = ttk.Frame(sekcja)
        self._ramka_zrodla.grid(row=2, column=1, columnspan=3, sticky="we", padx=(8, 0), pady=(4, 0))
        sekcja.columnconfigure(3, weight=1)
        self._buduj_pole_zrodla()

    def _buduj_pole_zrodla(self) -> None:
        for dziecko in self._ramka_zrodla.winfo_children():
            dziecko.destroy()
        if self.zrodlo.get() == "searxng":
            ttk.Label(self._ramka_zrodla, text=t("asystent.adres_searxng"), style="Pole.TLabel").pack(side="left")
            ttk.Entry(self._ramka_zrodla, textvariable=self.searxng, width=36).pack(side="left", padx=(8, 0))
            ttk.Label(self._ramka_zrodla, text=t("asystent.searxng_podpowiedz"), style="Opis.TLabel").pack(
                side="left", padx=(8, 0))
            return
        ttk.Label(self._ramka_zrodla, text=t("asystent.klucz"), style="Pole.TLabel").pack(side="left")
        ttk.Entry(self._ramka_zrodla, textvariable=self.klucz, show="•", width=36).pack(side="left", padx=(8, 0))
        link = ttk.Label(self._ramka_zrodla, text=t("asystent.klucz_skad"), style="Odnosnik.TLabel", cursor="hand2")
        link.pack(side="left", padx=(8, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(ADRES_KLUCZY))

    def _odswiez_ustawienia(self) -> None:
        self._modele.configure(values=self.modele)
        self._stan_ollamy.configure(text=self.stan_ollamy.komunikat() if self.stan_ollamy else
                                    t("asystent.modele_ollamy", ile=len(self.modele)) if self.modele else "")

    def _odswiez_pracy(self, start: ttk.Button, stop: ttk.Button, pasek: ttk.Progressbar) -> None:
        start.state(["disabled"] if self.pracuje else ["!disabled"])
        stop.state(["!disabled"] if self.pracuje else ["disabled"])
        if self.pracuje:
            pasek.configure(mode="indeterminate")
            pasek.start(12)
        else:                                # zatrzymany pasek „w ruchu” zostawia kawałek wskaźnika
            pasek.stop()
            pasek.configure(mode="determinate", value=0)

    # ------------------------------------------------------------------ praca
    def ustawienia(self) -> dict:
        """Ustawienia jako zwykłe napisy — do przekazania wątkowi pobocznemu."""
        return {"model": self.model.get().strip(), "zrodlo": self.zrodlo.get(), "searxng": self.searxng.get().strip(),
                "klucz": self.klucz.get().strip(), "ollama": self.adres_ollamy.get().strip()}

    def _zapisz_ustawienia(self) -> None:
        for klucz, zmienna in (("asystent_model", self.model), ("asystent_zrodlo", self.zrodlo),
                               ("asystent_searxng", self.searxng), ("asystent_ollama", self.adres_ollamy)):
            ustawienia.zapisz(self.db, klucz, zmienna.get().strip())
        if self.klucz.get().strip() != wyszukiwarki.klucz_api():
            wyszukiwarki.zapisz_klucz(self.klucz.get())

    def _gotowy_do_pracy(self) -> bool:
        if self.pracuje:
            return False
        if not self.model.get().strip():
            self.blad = BladNornicy("asystent.brak_modelu")
            self._odswiez()
            return False
        self._zapisz_ustawienia()
        self._anuluj = threading.Event()
        return True

    def wczytaj_modele(self) -> None:
        """Lista modeli z Ollamy w tle; brak Ollamy to komunikat, nie błąd okna."""
        u, kolejka, lista_modeli = self.ustawienia(), self._kolejka, self._lista_modeli

        def w_tle():                         # bez odwołań do okna — patrz _uruchom_watek
            try:
                kolejka.put(("modele", lista_modeli(u), None))
            except Exception as blad:   # noqa: BLE001
                kolejka.put(("modele", [], blad))
        self._uruchom_watek(w_tle, "asystent-modele")

    def _uruchom_watek(self, cel, nazwa: str) -> None:
        """cel NIE może odwoływać się do okna (self): gdy wątek skończy się ostatni,
        sprzątałby okno i jego zmienne tkintera poza wątkiem głównym — tkinter
        zgłasza wtedy „main thread is not in main loop” i blokuje się na sekundę
        przy każdej zmiennej. Wątek dostaje kolejkę i gotowe wartości.

        Z tego samego powodu przed startem sprzątamy pamięć TU, w wątku głównym:
        zamknięte wcześniej okna czekają na zbieracz cykli, a ten uruchamia się
        w wątku, który akurat tworzy dużo obiektów — czyli w wątku asystenta."""
        import gc
        gc.collect()
        self._w_tle += 1
        threading.Thread(target=cel, name=nazwa, daemon=True).start()
        if self._w_tle == 1:                 # jedna pętla odbioru na wszystkie wątki
            self.after(100, self._czekaj)

    def przerwij(self) -> None:
        self._anuluj.set()
        self.postep = t("asystent.przerywam")
        self._odswiez()

    def _czekaj(self) -> None:
        """Odbiór wiadomości z wątku pobocznego (tylko tu dotykamy okna)."""
        if not self.winfo_exists():
            return
        zmiana = False
        try:
            while True:
                rodzaj, wartosc, dodatek = self._kolejka.get_nowait()
                if not self._odbierz_wspolne(rodzaj, wartosc, dodatek):
                    self._odbierz(rodzaj, wartosc, dodatek)
                if rodzaj not in POSREDNIE:
                    self._w_tle -= 1
                zmiana = True
        except queue.Empty:
            pass
        if self._w_tle > 0:
            self.after(100, self._czekaj)
        if zmiana:
            self._odswiez()

    def _odbierz_wspolne(self, rodzaj: str, wartosc, dodatek) -> bool:
        if rodzaj == "modele":
            self.modele, self.stan_ollamy = wartosc, (dodatek if isinstance(dodatek, BladNornicy) else
                                                      BladNornicy("asystent.blad_ollamy", opis=str(dodatek))
                                                      if dodatek else None)
            if self.modele and self.model.get() not in self.modele and MODEL_DOMYSLNY in self.modele:
                self.model.set(MODEL_DOMYSLNY)
            return True
        if rodzaj == "krok":
            self.postep = t(wartosc, **dodatek)
            return True
        if rodzaj == "przerwano":
            self.pracuje, self.blad = False, BladNornicy("asystent.przerwano")
            return True
        if rodzaj == "blad":
            self.pracuje, self.blad = False, dodatek
            return True
        return False

    def czekaj_na_wynik(self, limit: float = 10.0) -> None:
        """Dla testów: obsługa kolejki aż praca się skończy."""
        import time
        koniec = time.monotonic() + limit
        while self._w_tle > 0 and time.monotonic() < koniec:
            self.update()
            time.sleep(0.02)
        self._czekaj()

    def zamknij(self) -> None:
        self._anuluj.set()
        super().zamknij()
