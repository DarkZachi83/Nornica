# SPDX-License-Identifier: GPL-3.0-or-later
"""Skaner w oknie głównym: pole „Skanuj”, czytnik USB i most do telefonu.

Klasa pomocnicza okna głównego (gui/okno_glowne.py): korzysta z jego
atrybutów — db, stan, _dialogi, _widzety, odswiez() — i nie działa samodzielnie.
"""
from __future__ import annotations

import tkinter as tk

from gui.model_drzewa import iid_egzemplarza, iid_lokalizacji
from i18n.tlumacz import t


class SkanerGlowny:
    """Obsługa skanu z każdego źródła i zapytań serwera telefonu (w wątku interfejsu)."""

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
        if rodzaj == "inwentaryzacja":
            from uslugi import inwentaryzacja
            try:
                return inwentaryzacja.obsluga_telefonu(self.db, dane)
            finally:
                self.powiadom_okna()       # otwarte okno inwentaryzacji pokazuje skany na żywo
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
        """Skaner w telefonie (jedno okno)."""
        from gui.okno_telefonu import OknoTelefonu
        return self.jedno_okno(OknoTelefonu)
        okno = OknoTelefonu(self)
        okno.pokaz()
        return okno
