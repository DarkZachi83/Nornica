# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Asystent AI”: parametry modelu z internetu, do przejrzenia i wstawienia.

Otwierane z okna modelu. Asystent szuka w sieci, lokalny model (Ollama)
wyciąga wartości ze znalezionych stron, a program sprawdza każdą z nich
(asystent/propozycje.py). Użytkownik zaznacza, co przyjmuje — wartości
trafiają do FORMULARZA modelu; zapis do bazy dopiero przyciskiem „Zapisz”.

Praca idzie w wątku pobocznym (sieć i model potrafią trwać minutę); do okna
wraca przez kolejkę, odczytywaną w wątku interfejsu. Stan żyje w atrybutach,
więc okno przeżywa zmianę języka i motywu.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from asystent import wyszukiwarki
from asystent.ollama import Ollama, Przerwano
from asystent.propozycje import Asystent, zapytanie
from baza.repozytoria import ustawienia
from gui import styl
from gui.bazowe import OknoDialogowe
from gui.pola import PoleTekstu
from i18n.tlumacz import jezyk_biezacy, t
from wyjatki import BladNornicy

MODEL_DOMYSLNY = "qwen3:8b"
ADRES_KLUCZY = "https://ollama.com/settings/keys"


# Obie funkcje działają w wątku pobocznym, więc dostają gotowe wartości
# (słownik z ustawien()), a nie zmienne tkintera — te wolno czytać tylko
# w wątku interfejsu.
def _fabryka(u: dict) -> Asystent:
    """Prawdziwa Ollama i wybrana wyszukiwarka (testy podstawiają własną fabrykę)."""
    return Asystent(Ollama(u["ollama"]), wyszukiwarki.wyszukiwarka(u["zrodlo"], u["searxng"], u["klucz"]),
                    u["model"])


def _lista_modeli(u: dict) -> list[str]:
    return Ollama(u["ollama"]).modele()


