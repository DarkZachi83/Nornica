# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Porządki w kolekcji”: lista kontroli z liczbą znalezisk po lewej,
pozycje wybranej kontroli po prawej.

Okno trzyma SUROWE wyniki z uslugi/porzadki.py (bez tekstów) i formatuje je
przy wyświetleniu — zmiana języka przebudowuje okno bez ponownego szukania.
Wyniki liczone są od nowa po każdej zmianie danych (dane_zmienione), także
po usunięciu pozycji w tym oknie.
"""
from __future__ import annotations

from datetime import datetime, timezone
from tkinter import messagebox, ttk

from baza import enumy
from baza.repozytoria.egzemplarze import nazwa_wyswietlana
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import iid_egzemplarza, iid_lokalizacji
from i18n.tlumacz import nazwa, t
from uslugi import porzadki
from uslugi.formatowanie import data_lokalna, pojemnosc_na_tekst

# kolumny każdej kontroli: (kod kolumny, klucz nagłówka, szerokość)
KOLUMNY: dict[str, tuple[tuple[str, str, int], ...]] = {
    "zasoby_sieroty": (("tytul", "kolumna.tytul", 260), ("typ", "kolumna.typ", 150),
                       ("rozmiar", "kolumna.rozmiar", 90), ("data", "kolumna.data", 140)),
    "pliki_bez_wpisu": (("plik", "kolumna.plik", 360), ("rozmiar", "kolumna.rozmiar", 90),
                        ("data", "kolumna.zmieniono", 140)),
    "brakujace_pliki": (("tytul", "kolumna.tytul", 220), ("typ", "kolumna.typ", 130),
                        ("plik", "kolumna.plik", 220), ("egzemplarz", "kolumna.egzemplarz", 110)),
    "puste_lokalizacje": (("kod", "kolumna.kod", 100), ("nazwa", "kolumna.nazwa", 380),
                          ("typ", "kolumna.typ", 120)),
    "nieuzywane_modele": (("producent", "kolumna.producent", 150), ("nazwa", "kolumna.nazwa", 200),
                          ("numer", "kolumna.numer_czesci", 110), ("kategoria", "kolumna.kategoria", 180)),
    "nieuzywani_producenci": (("nazwa", "kolumna.producent", 400),),
    "bez_lokalizacji": (("kod", "kolumna.kod", 110), ("nazwa", "kolumna.nazwa", 340),
                        ("status", "kolumna.status", 140)),
    "powtorzone_numery": (("numer", "kolumna.numer_seryjny", 150), ("kod", "kolumna.kod", 110),
                          ("nazwa", "kolumna.nazwa", 340)),
}


def _czas_pliku(sekundy: float) -> str:
    return data_lokalna(datetime.fromtimestamp(sekundy, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))


def wartosci(kod: str, p) -> tuple[str, ...]:
    """Teksty kolumn jednej pozycji — w bieżącym języku."""
    if kod == "zasoby_sieroty":
        return (p["tytul"], enumy.etykieta("zasob.typ", p["typ"]),
                pojemnosc_na_tekst(p["plik_rozmiar"]) if p["plik_rozmiar"] is not None else "—",
                data_lokalna(p["dodano"]))
    if kod == "pliki_bez_wpisu":
        plik = p["sciezka"] + ("  " + t("porzadki.tymczasowy") if p["tymczasowy"] else "")
        return plik, pojemnosc_na_tekst(p["rozmiar"]), _czas_pliku(p["zmieniono"])
    if kod == "brakujace_pliki":
        return (p["tytul"], enumy.etykieta("zasob.typ", p["typ"]), p["plik_sciezka"],
                p.get("kod_egzemplarza") or "—")
    if kod == "puste_lokalizacje":
        return (p["kod_etykiety"] or "—", p["sciezka"] or p["nazwa"],
                enumy.etykieta("lokalizacja.typ", p["typ"]) if p["typ"] else "—")
    if kod == "nieuzywane_modele":
        return p["producent"] or "—", p["nazwa"], p["numer_czesci"] or "—", nazwa(p["kategoria_nazwy"])
    if kod == "nieuzywani_producenci":
        return (p["nazwa"],)
    if kod == "bez_lokalizacji":
        return p["kod_inwentarzowy"] or "—", nazwa_wyswietlana(p), nazwa(p["status_nazwy"])
    if kod == "powtorzone_numery":
        return p["numer_seryjny"].strip(), p["kod_inwentarzowy"] or "—", nazwa_wyswietlana(p)
    raise KeyError(kod)


class OknoPorzadkow(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.kod = porzadki.KONTROLE[0].kod
        self.wyniki: dict[str, list] = {}
        self.komunikat: tuple[str, dict] | None = None
        self._kontrole = self._pozycje = self._opis = self._stan = None
        self._przyciski: dict[str, ttk.Button] = {}
        self._policz()

    # ------------------------------------------------------------------ dane
    def _policz(self) -> None:
        self.wyniki = porzadki.przeglad(self.db)
        kody = {}
        for p in self.wyniki.get("brakujace_pliki", []):
            if p["egzemplarz_id"] is not None and p["egzemplarz_id"] not in kody:
                wiersz = self.db.execute("SELECT kod_inwentarzowy FROM egzemplarz WHERE id = ?",
                                         (p["egzemplarz_id"],)).fetchone()
                kody[p["egzemplarz_id"]] = wiersz[0] if wiersz else None
            p["kod_egzemplarza"] = kody.get(p["egzemplarz_id"])

    def dane_zmienione(self) -> None:
        self._policz()
        self._pokaz_kontrole()

    # ------------------------------------------------------------------ widok
    def pokaz(self) -> None:
        """Stały rozmiar okna: opisy kontroli mają różną długość, a okno
        dopasowujące się do treści skakałoby przy każdym wyborze z listy."""
        super().pokaz()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight() + 40}")

    def zbuduj_ui(self) -> None:
        self.title(t("okno.porzadki"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("porzadki.wstep"), style="Opis.TLabel", wraplength=880,
                  justify="left").pack(anchor="w", pady=(0, 10))

        dol = ttk.Frame(ramka)
        dol.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        self._stan = ttk.Label(dol, style="Opis.TLabel")
        self._stan.pack(side="left")

        srodek = ttk.Frame(ramka)
        srodek.pack(fill="both", expand=True)
        self._kontrole = ttk.Treeview(srodek, show="tree", selectmode="browse", height=14)
        self._kontrole.column("#0", width=290)
        self._kontrole.pack(side="left", fill="y")
        self._kontrole.bind("<<TreeviewSelect>>", self._wybrano_kontrole)
        self._kontrole.tag_configure("grupa", font=self.glowne.czcionki["pogrubiona"])
        self._kontrole.tag_configure("pusta", foreground="#8A857A")

        prawa = ttk.Frame(srodek, padding=(14, 0, 0, 0))
        prawa.pack(side="left", fill="both", expand=True)
        self._opis = ttk.Label(prawa, wraplength=560, justify="left")
        self._opis.pack(anchor="w", fill="x")
        lista = ttk.Frame(prawa)
        lista.pack(fill="both", expand=True, pady=(8, 0))
        self._pozycje = ttk.Treeview(lista, show="headings", selectmode="extended", height=14)
        przewijak = ttk.Scrollbar(lista, orient="vertical", command=self._pozycje.yview)
        self._pozycje.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")
        self._pozycje.pack(side="left", fill="both", expand=True)
        self._pozycje.bind("<<TreeviewSelect>>", lambda _e: self._stan_przyciskow())
        self._pozycje.bind("<Double-1>", lambda _e: self.pokaz_pozycje())
        self._pozycje.bind("<Delete>", lambda _e: self.usun_zaznaczone())

        przyciski = ttk.Frame(prawa)
        przyciski.pack(fill="x", pady=(8, 0))
        for kod, klucz, polecenie in (("wszystko", "porzadki.zaznacz_wszystko", self.zaznacz_wszystko),
                                      ("pokaz", "porzadki.pokaz", self.pokaz_pozycje),
                                      ("usun", "porzadki.usun_zaznaczone", self.usun_zaznaczone),
                                      ("odswiez", "akcja.odswiez", self.odswiez)):
            self._przyciski[kod] = ttk.Button(przyciski, text=t(klucz), command=polecenie)
            self._przyciski[kod].pack(side="right" if kod == "odswiez" else "left", padx=(0, 6))
        self._pokaz_kontrole()

    def _pokaz_kontrole(self) -> None:
        drzewo = self._kontrole
        if drzewo is None or not drzewo.winfo_exists():
            return
        drzewo.delete(*drzewo.get_children())
        for grupa, usuwanie in (("do_usuniecia", True), ("do_sprawdzenia", False)):
            drzewo.insert("", "end", iid=grupa, text=t(f"porzadki.grupa.{grupa}"), open=True, tags=("grupa",))
            for k in porzadki.KONTROLE:
                if k.usuwanie == usuwanie:
                    liczba = len(self.wyniki.get(k.kod, []))
                    drzewo.insert(grupa, "end", iid=k.kod, text=f"{t(f'porzadki.{k.kod}')} ({liczba})",
                                  tags=() if liczba else ("pusta",))
        drzewo.selection_set(self.kod)
        drzewo.focus(self.kod)
        self._pokaz_pozycje()
        if self.komunikat:
            klucz, pola = self.komunikat
            self._stan.configure(text=t(klucz, **pola))

    def _wybrano_kontrole(self, _zdarzenie=None) -> None:
        wybor = self._kontrole.selection()
        if not wybor:
            return
        if wybor[0] not in porzadki.PO_KODZIE:          # kliknięto nagłówek grupy
            self._kontrole.selection_set(self.kod)
            return
        if wybor[0] != self.kod:
            self.kod = wybor[0]
            self._pokaz_pozycje()

    def _pokaz_pozycje(self) -> None:
        lista = self._pozycje
        kolumny = KOLUMNY[self.kod]
        lista.delete(*lista.get_children())
        lista.configure(columns=[k for k, _, _ in kolumny])
        for k, klucz, szerokosc in kolumny:
            lista.heading(k, text=t(klucz))
            lista.column(k, width=szerokosc, stretch=True)
        for p in self.wyniki.get(self.kod, []):
            lista.insert("", "end", iid=str(porzadki.klucz_pozycji(self.kod, p)), values=wartosci(self.kod, p))
        pozycje = self.wyniki.get(self.kod, [])
        self._opis.configure(text=t(f"porzadki.opis.{self.kod}") + "\n\n"
                             + (t("porzadki.znaleziono", liczba=len(pozycje)) if pozycje
                                else t("porzadki.brak")))
        self._stan_przyciskow()

    def _stan_przyciskow(self) -> None:
        kontrola = porzadki.PO_KODZIE[self.kod]
        zaznaczone = bool(self._pozycje.selection())
        stany = {"wszystko": bool(self.wyniki.get(self.kod)),
                 "pokaz": kontrola.przejscie and len(self._pozycje.selection()) == 1,
                 "usun": kontrola.usuwanie and zaznaczone,
                 "odswiez": True}
        usun = self._przyciski["usun"]
        if not kontrola.usuwanie:                     # kontrole „do sprawdzenia” niczego nie usuwają
            usun.pack_forget()
        elif not usun.winfo_manager():
            usun.pack(side="left", padx=(0, 6), after=self._przyciski["pokaz"])
        for kod, przycisk in self._przyciski.items():
            przycisk.configure(state="normal" if stany[kod] else "disabled")

    # ------------------------------------------------------------------ akcje
    def odswiez(self) -> None:
        self.komunikat = None
        self._policz()
        self._pokaz_kontrole()

    def zaznacz_wszystko(self) -> None:
        self._pozycje.selection_set(self._pozycje.get_children())

    def _zaznaczone_klucze(self) -> list:
        klucze = []
        indeks = {str(porzadki.klucz_pozycji(self.kod, p)): porzadki.klucz_pozycji(self.kod, p)
                  for p in self.wyniki.get(self.kod, [])}
        for iid in self._pozycje.selection():
            if iid in indeks:
                klucze.append(indeks[iid])
        return klucze

    def pokaz_pozycje(self) -> None:
        """Zaznacza pozycję w drzewie okna głównego."""
        if not porzadki.PO_KODZIE[self.kod].przejscie:
            return
        klucze = self._zaznaczone_klucze()
        if len(klucze) != 1:
            return
        if self.kod == "puste_lokalizacje":
            iid = iid_lokalizacji(klucze[0])
        elif self.kod == "brakujace_pliki":
            pozycja = next(p for p in self.wyniki[self.kod] if p["id"] == klucze[0])
            if pozycja["egzemplarz_id"] is None:
                return
            iid = iid_egzemplarza(pozycja["egzemplarz_id"])
        else:
            iid = iid_egzemplarza(klucze[0])
        self.glowne.filtr_var.set("")
        self.glowne.odswiez(zaznacz=iid)
        self.glowne.lift()

    def usun_zaznaczone(self) -> None:
        if not porzadki.PO_KODZIE[self.kod].usuwanie:
            return
        klucze = self._zaznaczone_klucze()
        if not klucze:
            return
        pytanie = t("porzadki.pytanie_usun", kontrola=t(f"porzadki.{self.kod}"), liczba=len(klucze))
        if self.kod in ("zasoby_sieroty", "pliki_bez_wpisu"):
            pytanie += "\n\n" + t("porzadki.pytanie_pliki")
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            usuniete = porzadki.usun(self.db, self.kod, klucze)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        pominiete = len(klucze) - usuniete
        self.komunikat = (("porzadki.usunieto_pominieto", {"liczba": usuniete, "pominiete": pominiete})
                          if pominiete else ("porzadki.usunieto", {"liczba": usuniete}))
        self.glowne.odswiez()          # drzewo i inne okna; to okno przeliczy się w dane_zmienione
