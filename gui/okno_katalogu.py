# SPDX-License-Identifier: GPL-3.0-or-later
"""Katalog modeli: przeglądanie, edycja i usuwanie modeli.

Model istnieje niezależnie od egzemplarzy (można go założyć „na zapas”
albo zostać z nim po usunięciu ostatniego egzemplarza), więc musi mieć
własne miejsce, w którym da się go poprawić.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from baza.polaczenie import klucz_sortowania
from baza.repozytoria import modele
from baza.zaleznosci import opis, zaleznosci
from gui.bazowe import OknoDialogowe, pokaz_blad
from i18n.tlumacz import nazwa, t
from uslugi import inwentarz

KOLUMNY = (("producent", "kolumna.producent", 150), ("nazwa", "kolumna.nazwa", 220),
           ("numer", "kolumna.numer_czesci", 110), ("kategoria", "kolumna.kategoria", 170),
           ("egzemplarze", "kolumna.egzemplarze", 90))


class OknoKataloguModeli(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.filtr = tk.StringVar()
        self.filtr.trace_add("write", lambda *_: self._wypelnij())
        self.zaznaczony: int | None = None      # id modelu — przeżywa przebudowę
        self._lista: ttk.Treeview | None = None
        self.geometry("820x480")    # tylko raz: przebudowa nie cofa rozmiaru zmienionego ręcznie

    def zbuduj_ui(self) -> None:
        self.title(t("okno.katalog_modeli"))
        ramka = ttk.Frame(self, padding=12)
        ramka.pack(fill="both", expand=True)

        gora = ttk.Frame(ramka)
        gora.pack(fill="x", pady=(0, 8))
        ttk.Button(gora, text=t("akcja.nowy_model"), command=self.nowy).pack(side="left")
        ttk.Button(gora, text=t("akcja.edytuj"), command=self.edytuj).pack(side="left", padx=(6, 0))
        ttk.Button(gora, text=t("akcja.usun"), command=self.usun).pack(side="left", padx=(6, 0))
        ttk.Entry(gora, textvariable=self.filtr, width=28).pack(side="right")
        ttk.Label(gora, text=t("pasek.szukaj")).pack(side="right", padx=(0, 6))

        srodek = ttk.Frame(ramka)
        srodek.pack(fill="both", expand=True)
        self._lista = ttk.Treeview(srodek, columns=[k for k, _, _ in KOLUMNY], show="headings",
                                   selectmode="browse")
        for kod, klucz, szerokosc in KOLUMNY:
            self._lista.heading(kod, text=t(klucz), anchor="w")
            self._lista.column(kod, width=szerokosc, stretch=kod == "nazwa")
        przewijak = ttk.Scrollbar(srodek, orient="vertical", command=self._lista.yview)
        self._lista.configure(yscrollcommand=przewijak.set)
        # pasek PRZED treścią: przy braku miejsca pack odbiera je ostatniemu widżetowi
        przewijak.pack(side="right", fill="y")
        self._lista.pack(side="left", fill="both", expand=True)
        self._lista.bind("<<TreeviewSelect>>", self._wybrano)
        self._lista.bind("<Double-1>", lambda _e: self.edytuj())
        self._lista.bind("<Delete>", lambda _e: self.usun())
        self._wypelnij()

    def _wypelnij(self) -> None:
        lista = self._lista
        if lista is None or not lista.winfo_exists():
            return
        fraza = self.filtr.get().strip().casefold()
        wiersze = []
        for m in modele.katalog(self.db):
            wartosci = (m["producent"] or "", m["nazwa"], m["numer_czesci"] or "",
                        nazwa(m["kategoria_nazwy"]), m["egzemplarze"])
            if fraza and not any(fraza in str(w).casefold() for w in wartosci[:4]):
                continue
            wiersze.append((m["id"], wartosci))
        wiersze.sort(key=lambda w: (klucz_sortowania(w[1][0]), klucz_sortowania(w[1][1])))
        lista.delete(*lista.get_children())
        for model_id, wartosci in wiersze:
            lista.insert("", "end", iid=str(model_id), values=wartosci)
        if self.zaznaczony is not None and lista.exists(str(self.zaznaczony)):
            lista.selection_set(str(self.zaznaczony))
            lista.see(str(self.zaznaczony))

    def dane_zmienione(self) -> None:
        super().dane_zmienione()
        self._wypelnij()

    def _wybrano(self, _e=None) -> None:
        zaznaczenie = self._lista.selection()
        self.zaznaczony = int(zaznaczenie[0]) if zaznaczenie else None

    def _po_zapisie(self, model_id: int) -> None:
        self.zaznaczony = model_id
        self.glowne.odswiez()          # odświeża też tę listę (dane_zmienione)

    def nowy(self) -> None:
        from gui.okno_modelu import OknoModelu
        OknoModelu(self.glowne, None, po_zapisie=self._po_zapisie).pokaz()

    def edytuj(self) -> None:
        from gui.okno_modelu import OknoModelu
        if self.zaznaczony is not None:
            OknoModelu(self.glowne, self.zaznaczony, po_zapisie=self._po_zapisie).pokaz()

    def usun(self) -> None:
        if self.zaznaczony is None:
            return
        m = modele.pobierz(self.db, self.zaznaczony)
        blokujace, kaskadowe = zaleznosci(self.db, "model", self.zaznaczony)
        if blokujace:
            messagebox.showwarning(t("okno.uwaga"), t("blad.usuwanie_zablokowane", lista=opis(blokujace)),
                                   parent=self)
            return
        pytanie = t("pytanie.usun_model", nazwa=modele.etykieta(m))
        if kaskadowe:
            pytanie += "\n\n" + t("pytanie.usun_tez", lista=opis(kaskadowe))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            inwentarz.usun_model(self.db, self.zaznaczony)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zaznaczony = None
        self._wypelnij()
        self.glowne.odswiez()