class OknoAsystenta(OknoDialogowe):
    """dane: kategoria (nazwa), producent, nazwa; szablon: pola kategorii;
    obecne(): {kod: tekst w formularzu}; po_zastosowaniu(wynik, kody, nadpisz)."""

    def __init__(self, glowne, szablon: list[dict], dane: dict, obecne, po_zastosowaniu,
                 fabryka=_fabryka, lista_modeli=_lista_modeli):
        super().__init__(glowne)
        self.szablon, self.dane, self.obecne = szablon, dane, obecne
        self.po_zastosowaniu = po_zastosowaniu
        self._fabryka, self._lista_modeli = fabryka, lista_modeli
        u = lambda klucz, domyslna="": ustawienia.pobierz(self.db, klucz) or domyslna  # noqa: E731
        self.model = tk.StringVar(value=u("asystent_model", MODEL_DOMYSLNY))
        self.zrodlo = tk.StringVar(value=u("asystent_zrodlo", "searxng"))
        self.searxng = tk.StringVar(value=u("asystent_searxng", "http://127.0.0.1:8888"))
        self.adres_ollamy = tk.StringVar(value=u("asystent_ollama", "http://127.0.0.1:11434"))
        self.klucz = tk.StringVar(value=wyszukiwarki.klucz_api())
        self.zapytanie = tk.StringVar()
        self.nadpisz = tk.BooleanVar(value=False)
        self.oznaczenia = PoleTekstu(dane.get("oznaczenia", ""))
        self.modele: list[str] = []
        self.stan_ollamy: BladNornicy | None = None
        self.wynik = None
        self.zaznaczone: set[str] = set()
        self.blad: Exception | None = None
        self.postep = ""                     # opis bieżącego kroku (tekst)
        self.pracuje = False
        self._kolejka: queue.Queue = queue.Queue()
        self._w_tle = 0                      # wątki, na których wynik jeszcze czekamy
        self._anuluj = threading.Event()
        self.wczytaj_modele()

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("asystent.tytul"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        self._sekcja_ustawien(ramka)
        self._sekcja_przedmiotu(ramka)
        self._stan = ttk.Label(ramka, style="Opis.TLabel", wraplength=760, justify="left")
        self._stan.pack(fill="x", pady=(8, 0))
        self._pasek = ttk.Progressbar(ramka, mode="indeterminate")
        self._pasek.pack(fill="x", pady=(4, 0))
        self._sekcja_wynikow(ramka)
        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(dol, text=t("trw.nadpisz"), variable=self.nadpisz).pack(side="left")
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        self._wstaw = ttk.Button(dol, text=t("asystent.wstaw"), style="Akcent.TButton", command=self.zastosuj)
        self._wstaw.pack(side="right", padx=(0, 8))
        self._odswiez()

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

    def _sekcja_przedmiotu(self, ramka: ttk.Frame) -> None:
        sekcja = ttk.LabelFrame(ramka, text=t("asystent.przedmiot"), padding=10)
        sekcja.pack(fill="x", pady=(10, 0))
        opis = " · ".join(x for x in (self.dane.get("kategoria"), self.dane.get("producent"),
                                      self.dane.get("nazwa")) if x)
        ttk.Label(sekcja, text=opis or "—").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(sekcja, text=t("asystent.oznaczenia"), style="Pole.TLabel").grid(row=1, column=0, sticky="nw", pady=(6, 0))
        self.oznaczenia.zbuduj(sekcja, height=3, width=60, font=self.glowne.czcionki["zwykla"]).grid(row=1, column=1, columnspan=2, sticky="we",
                                                                padx=(8, 0), pady=(6, 0))
        ttk.Label(sekcja, text=t("asystent.oznaczenia_podpowiedz"), style="Opis.TLabel", wraplength=600,
                  justify="left").grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0))
        ttk.Label(sekcja, text=t("asystent.zapytanie"), style="Pole.TLabel").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(sekcja, textvariable=self.zapytanie).grid(row=3, column=1, sticky="we", padx=(8, 6), pady=(6, 0))
        przyciski = ttk.Frame(sekcja)
        przyciski.grid(row=3, column=2, sticky="e", pady=(6, 0))
        self._start = ttk.Button(przyciski, text=t("asystent.szukaj"), style="Akcent.TButton", command=self.uruchom)
        self._start.pack(side="left")
        self._stop = ttk.Button(przyciski, text=t("asystent.przerwij"), command=self.przerwij)
        self._stop.pack(side="left", padx=(6, 0))
        ttk.Label(sekcja, text=t("asystent.zapytanie_podpowiedz"), style="Opis.TLabel").grid(
            row=4, column=1, columnspan=2, sticky="w", padx=(8, 0))
        sekcja.columnconfigure(1, weight=1)

    def _sekcja_wynikow(self, ramka: ttk.Frame) -> None:
        obszar = ttk.Frame(ramka)
        obszar.pack(fill="both", expand=True, pady=(10, 0))
        kolumny = (("wstaw", 60), ("pole", 170), ("obecnie", 130), ("propozycja", 150), ("pewnosc", 160))
        drzewo = ttk.Treeview(obszar, columns=[k for k, _ in kolumny], show="headings", height=8,
                              selectmode="browse")
        for kod, szerokosc in kolumny:
            drzewo.heading(kod, text=t(f"asystent.kolumna_{kod}"), anchor="w")
            drzewo.column(kod, width=szerokosc, stretch=kod in ("propozycja", "pewnosc"), anchor="w")
        przewijak = ttk.Scrollbar(obszar, orient="vertical", command=drzewo.yview)
        drzewo.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")
        drzewo.pack(side="left", fill="both", expand=True)
        drzewo.tag_configure("niepotwierdzona", foreground=styl.KOLORY_STATUSOW["w_naprawie"])
        drzewo.tag_configure("bledna", foreground=styl.KOLORY_STATUSOW["uszkodzony"])
        drzewo.bind("<Button-1>", self._klik)
        drzewo.bind("<space>", lambda _e: self.przelacz(drzewo.focus()))
        drzewo.bind("<<TreeviewSelect>>", lambda _e: self._pokaz_szczegoly())
        self._drzewo = drzewo
        self._szczegoly = ttk.Label(ramka, wraplength=760, justify="left")
        self._szczegoly.pack(fill="x", pady=(6, 0))
        self._adres = ttk.Label(ramka, style="Odnosnik.TLabel", cursor="hand2")
        self._adres.pack(anchor="w")
        self._adres.bind("<Button-1>", lambda _e: self._otworz_zrodlo())
        self._uwagi = ttk.Label(ramka, style="Opis.TLabel", wraplength=760, justify="left")
        self._uwagi.pack(fill="x", pady=(6, 0))

    def _odswiez(self) -> None:
        """Widok ze stanu w atrybutach — po każdej zmianie i po przebudowie okna."""
        if not hasattr(self, "_drzewo") or not self._drzewo.winfo_exists():
            return
        self._modele.configure(values=self.modele)
        self._stan_ollamy.configure(text=self.stan_ollamy.komunikat() if self.stan_ollamy else
                                    t("asystent.modele_ollamy", ile=len(self.modele)) if self.modele else "")
        self._start.state(["disabled"] if self.pracuje else ["!disabled"])
        self._stop.state(["!disabled"] if self.pracuje else ["disabled"])
        if self.pracuje:
            self._pasek.configure(mode="indeterminate")
            self._pasek.start(12)
        else:                                # zatrzymany pasek „w ruchu” zostawia kawałek wskaźnika
            self._pasek.stop()
            self._pasek.configure(mode="determinate", value=0)
        if self.pracuje:
            self._stan.configure(text=self.postep)
        elif self.blad is not None:
            tekst = self.blad.komunikat() if isinstance(self.blad, BladNornicy) else str(self.blad)
            self._stan.configure(text=tekst, style="Ostrzezenie.TLabel")
        elif self.wynik is not None:
            self._stan.configure(text=t("asystent.gotowe", ile=len(self.wynik.wartosci),
                                        zapytanie=self.wynik.zapytanie), style="Opis.TLabel")
        else:
            self._stan.configure(text=t("asystent.wstep"), style="Opis.TLabel")
        self._wypelnij_tabele()

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

    def _wypelnij_tabele(self) -> None:
        drzewo = self._drzewo
        biezacy = drzewo.focus()
        drzewo.delete(*drzewo.get_children())
        if self.wynik is None:
            return
        obecne = self.obecne()
        for w in self.wynik.wartosci:
            if w.blad:
                pewnosc, znak, znaczniki = t(w.blad), "—", ("bledna",)
            elif w.potwierdzona:
                pewnosc, znak, znaczniki = t("asystent.potwierdzona"), "", ()
            else:
                pewnosc, znak, znaczniki = t("asystent.niepotwierdzona"), "", ("niepotwierdzona",)
            if not w.blad:
                znak = "☑" if w.kod in self.zaznaczone else "☐"
            drzewo.insert("", "end", iid=w.kod, tags=znaczniki,
                          values=(znak, w.etykieta, obecne.get(w.kod, "") or "—", w.tekst, pewnosc))
        if biezacy and drzewo.exists(biezacy):
            drzewo.focus(biezacy)
            drzewo.selection_set(biezacy)
        self._pokaz_szczegoly()

    def _pokaz_szczegoly(self) -> None:
        w = self._wartosc(self._drzewo.focus() or (self._drzewo.selection() or ("",))[0])
        if w is None:
            self._szczegoly.configure(text=t("asystent.wybierz_wiersz") if self.wynik else "")
            self._adres.configure(text="")
        else:
            cytat = f"„{w.cytat}”" if w.cytat else t("asystent.bez_cytatu")
            self._szczegoly.configure(text=t("asystent.cytat", cytat=cytat))
            self._adres.configure(text=f"{w.zrodlo.tytul} — {w.zrodlo.adres}" if w.zrodlo else t("asystent.bez_zrodla"))
        self._uwagi.configure(text=t("asystent.uwagi", uwagi=self.wynik.uwagi) if self.wynik and self.wynik.uwagi else "")

    def _wartosc(self, kod: str):
        if self.wynik is None:
            return None
        return next((w for w in self.wynik.wartosci if w.kod == kod), None)

    def _otworz_zrodlo(self) -> None:
        w = self._wartosc(self._drzewo.focus())
        if w is not None and w.zrodlo is not None:
            webbrowser.open(w.zrodlo.adres)

    def _klik(self, zdarzenie) -> None:
        if self._drzewo.identify_column(zdarzenie.x) == "#1":
            self.przelacz(self._drzewo.identify_row(zdarzenie.y))

    def przelacz(self, kod: str) -> None:
        """Zaznacza albo odznacza wiersz do wstawienia (wartości z błędem — nigdy)."""
        w = self._wartosc(kod)
        if w is None or not w.mozna_wstawic:
            return
        self.zaznaczone.symmetric_difference_update({kod})
        self._drzewo.set(kod, "wstaw", "☑" if kod in self.zaznaczone else "☐")

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

    def wczytaj_modele(self) -> None:
        """Lista modeli z Ollamy w tle; brak Ollamy to komunikat, nie błąd okna."""
        u = self.ustawienia()

        def w_tle():
            try:
                self._kolejka.put(("modele", self._lista_modeli(u), None))
            except Exception as blad:   # noqa: BLE001
                self._kolejka.put(("modele", [], blad))
        self._uruchom_watek(w_tle, "asystent-modele")

    def uruchom(self) -> None:
        if self.pracuje:
            return
        if not self.model.get().strip():
            self.blad = BladNornicy("asystent.brak_modelu")
            self._odswiez()
            return
        self._zapisz_ustawienia()
        dane = {**self.dane, "oznaczenia": self.oznaczenia.zapamietaj()}
        tekst_zapytania = self.zapytanie.get().strip() or zapytanie(dane.get("producent", ""), dane.get("nazwa", ""),
                                                                     dane["oznaczenia"])
        self.pracuje, self.blad, self.wynik, self.zaznaczone = True, None, None, set()
        self.postep = t("asystent.krok_start")
        self._anuluj = threading.Event()
        anuluj, jezyk, u = self._anuluj, jezyk_biezacy(), self.ustawienia()

        def w_tle():
            try:
                asystent = self._fabryka(u)
                wynik = asystent.zaproponuj(self.szablon, dane, tekst_zapytania, anuluj,
                                            lambda klucz, **p: self._kolejka.put(("krok", klucz, p)), jezyk)
                self._kolejka.put(("wynik", wynik, None))
            except Przerwano:
                self._kolejka.put(("przerwano", None, None))
            except Exception as blad:   # noqa: BLE001 — wynik wraca do wątku interfejsu
                self._kolejka.put(("blad", None, blad))

        self._uruchom_watek(w_tle, "asystent")
        self._odswiez()

    def _uruchom_watek(self, cel, nazwa: str) -> None:
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
                self._odbierz(rodzaj, wartosc, dodatek)
                if rodzaj != "krok":
                    self._w_tle -= 1
                zmiana = True
        except queue.Empty:
            pass
        if self._w_tle > 0:
            self.after(100, self._czekaj)
        if zmiana:
            self._odswiez()

    def _odbierz(self, rodzaj: str, wartosc, dodatek) -> None:
        if rodzaj == "modele":
            self.modele, self.stan_ollamy = wartosc, (dodatek if isinstance(dodatek, BladNornicy) else
                                                      BladNornicy("asystent.blad_ollamy", opis=str(dodatek))
                                                      if dodatek else None)
            if self.modele and self.model.get() not in self.modele and MODEL_DOMYSLNY in self.modele:
                self.model.set(MODEL_DOMYSLNY)
        elif rodzaj == "krok":
            self.postep = t(wartosc, **dodatek)
        elif rodzaj == "wynik":
            self.pracuje, self.wynik = False, wartosc
            obecne = {k: (v or "").casefold() for k, v in self.obecne().items()}
            # domyślnie: potwierdzone i różne od tego, co już jest w formularzu
            self.zaznaczone = {w.kod for w in wartosc.wartosci if w.mozna_wstawic and w.potwierdzona
                               and w.tekst.casefold() != obecne.get(w.kod, "")}
        elif rodzaj == "przerwano":
            self.pracuje, self.blad = False, BladNornicy("asystent.przerwano")
        elif rodzaj == "blad":
            self.pracuje, self.blad = False, dodatek

    def czekaj_na_wynik(self, limit: float = 10.0) -> None:
        """Dla testów: obsługa kolejki aż praca się skończy."""
        import time
        koniec = time.monotonic() + limit
        while self._w_tle > 0 and time.monotonic() < koniec:
            self.update()
            time.sleep(0.02)
        self._czekaj()

    def zastosuj(self) -> None:
        if self.wynik is None or not self.zaznaczone:
            return
        self.po_zastosowaniu(self.wynik, set(self.zaznaczone), self.nadpisz.get())
        self.zamknij()

    def zamknij(self) -> None:
        self._anuluj.set()
        super().zamknij()

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.oznaczenia.zapamietaj()

