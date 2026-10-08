# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Kopia zapasowa”: utworzenie kopii ZIP całej kolekcji i przywrócenie.

Migawka bazy powstaje w wątku interfejsu (połączenie SQLite należy do niego),
pakowanie plików idzie w tle z paskiem postępu, a wynik wraca przez kolejkę
sprawdzaną pętlą after(). Stan (komunikat, postęp) mieszka w atrybutach,
więc okno przeżywa zmianę języka także w trakcie pakowania.
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import konfiguracja
from baza.repozytoria import ustawienia
from gui.bazowe import OknoDialogowe, pokaz_blad
from i18n.tlumacz import t
from uslugi import archiwum
from uslugi.formatowanie import data_lokalna, pojemnosc_na_tekst


class OknoKopii(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.pracuje = False
        self.postep = 0.0
        self.komunikat: tuple[str, dict, bool] | None = None      # (klucz, pola, ostrzeżenie)
        self._wyniki: queue.Queue = queue.Queue()
        self._pasek = self._stan = self._info = None
        self._przyciski: dict[str, ttk.Button] = {}

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("okno.kopia"))
        ramka = ttk.Frame(self, padding=16)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("kopia.wstep"), wraplength=560, justify="left").pack(anchor="w")
        self._info = ttk.Frame(ramka, padding=(0, 12))
        self._info.pack(fill="x")

        ttk.Label(ramka, text=t("kopia.utworz_naglowek"), font=self.glowne.czcionki["pogrubiona"]).pack(anchor="w", pady=(4, 0))
        ttk.Label(ramka, text=t("kopia.utworz_opis"), style="Opis.TLabel", wraplength=560,
                  justify="left").pack(anchor="w")
        self._przyciski["utworz"] = ttk.Button(ramka, text=t("kopia.utworz"), style="Akcent.TButton",
                                               command=self.utworz)
        self._przyciski["utworz"].pack(anchor="w", pady=(6, 0))
        self._pasek = ttk.Progressbar(ramka, mode="determinate", maximum=100, length=560)
        self._pasek.pack(fill="x", pady=(8, 0))

        ttk.Separator(ramka).pack(fill="x", pady=14)
        ttk.Label(ramka, text=t("kopia.przywroc_naglowek"), font=self.glowne.czcionki["pogrubiona"]).pack(anchor="w")
        ttk.Label(ramka, text=t("kopia.przywroc_opis"), style="Opis.TLabel", wraplength=560,
                  justify="left").pack(anchor="w")
        self._przyciski["przywroc"] = ttk.Button(ramka, text=t("kopia.przywroc"), command=self.przywroc)
        self._przyciski["przywroc"].pack(anchor="w", pady=(6, 0))

        self._stan = ttk.Label(ramka, wraplength=560, justify="left")
        self._stan.pack(anchor="w", fill="x", pady=(14, 0))
        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(14, 0))
        self._przyciski["zamknij"] = ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij)
        self._przyciski["zamknij"].pack(side="right")
        self._odswiez()

    def _odswiez(self) -> None:
        if self._info is None or not self._info.winfo_exists():
            return
        for dziecko in self._info.winfo_children():
            dziecko.destroy()
        ostatnia = ustawienia.pobierz(self.db, "kopia_ostatnia")
        liczby = {n: self.db.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
                  for n, tab in (("egzemplarze", "egzemplarz"), ("lokalizacje", "lokalizacja"))}
        pliki = self.db.execute("SELECT COUNT(DISTINCT plik_sciezka), coalesce(SUM(plik_rozmiar), 0) "
                                "FROM zasob WHERE plik_sciezka IS NOT NULL").fetchone()
        for wiersz, (etykieta, wartosc) in enumerate((
                (t("kopia.ostatnia"), data_lokalna(ostatnia) if ostatnia else t("kopia.nigdy")),
                (t("kopia.zawartosc"), t("kopia.liczby", egzemplarze=liczby["egzemplarze"],
                                         lokalizacje=liczby["lokalizacje"], pliki=pliki[0],
                                         rozmiar=pojemnosc_na_tekst(pliki[1]))))):
            ttk.Label(self._info, text=etykieta, style="Pole.TLabel").grid(row=wiersz, column=0, sticky="w",
                                                                           padx=(0, 12))
            ttk.Label(self._info, text=wartosc).grid(row=wiersz, column=1, sticky="w")
        self._pasek.configure(value=self.postep)
        if self.komunikat:
            klucz, pola, ostrzezenie = self.komunikat
            self._stan.configure(text=t(klucz, **pola), style="Ostrzezenie.TLabel" if ostrzezenie else "TLabel")
        else:
            self._stan.configure(text="")
        for kod, przycisk in self._przyciski.items():
            przycisk.configure(state="disabled" if self.pracuje else "normal")

    def dane_zmienione(self) -> None:
        self._odswiez()

    def zamknij(self) -> None:
        if self.pracuje:                  # pakowanie w toku — plik musi zostać dokończony
            return
        super().zamknij()

    # ------------------------------------------------------------------ tworzenie
    def utworz(self, cel: str | None = None) -> None:
        if self.pracuje:
            return
        if cel is None:
            folder = ustawienia.pobierz(self.db, "kopia_folder")
            cel = filedialog.asksaveasfilename(
                parent=self, title=t("kopia.utworz"), defaultextension=".zip",
                initialdir=folder if folder and Path(folder).is_dir() else str(Path.home()),
                initialfile=archiwum.domyslna_nazwa(), filetypes=[("ZIP", "*.zip")])
            if not cel:
                return
        try:
            migawka = archiwum.migawka(self.db)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.pracuje, self.postep, self.komunikat = True, 0.0, ("kopia.pakowanie", {}, False)
        self._odswiez()

        def postep(zrobione: int, razem: int) -> None:
            self._wyniki.put(("postep", zrobione * 100.0 / max(razem, 1)))

        def w_tle():
            try:
                self._wyniki.put(("ok", archiwum.zapisz(migawka, cel, postep)))
            except Exception as blad:   # noqa: BLE001 — wynik wraca do wątku interfejsu
                self._wyniki.put(("blad", blad))

        threading.Thread(target=w_tle, name="kopia", daemon=True).start()
        self.after(100, lambda: self._czekaj(cel))

    def _czekaj(self, cel: str) -> None:
        koniec = None
        try:
            while True:
                rodzaj, wartosc = self._wyniki.get_nowait()
                if rodzaj == "postep":
                    self.postep = wartosc
                else:
                    koniec = (rodzaj, wartosc)
        except queue.Empty:
            pass
        if koniec is None:
            if self.winfo_exists():
                self._pasek.configure(value=self.postep)
                self.after(100, lambda: self._czekaj(cel))
            return
        self.pracuje = False
        rodzaj, wartosc = koniec
        if rodzaj == "blad":
            self.postep, self.komunikat = 0.0, None
            self._odswiez()
            pokaz_blad(self, wartosc)
            return
        archiwum.zapamietaj(self.db, cel, wartosc)
        self.postep = 100.0
        pola = {"plik": cel, "rozmiar": pojemnosc_na_tekst(Path(cel).stat().st_size)}
        if wartosc["brakujace_pliki"]:
            self.komunikat = ("kopia.gotowa_brakujace", {**pola, "brakujace": len(wartosc["brakujace_pliki"])}, True)
        elif self._ten_sam_dysk(cel):
            self.komunikat = ("kopia.gotowa_ten_sam_dysk", pola, True)
        else:
            self.komunikat = ("kopia.gotowa", pola, False)
        self._odswiez()

    @staticmethod
    def _ten_sam_dysk(cel: str) -> bool:
        """Kopia na tym samym dysku co dane nie przetrwa awarii dysku."""
        try:
            return Path(cel).resolve().stat().st_dev == konfiguracja.katalog_danych().resolve().stat().st_dev
        except OSError:
            return False

    # ------------------------------------------------------------------ przywracanie
    def przywroc(self, sciezka: str | None = None) -> None:
        if self.pracuje:
            return
        if sciezka is None:
            folder = ustawienia.pobierz(self.db, "kopia_folder")
            sciezka = filedialog.askopenfilename(
                parent=self, title=t("kopia.przywroc"),
                initialdir=folder if folder and Path(folder).is_dir() else str(Path.home()),
                filetypes=[("ZIP", "*.zip"), (t("plik.wszystkie"), "*")])
            if not sciezka:
                return
        try:
            manifest = archiwum.odczytaj_manifest(sciezka)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        liczby = manifest.get("liczby", {})
        pytanie = t("kopia.pytanie_przywroc", data=data_lokalna(manifest.get("utworzono")),
                    wersja=manifest.get("wersja_programu", "?"), egzemplarze=liczby.get("egzemplarze", "?"),
                    lokalizacje=liczby.get("lokalizacje", "?"), pliki=liczby.get("pliki", "?"))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, icon="warning", parent=self):
            return
        self.pracuje = True
        self._odswiez()
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            wynik = archiwum.przywroc(self.db, sciezka, konfiguracja.katalog_kopii())
        except Exception as blad:   # noqa: BLE001
            self.pracuje = False
            self.configure(cursor="")
            self._odswiez()
            pokaz_blad(self, blad)
            return
        self.pracuje = False
        self.configure(cursor="")
        self.komunikat = ("kopia.przywrocono", {"pliki": wynik["dodane_pliki"],
                                                "kopia": str(wynik["kopia_bezpieczenstwa"])}, False)
        self.glowne.odswiez()             # drzewo, karta i otwarte okna; to okno przez dane_zmienione
