# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Słowniki”: własne kategorie, pola parametrów i statusy.

Wpisy wbudowane są widoczne, ale tylko do odczytu (opis w usłudze
uslugi/slowniki_edycja.py). Stan okna — wybrana kategoria, pole, status,
zakładka — mieszka w atrybutach, więc przeżywa przebudowę po zmianie języka.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from baza.enumy import opcje
from baza.repozytoria import slowniki
from baza.repozytoria.slowniki import klucz_kolejnosci
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.pola import PoleTekstu, PoleWyboru
from i18n.tlumacz import jezyk_biezacy, nazwa, t
from uslugi import slowniki_edycja as edycja


def opcje_typow() -> list[tuple[str, str]]:
    return [(typ, t(f"typ_pola.{typ}")) for typ in edycja.TYPY_POL]


def _opis_pola(pole: dict) -> str:
    if pole["typ"] == "enum":
        return ", ".join(pole.get("wartosci", []))
    return pole.get("jednostka", "")


class OknoSlownikow(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.kat_id: int | None = None
        self.pole_kod: str | None = None
        self.status_id: int | None = None
        self._drzewo = self._pola = self._statusy = None
        self._przyciski: dict[str, ttk.Button] = {}

    # ------------------------------------------------------------------ widok
    def zbuduj_ui(self) -> None:
        self.title(t("okno.slowniki"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("slowniki.wstep"), style="Opis.TLabel", wraplength=760,
                  justify="left").pack(anchor="w", pady=(0, 8))
        self._notatnik = ttk.Notebook(ramka)
        self._notatnik.pack(fill="both", expand=True)

        # --- kategorie i pola
        karta = ttk.Frame(self._notatnik, padding=10)
        self._notatnik.add(karta, text=t("slowniki.kategorie"))
        lewa = ttk.Frame(karta)
        lewa.pack(side="left", fill="y")
        self._drzewo = ttk.Treeview(lewa, show="tree", selectmode="browse", height=18)
        self._drzewo.column("#0", width=260)
        przewijak = ttk.Scrollbar(lewa, orient="vertical", command=self._drzewo.yview)
        self._drzewo.configure(yscrollcommand=przewijak.set)
        przyciski = ttk.Frame(lewa)
        przyciski.pack(side="bottom", fill="x", pady=(6, 0))
        przewijak.pack(side="right", fill="y")
        self._drzewo.pack(side="left", fill="both", expand=True)
        self._drzewo.bind("<<TreeviewSelect>>", self._wybrano_kategorie)
        self._drzewo.bind("<Double-1>", lambda _e: self.edytuj_kategorie())
        for kod, klucz, polecenie in (("kat_nowa", "slowniki.nowa_kategoria", lambda: self.nowa_kategoria(None)),
                                      ("kat_pod", "slowniki.nowa_podkategoria",
                                       lambda: self.nowa_kategoria(self.kat_id)),
                                      ("kat_edytuj", "akcja.edytuj", self.edytuj_kategorie),
                                      ("kat_usun", "akcja.usun", self.usun_kategorie)):
            self._przyciski[kod] = ttk.Button(przyciski, text=t(klucz), command=polecenie)
            numer = len(self._przyciski) - 1
            self._przyciski[kod].grid(row=numer // 2, column=numer % 2, sticky="we", padx=(0, 4), pady=(0, 4))
        przyciski.columnconfigure((0, 1), weight=1)

        prawa = ttk.Frame(karta, padding=(12, 0, 0, 0))
        prawa.pack(side="left", fill="both", expand=True)
        self._tytul_pol = ttk.Label(prawa, style="Pole.TLabel")
        self._tytul_pol.pack(anchor="w")
        self._pola = ttk.Treeview(prawa, columns=("typ", "opis", "zrodlo"), show="tree headings",
                                  selectmode="browse", height=14)
        self._pola.heading("#0", text=t("slowniki.pole"))
        for kolumna, klucz, szer in (("typ", "slowniki.typ", 150), ("opis", "slowniki.jednostka_lista", 200),
                                     ("zrodlo", "slowniki.zrodlo", 130)):
            self._pola.heading(kolumna, text=t(klucz))
            self._pola.column(kolumna, width=szer, stretch=kolumna == "opis")
        self._pola.column("#0", width=170)
        self._pola.pack(fill="both", expand=True, pady=(4, 0))
        self._pola.bind("<<TreeviewSelect>>", self._wybrano_pole)
        self._pola.bind("<Double-1>", lambda _e: self.edytuj_pole())
        self._pola.tag_configure("cudze", foreground="#8A857A")
        przyciski_pol = ttk.Frame(prawa)
        przyciski_pol.pack(fill="x", pady=(6, 0))
        for kod, tekst, polecenie in (("pole_nowe", t("slowniki.dodaj_pole"), self.dodaj_pole),
                                      ("pole_edytuj", t("akcja.edytuj"), self.edytuj_pole),
                                      ("pole_usun", t("akcja.usun"), self.usun_pole),
                                      ("pole_wartosci", t("slowniki.wartosci_listy"), self.wartosci_pola),
                                      ("pole_gora", "↑", lambda: self.przesun_pole(-1)),
                                      ("pole_dol", "↓", lambda: self.przesun_pole(1))):
            self._przyciski[kod] = ttk.Button(przyciski_pol, text=tekst, command=polecenie,
                                              width=3 if len(tekst) == 1 else None)
            self._przyciski[kod].pack(side="left", padx=(0, 4))
        self._podpowiedz = ttk.Label(prawa, style="Opis.TLabel", wraplength=640, justify="left")
        self._podpowiedz.pack(anchor="w", pady=(6, 0))

        # --- statusy
        karta = ttk.Frame(self._notatnik, padding=10)
        self._notatnik.add(karta, text=t("slowniki.statusy"))
        self._statusy = ttk.Treeview(karta, columns=("zrodlo",), show="tree headings", selectmode="browse", height=12)
        self._statusy.heading("#0", text=t("pole.status"))
        self._statusy.heading("zrodlo", text=t("slowniki.zrodlo"))
        self._statusy.column("zrodlo", width=140, stretch=False)
        self._statusy.pack(fill="both", expand=True)
        self._statusy.bind("<<TreeviewSelect>>", self._wybrano_status)
        self._statusy.bind("<Double-1>", lambda _e: self.edytuj_status())
        przyciski_st = ttk.Frame(karta)
        przyciski_st.pack(fill="x", pady=(6, 0))
        for kod, klucz, polecenie in (("st_nowy", "slowniki.nowy_status", lambda: self.status(None)),
                                      ("st_edytuj", "akcja.edytuj", self.edytuj_status),
                                      ("st_usun", "akcja.usun", self.usun_status)):
            self._przyciski[kod] = ttk.Button(przyciski_st, text=t(klucz), command=polecenie)
            self._przyciski[kod].pack(side="left", padx=(0, 4))

        dol = ttk.Frame(ramka)
        dol.pack(fill="x", pady=(10, 0))
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")
        self._wypelnij()

    def dane_zmienione(self) -> None:
        super().dane_zmienione()
        self._wypelnij()

    def _zywy(self, widzet) -> bool:
        return widzet is not None and widzet.winfo_exists()

    def _wypelnij(self) -> None:
        if not self._zywy(self._drzewo):
            return
        # drzewo kategorii
        self._drzewo.delete(*self._drzewo.get_children())
        wiersze = slowniki.kategorie(self.db)
        dzieci: dict = {}
        for w in wiersze:
            dzieci.setdefault(w["rodzic_id"], []).append(w)

        def dodaj(rodzic_iid, rodzic_id):
            for w in sorted(dzieci.get(rodzic_id, []), key=klucz_kolejnosci):
                tekst = nazwa(w["nazwy"]) + ("" if w["kod"] else f"  ({t('slowniki.wlasna_kategoria')})")
                self._drzewo.insert(rodzic_iid, "end", iid=str(w["id"]), text=tekst, open=True)
                dodaj(str(w["id"]), w["id"])
        dodaj("", None)
        if self.kat_id is not None and self._drzewo.exists(str(self.kat_id)):
            self._drzewo.selection_set(str(self.kat_id))
            self._drzewo.see(str(self.kat_id))
        else:
            self.kat_id = None
        self._wypelnij_pola()
        # statusy
        self._statusy.delete(*self._statusy.get_children())
        for w in slowniki.statusy(self.db):
            self._statusy.insert("", "end", iid=str(w["id"]), text=nazwa(w["nazwy"]),
                                 values=(t("slowniki.wbudowany") if w["kod"] else t("slowniki.wlasne"),))
        if self.status_id is not None and self._statusy.exists(str(self.status_id)):
            self._statusy.selection_set(str(self.status_id))
        else:
            self.status_id = None
        self._stany()

    def _wypelnij_pola(self) -> None:
        self._pola.delete(*self._pola.get_children())
        if self.kat_id is None:
            self._tytul_pol.configure(text=t("slowniki.wybierz_kategorie"))
            return
        kat = slowniki.kategoria(self.db, self.kat_id)
        self._tytul_pol.configure(text=t("slowniki.pola_kategorii", kategoria=nazwa(kat["nazwy"])))
        wlasne = {p["kod"]: p for p in json.loads(kat["szablon_atrybutow"] or "[]")}
        typy = dict(opcje_typow())
        for pole in slowniki.szablon(self.db, self.kat_id):
            if pole["kod"] in wlasne:
                zrodlo, tagi = (t("slowniki.wlasne") if pole.get("wlasne") else t("slowniki.wbudowany")), ()
            else:                                  # odziedziczone po kategorii nadrzędnej
                skad = next(k for k in slowniki.lancuch_kategorii(self.db, self.kat_id)
                            if any(p["kod"] == pole["kod"] for p in json.loads(
                                slowniki.kategoria(self.db, k)["szablon_atrybutow"] or "[]")))
                zrodlo, tagi = t("slowniki.z_kategorii", kategoria=nazwa(slowniki.kategoria(self.db, skad)["nazwy"])), ("cudze",)
            self._pola.insert("", "end", iid=pole["kod"], text=nazwa(pole["nazwy"]),
                              values=(typy.get(pole["typ"], pole["typ"]), _opis_pola(pole), zrodlo), tags=tagi)
        if self.pole_kod is not None and self._pola.exists(self.pole_kod):
            self._pola.selection_set(self.pole_kod)
        else:
            self.pole_kod = None

    # --------------------------------------------------------------- wybory
    def _kategoria(self):
        return slowniki.kategoria(self.db, self.kat_id) if self.kat_id is not None else None

    def _pole_wlasne(self) -> bool:
        kat = self._kategoria()
        if kat is None or self.pole_kod is None:
            return False
        return any(p["kod"] == self.pole_kod and p.get("wlasne")
                   for p in json.loads(kat["szablon_atrybutow"] or "[]"))

    def _pole_listy(self) -> bool:
        """Dowolne pole typu „wybór z listy” widoczne w tej kategorii (wbudowane, własne,
        odziedziczone) — jego wartości można zmieniać. Pojemność to nie lista."""
        if self.kat_id is None or self.pole_kod is None:
            return False
        return any(p["kod"] == self.pole_kod and p["typ"] == "enum" for p in slowniki.szablon(self.db, self.kat_id))

    def _wybrano_kategorie(self, _e=None) -> None:
        wybor = self._drzewo.selection()
        nowa = int(wybor[0]) if wybor else None
        if nowa != self.kat_id:
            self.kat_id, self.pole_kod = nowa, None
            self._wypelnij_pola()
        self._stany()

    def _wybrano_pole(self, _e=None) -> None:
        wybor = self._pola.selection()
        self.pole_kod = wybor[0] if wybor else None
        self._stany()

    def _wybrano_status(self, _e=None) -> None:
        wybor = self._statusy.selection()
        self.status_id = int(wybor[0]) if wybor else None
        self._stany()

    def _stany(self) -> None:
        """Przyciski aktywne tylko tam, gdzie zmiana jest możliwa; podpowiedź mówi dlaczego nie."""
        kat = self._kategoria()
        kat_wlasna = kat is not None and kat["kod"] is None
        status = (self.db.execute("SELECT kod FROM status WHERE id = ?", (self.status_id,)).fetchone()
                  if self.status_id is not None else None)
        pole_wlasne = self._pole_wlasne()
        stany = {"kat_pod": kat is not None, "kat_edytuj": kat_wlasna, "kat_usun": kat_wlasna,
                 "pole_nowe": kat is not None, "pole_edytuj": pole_wlasne, "pole_usun": pole_wlasne,
                 "pole_gora": pole_wlasne, "pole_dol": pole_wlasne,
                 "pole_wartosci": self._pole_listy(),
                 "st_edytuj": status is not None and status["kod"] is None,
                 "st_usun": status is not None and status["kod"] is None}
        for kod, przycisk in self._przyciski.items():
            if przycisk.winfo_exists():
                przycisk.configure(state="normal" if stany.get(kod, True) else "disabled")
        if self._zywy(self._podpowiedz):
            if self._pole_listy() and not pole_wlasne:
                tekst = t("slowniki.lista_wbudowana")
            elif self.pole_kod is not None and not pole_wlasne:
                tekst = t("slowniki.pole_tylko_odczyt")
            elif kat is not None and not kat_wlasna:
                tekst = t("slowniki.kategoria_wbudowana")
            else:
                tekst = ""
            self._podpowiedz.configure(text=tekst)

    # --------------------------------------------------------------- akcje
    def _po_zmianie(self) -> None:
        self.glowne.odswiez()          # formularze i drzewo zobaczą zmiany; to okno odświeży dane_zmienione

    def nowa_kategoria(self, rodzic_id: int | None) -> "OknoKategorii":
        okno = OknoKategorii(self.glowne, None, rodzic_id, po_zapisie=self._kategoria_zapisana)
        okno.pokaz()
        return okno

    def edytuj_kategorie(self):
        kat = self._kategoria()
        if kat is None or kat["kod"] is not None:
            return None
        okno = OknoKategorii(self.glowne, self.kat_id, kat["rodzic_id"], po_zapisie=self._kategoria_zapisana)
        okno.pokaz()
        return okno

    def _kategoria_zapisana(self, kat_id: int) -> None:
        self.kat_id, self.pole_kod = kat_id, None
        self._po_zmianie()

    def usun_kategorie(self) -> None:
        kat = self._kategoria()
        if kat is None or kat["kod"] is not None:
            return
        blokujace, kaskadowe = edycja.zaleznosci_kategorii(self.db, self.kat_id)
        if blokujace:
            from baza.zaleznosci import opis
            messagebox.showwarning(t("okno.uwaga"), t("blad.usuwanie_zablokowane", lista=opis(blokujace)),
                                   parent=self)
            return
        pytanie = t("pytanie.usun_kategorie", nazwa=nazwa(kat["nazwy"]))
        if kaskadowe:
            from baza.zaleznosci import opis
            pytanie += "\n\n" + t("pytanie.razem_z", lista=opis(kaskadowe))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            edycja.usun_kategorie(self.db, self.kat_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.kat_id = kat["rodzic_id"]
        self._po_zmianie()

    def dodaj_pole(self):
        if self.kat_id is None:
            return None
        okno = OknoPola(self.glowne, self.kat_id, None, po_zapisie=self._pole_zapisane)
        okno.pokaz()
        return okno

    def edytuj_pole(self):
        if not self._pole_wlasne():
            return None
        okno = OknoPola(self.glowne, self.kat_id, self.pole_kod, po_zapisie=self._pole_zapisane)
        okno.pokaz()
        return okno

    def wartosci_pola(self):
        if not self._pole_listy():
            return None
        okno = OknoWartosci(self.glowne, self.kat_id, self.pole_kod, po_zapisie=self._pole_zapisane)
        okno.pokaz()
        return okno

    def _pole_zapisane(self, kod: str) -> None:
        self.pole_kod = kod
        self._po_zmianie()

    def usun_pole(self) -> None:
        if not self._pole_wlasne():
            return
        pole = next(p for p in slowniki.szablon(self.db, self.kat_id) if p["kod"] == self.pole_kod)
        uzycie = edycja.uzycie_pola(self.db, self.kat_id, self.pole_kod)
        pytanie = t("pytanie.usun_pole", nazwa=nazwa(pole["nazwy"]))
        if any(uzycie.values()):
            pytanie += "\n\n" + t("pytanie.usun_pole_dane", modele=uzycie["model"], egzemplarze=uzycie["egzemplarz"])
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            edycja.usun_pole(self.db, self.kat_id, self.pole_kod)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.pole_kod = None
        self._po_zmianie()

    def przesun_pole(self, kierunek: int) -> None:
        if not self._pole_wlasne():
            return
        try:
            edycja.przesun_pole(self.db, self.kat_id, self.pole_kod, kierunek)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._po_zmianie()

    def status(self, status_id: int | None):
        okno = OknoStatusu(self.glowne, status_id, po_zapisie=self._status_zapisany)
        okno.pokaz()
        return okno

    def edytuj_status(self):
        wiersz = (self.db.execute("SELECT kod FROM status WHERE id = ?", (self.status_id,)).fetchone()
                  if self.status_id is not None else None)
        if wiersz is None or wiersz["kod"] is not None:
            return None
        return self.status(self.status_id)

    def _status_zapisany(self, status_id: int) -> None:
        self.status_id = status_id
        self._po_zmianie()

    def usun_status(self) -> None:
        wiersz = (self.db.execute("SELECT kod, nazwy FROM status WHERE id = ?", (self.status_id,)).fetchone()
                  if self.status_id is not None else None)
        if wiersz is None or wiersz["kod"] is not None:
            return
        if not messagebox.askyesno(t("okno.potwierdzenie"), t("pytanie.usun_status", nazwa=nazwa(wiersz["nazwy"])),
                                   parent=self):
            return
        try:
            edycja.usun_status(self.db, self.status_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.status_id = None
        self._po_zmianie()


# ---------------------------------------------------------------------------
# Małe okna: nazwy w dwóch językach (wystarczy jeden), plus pola zależne od rodzaju
# ---------------------------------------------------------------------------
class _OknoNazw(OknoDialogowe):
    tytul_nowy = tytul_edycja = ""

    def __init__(self, glowne, ident, nazwy: dict, po_zapisie=None):
        super().__init__(glowne)
        self.ident = ident
        self.po_zapisie = po_zapisie
        self.nazwy = {j: tk.StringVar(value=nazwy.get(j, "")) for j in ("pl", "en")}

    def _pola_nazw(self, ramka: ttk.Frame, od_wiersza: int) -> int:
        jezyki = sorted(self.nazwy, key=lambda j: j != jezyk_biezacy())
        for i, jezyk in enumerate(jezyki):
            ttk.Label(ramka, text=t(f"pole.nazwa_{jezyk}"), style="Pole.TLabel").grid(
                row=od_wiersza + i, column=0, sticky="w", padx=(0, 10), pady=3)
            pole = ttk.Entry(ramka, textvariable=self.nazwy[jezyk], width=36)
            pole.grid(row=od_wiersza + i, column=1, sticky="we", pady=3)
            if i == 0:
                pole.focus_set()
        ttk.Label(ramka, text=t("formularz.nazwa_jednojezyczna"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=od_wiersza + 2, column=1, sticky="w", pady=(2, 0))
        return od_wiersza + 3

    def _zakoncz(self, wynik) -> None:
        self.zamknij()
        if self.po_zapisie:
            self.po_zapisie(wynik)


class OknoKategorii(_OknoNazw):
    def __init__(self, glowne, kat_id, rodzic_id, po_zapisie=None):
        wiersz = slowniki.kategoria(glowne.db, kat_id) if kat_id else None
        super().__init__(glowne, kat_id, json.loads(wiersz["nazwy"]) if wiersz else {}, po_zapisie)
        self.rodzic = PoleWyboru(self._opcje_rodzica, rodzic_id or "")
        self.rodzaj = PoleWyboru(lambda: opcje("kategoria.rodzaj"), wiersz["rodzaj"] if wiersz else "czesc")

    def _opcje_rodzica(self):
        pomin = set()
        if self.ident:                              # nie do własnego wnętrza
            from uslugi.slowniki_edycja import _potomkowie
            pomin = {self.ident, *_potomkowie(self.db, self.ident)}
        return [("", t("slowniki.kategoria_glowna"))] + [
            (k, "    " * g + n) for k, g, n in slowniki.kategorie_plasko(self.db) if k not in pomin]

    def zbuduj_ui(self) -> None:
        self.title(t("okno.kategoria_nowa") if self.ident is None else t("okno.kategoria_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        wiersz = self._pola_nazw(ramka, 0)
        ttk.Label(ramka, text=t("slowniki.nadrzedna"), style="Pole.TLabel").grid(row=wiersz, column=0, sticky="w",
                                                                                padx=(0, 10), pady=3)
        self.rodzic.zbuduj(ramka, width=36).grid(row=wiersz, column=1, sticky="we", pady=3)
        ttk.Label(ramka, text=t("pole.rodzaj"), style="Pole.TLabel").grid(row=wiersz + 1, column=0, sticky="w",
                                                                         padx=(0, 10), pady=3)
        self.rodzaj.zbuduj(ramka, width=24).grid(row=wiersz + 1, column=1, sticky="w", pady=3)
        ttk.Label(ramka, text=t("slowniki.rodzaj_podpowiedz"), style="Opis.TLabel", wraplength=360,
                  justify="left").grid(row=wiersz + 2, column=1, sticky="w")
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz + 3, column=0, columnspan=2, sticky="we", pady=(12, 0))

    def zapisz(self) -> None:
        try:
            kat_id = edycja.zapisz_kategorie(self.db, {"nazwy": {j: v.get() for j, v in self.nazwy.items()},
                                                       "rodzic_id": self.rodzic.wartosc or None,
                                                       "rodzaj": self.rodzaj.wartosc}, self.ident)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(kat_id)


class OknoStatusu(_OknoNazw):
    def __init__(self, glowne, status_id, po_zapisie=None):
        wiersz = glowne.db.execute("SELECT nazwy FROM status WHERE id = ?", (status_id,)).fetchone() if status_id else None
        super().__init__(glowne, status_id, json.loads(wiersz["nazwy"]) if wiersz else {}, po_zapisie)

    def zbuduj_ui(self) -> None:
        self.title(t("okno.status_nowy") if self.ident is None else t("okno.status_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        wiersz = self._pola_nazw(ramka, 0)
        ramka.columnconfigure(1, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self.bind("<Return>", lambda _e: self.zapisz())

    def zapisz(self) -> None:
        try:
            status_id = edycja.zapisz_status(self.db, {j: v.get() for j, v in self.nazwy.items()}, self.ident)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(status_id)


class OknoPola(_OknoNazw):
    def __init__(self, glowne, kat_id: int, kod: str | None, po_zapisie=None):
        pole = next((p for p in slowniki.szablon(glowne.db, kat_id) if p["kod"] == kod), {}) if kod else {}
        super().__init__(glowne, kod, pole.get("nazwy", {}), po_zapisie)
        self.kat_id = kat_id
        self.typ = PoleWyboru(opcje_typow, pole.get("typ", "text"),
                              przy_zmianie=lambda _w: self._pokaz_dodatkowe())
        self._typ_poczatkowy = pole.get("typ")
        self.jednostka = tk.StringVar(value=pole.get("jednostka", ""))
        self.wartosci = PoleTekstu("\n".join(pole.get("wartosci", [])))
        self._jednostka = self._wartosci = None

    def zbuduj_ui(self) -> None:
        self.title(t("okno.pole_nowe") if self.ident is None else t("okno.pole_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        kat = slowniki.kategoria(self.db, self.kat_id)
        ttk.Label(ramka, text=t("slowniki.pole_w_kategorii", kategoria=nazwa(kat["nazwy"])),
                  style="Opis.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        wiersz = self._pola_nazw(ramka, 1)
        ttk.Label(ramka, text=t("slowniki.typ"), style="Pole.TLabel").grid(row=wiersz, column=0, sticky="w",
                                                                          padx=(0, 10), pady=3)
        self.typ.zbuduj(ramka, width=24).grid(row=wiersz, column=1, sticky="w", pady=3)
        if self._typ_poczatkowy == "text":
            ttk.Label(ramka, text=t("slowniki.typ_tekst_lista"), style="Opis.TLabel", wraplength=360,
                      justify="left").grid(row=wiersz, column=2, sticky="w", padx=(8, 0))
        self._jednostka = ttk.Frame(ramka)
        self._jednostka.grid(row=wiersz + 1, column=0, columnspan=2, sticky="we")
        ttk.Label(self._jednostka, text=t("slowniki.jednostka"), style="Pole.TLabel", width=18).pack(side="left")
        ttk.Entry(self._jednostka, textvariable=self.jednostka, width=10).pack(side="left", padx=(4, 0))
        ttk.Label(self._jednostka, text=t("slowniki.jednostka_przyklad"), style="Opis.TLabel").pack(side="left", padx=8)
        self._wartosci = ttk.Frame(ramka)
        self._wartosci.grid(row=wiersz + 2, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        ttk.Label(self._wartosci, text=t("slowniki.wartosci"), style="Pole.TLabel").pack(anchor="w")
        self.wartosci.zbuduj(self._wartosci, height=6, width=40).pack(fill="both", expand=True)
        ramka.columnconfigure(1, weight=1)
        ramka.rowconfigure(wiersz + 2, weight=1)
        self.przyciski(ramka, self.zapisz).grid(row=wiersz + 3, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self._pokaz_dodatkowe()

    def _pokaz_dodatkowe(self) -> None:
        if self._jednostka is None or not self._jednostka.winfo_exists():
            return
        if self.typ.wartosc in ("int", "real"):
            self._jednostka.grid()
        else:
            self._jednostka.grid_remove()
        if self.typ.wartosc == "enum":
            self._wartosci.grid()
        else:
            self._wartosci.grid_remove()

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.wartosci.zapamietaj()

    def zapisz(self) -> None:
        dane = {"nazwy": {j: v.get() for j, v in self.nazwy.items()}, "typ": self.typ.wartosc,
                "jednostka": self.jednostka.get(), "wartosci": self.wartosci.zapamietaj().splitlines()}
        try:
            if self.ident is None:
                kod = edycja.dodaj_pole(self.db, self.kat_id, dane)
            else:
                edycja.zapisz_pole(self.db, self.kat_id, self.ident, dane)
                kod = self.ident
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self._zakoncz(kod)


class OknoWartosci(OknoDialogowe):
    """Wartości do wyboru w polu typu „wybór z listy”, np. kolor obudowy z edycją
    limitowaną albo SECAM w „Normie TV”. Przy polu wbudowanym lista wbudowana jest
    tylko do odczytu, a edytuje się dopiski; przy własnym — całą listę."""

    def __init__(self, glowne, kat_id: int, kod: str, po_zapisie=None):
        super().__init__(glowne)
        self.kat_id, self.kod, self.po_zapisie = kat_id, kod, po_zapisie
        self.dane = edycja.wartosci_listy(self.db, kat_id, kod)
        self.wartosci = PoleTekstu("\n".join(self.dane["edytowalne"]))

    def zbuduj_ui(self) -> None:
        self.title(t("okno.wartosci_listy"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=nazwa(self.dane["nazwy"]), style="Naglowek.TLabel").pack(anchor="w")
        if self.dane["kategoria"] != self.kat_id:
            ttk.Label(ramka, text=t("slowniki.z_kategorii", kategoria=nazwa(
                slowniki.kategoria(self.db, self.dane["kategoria"])["nazwy"])), style="Opis.TLabel").pack(anchor="w")
        if self.dane["wbudowane"]:
            ttk.Label(ramka, text=t("slowniki.wartosci_wbudowane", lista=", ".join(self.dane["wbudowane"])),
                      style="Opis.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(ramka, text=t("slowniki.wartosci_twoje" if self.dane["wbudowane"] else "slowniki.wartosci"),
                  style="Pole.TLabel").pack(anchor="w", pady=(10, 0))
        self.wartosci.zbuduj(ramka, height=8, width=40).pack(fill="both", expand=True, pady=(4, 0))
        ttk.Label(ramka, text=t("slowniki.wartosci_podpowiedz"), style="Opis.TLabel", wraplength=420,
                  justify="left").pack(anchor="w", pady=(6, 0))
        self.przyciski(ramka, self.zapisz).pack(fill="x", pady=(12, 0))

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.wartosci.zapamietaj()

    def zapisz(self) -> None:
        try:
            edycja.ustaw_wartosci_wlasne(self.db, self.kat_id, self.kod, self.wartosci.zapamietaj().splitlines())
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.zamknij()
        if self.po_zapisie:
            self.po_zapisie(self.kod)
