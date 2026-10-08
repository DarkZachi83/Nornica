# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno „Inwentaryzacje”: historia sesji z telefonu i raport wybranej.

Inwentaryzację prowadzi się telefonem (karta lokalizacji → „Rozpocznij
inwentaryzację”). To okno pokazuje wyniki — także na żywo, w trakcie
skanowania: każde zapytanie telefonu kończy się powiadomieniem otwartych
okien (dane_zmienione). Okno trzyma surowe dane, teksty powstają przy
wyświetleniu (zmiana języka na żywo).
"""
from __future__ import annotations

from tkinter import messagebox, ttk

from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import iid_egzemplarza
from i18n.tlumacz import nazwa, t
from uslugi import inwentaryzacja as inw
from uslugi.formatowanie import data_lokalna

GRUPY = ("brak", "nie_na_miejscu", "na_miejscu")


class OknoInwentaryzacji(OknoDialogowe):
    def __init__(self, glowne):
        super().__init__(glowne)
        self.sesja_id: int | None = None
        self.sesje: list = []
        self.pozycje: list[dict] = []
        self._lista = self._raport = self._podsumowanie = None
        self._przyciski: dict[str, ttk.Button] = {}
        self._policz()

    # ------------------------------------------------------------------ dane
    def _policz(self) -> None:
        self.sesje = inw.sesje(self.db)
        if self.sesja_id not in {s["id"] for s in self.sesje}:
            self.sesja_id = self.sesje[0]["id"] if self.sesje else None
        self.pozycje = inw.pozycje(self.db, self.sesja_id) if self.sesja_id else []

    def dane_zmienione(self) -> None:
        self._policz()
        self._pokaz()

    # ------------------------------------------------------------------ widok
    def pokaz(self) -> None:
        super().pokaz()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight() + 40}")

    def zbuduj_ui(self) -> None:
        self.title(t("okno.inwentaryzacje"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        ttk.Label(ramka, text=t("inw.wstep"), style="Opis.TLabel", wraplength=1100,
                  justify="left").pack(anchor="w", pady=(0, 10))
        dol = ttk.Frame(ramka)
        dol.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(dol, text=t("przycisk.zamknij"), command=self.zamknij).pack(side="right")

        srodek = ttk.Frame(ramka)
        srodek.pack(fill="both", expand=True)
        lewa = ttk.Frame(srodek)
        lewa.pack(side="left", fill="y")
        self._lista = ttk.Treeview(lewa, columns=("data", "miejsce", "wynik"), show="headings",
                                   selectmode="browse", height=16)
        for kolumna, klucz, szerokosc in (("data", "kolumna.data", 140), ("miejsce", "kolumna.lokalizacja", 170),
                                          ("wynik", "inw.kolumna.wynik", 120)):
            self._lista.heading(kolumna, text=t(klucz))
            self._lista.column(kolumna, width=szerokosc, stretch=kolumna == "miejsce")
        self._lista.pack(fill="y", expand=True)
        self._lista.bind("<<TreeviewSelect>>", self._wybrano_sesje)
        self._lista.tag_configure("w_toku", foreground="#7A5636")
        przyciski_sesji = ttk.Frame(lewa)
        przyciski_sesji.pack(fill="x", pady=(6, 0))
        self._przyciski["usun"] = ttk.Button(przyciski_sesji, text=t("inw.usun"), command=self.usun_sesje)
        self._przyciski["usun"].pack(side="left")
        ttk.Button(przyciski_sesji, text=t("akcja.odswiez"), command=self.dane_zmienione).pack(side="right")

        prawa = ttk.Frame(srodek, padding=(14, 0, 0, 0))
        prawa.pack(side="left", fill="both", expand=True)
        self._podsumowanie = ttk.Label(prawa, wraplength=680, justify="left")
        self._podsumowanie.pack(anchor="w", fill="x")
        obszar = ttk.Frame(prawa)
        obszar.pack(fill="both", expand=True, pady=(8, 0))
        self._raport = ttk.Treeview(obszar, columns=("kod", "opis"), show="tree headings",
                                    selectmode="browse", height=16)
        self._raport.heading("#0", text=t("kolumna.nazwa"))
        self._raport.heading("kod", text=t("kolumna.kod"))
        self._raport.heading("opis", text=t("inw.kolumna.uwagi"))
        self._raport.column("#0", width=300)
        self._raport.column("kod", width=100, stretch=False)
        self._raport.column("opis", width=300)
        przewijak = ttk.Scrollbar(obszar, orient="vertical", command=self._raport.yview)
        self._raport.configure(yscrollcommand=przewijak.set)
        przewijak.pack(side="right", fill="y")
        self._raport.pack(side="left", fill="both", expand=True)
        self._raport.tag_configure("grupa", font=self.glowne.czcionki["pogrubiona"])
        self._raport.tag_configure("brak", foreground="#A23B2A")
        self._raport.tag_configure("nie_na_miejscu", foreground="#A3641E")
        self._raport.bind("<<TreeviewSelect>>", lambda _e: self._stan_przyciskow())
        self._raport.bind("<Double-1>", lambda _e: self.pokaz_egzemplarz())
        przyciski = ttk.Frame(prawa)
        przyciski.pack(fill="x", pady=(6, 0))
        self._przyciski["pokaz"] = ttk.Button(przyciski, text=t("porzadki.pokaz"), command=self.pokaz_egzemplarz)
        self._przyciski["pokaz"].pack(side="left")
        self._pokaz()

    def _opis_sesji(self, s) -> str:
        if s["zakonczono"] is None:
            return t("inw.w_toku", na_miejscu=s["na_miejscu"], nie_na_miejscu=s["nie_na_miejscu"])
        return t("inw.wynik_krotki", na_miejscu=s["na_miejscu"], nie_na_miejscu=s["nie_na_miejscu"],
                 brak=s["brak"])

    @staticmethod
    def _skrot_sesji(s) -> str:
        """Wynik w kolumnie listy: znaki jak na telefonie (✓ ! ✗) — mieszczą się w wąskiej kolumnie."""
        skrot = f"✓ {s['na_miejscu']}   ! {s['nie_na_miejscu']}"
        return skrot + (f"   ✗ {s['brak']}" if s["zakonczono"] is not None else f"   ({t('inw.w_toku_krotko')})")

    def _pokaz(self) -> None:
        if self._lista is None or not self._lista.winfo_exists():
            return
        self._lista.delete(*self._lista.get_children())
        for s in self.sesje:
            self._lista.insert("", "end", iid=str(s["id"]),
                               values=(data_lokalna(s["rozpoczeto"]), s["lokalizacja_nazwa"], self._skrot_sesji(s)),
                               tags=("w_toku",) if s["zakonczono"] is None else ())
        if self.sesja_id is not None:
            self._lista.selection_set(str(self.sesja_id))
            self._lista.see(str(self.sesja_id))
        self._pokaz_raport()

    def _pokaz_raport(self) -> None:
        raport = self._raport
        raport.delete(*raport.get_children())
        sesja = next((s for s in self.sesje if s["id"] == self.sesja_id), None)
        if sesja is None:
            self._podsumowanie.configure(text=t("inw.brak_sesji"))
            self._stan_przyciskow()
            return
        if sesja["zakonczono"] is None:
            tekst = t("inw.naglowek_w_toku", miejsce=sesja["lokalizacja_nazwa"],
                      data=data_lokalna(sesja["rozpoczeto"]))
        else:
            tekst = t("inw.naglowek", miejsce=sesja["lokalizacja_nazwa"], data=data_lokalna(sesja["zakonczono"]))
        self._podsumowanie.configure(text=tekst + "\n" + self._opis_sesji(sesja))
        for grupa in GRUPY:
            pozycje = [p for p in self.pozycje if p["wynik"] == grupa]
            if not pozycje:
                continue
            raport.insert("", "end", iid=grupa, text=f"{t(f'inw.grupa.{grupa}')} ({len(pozycje)})",
                          open=True, tags=("grupa",))
            for p in pozycje:
                if grupa == "nie_na_miejscu":
                    opis = t("inw.w_bazie", miejsce=p["miejsce"]) if p["miejsce"] else t("inw.bez_miejsca")
                elif p["zamontowany_w"]:
                    opis = t("inw.tel.w_zestawie", nazwa=p["zamontowany_w"])
                elif grupa == "brak":
                    opis = p["miejsce"] or ""
                else:
                    opis = nazwa(p["status_nazwy"])
                raport.insert(grupa, "end", iid=f"{grupa}:{p['egzemplarz_id']}", text=p["nazwa"],
                              values=(p["kod"], opis), tags=(grupa,))
        self._stan_przyciskow()

    def _stan_przyciskow(self) -> None:
        wybor = self._raport.selection()
        self._przyciski["pokaz"].configure(state="normal" if wybor and ":" in wybor[0] else "disabled")
        self._przyciski["usun"].configure(state="normal" if self.sesja_id else "disabled")

    def _wybrano_sesje(self, _zdarzenie=None) -> None:
        wybor = self._lista.selection()
        if wybor and int(wybor[0]) != self.sesja_id:
            self.sesja_id = int(wybor[0])
            self.pozycje = inw.pozycje(self.db, self.sesja_id)
            self._pokaz_raport()

    # ------------------------------------------------------------------ akcje
    def pokaz_egzemplarz(self) -> None:
        wybor = self._raport.selection()
        if not wybor or ":" not in wybor[0]:
            return
        egz_id = int(wybor[0].split(":")[1])
        self.glowne.filtr_var.set("")
        self.glowne.odswiez(zaznacz=iid_egzemplarza(egz_id))
        self.glowne.lift()

    def usun_sesje(self) -> None:
        sesja = next((s for s in self.sesje if s["id"] == self.sesja_id), None)
        if sesja is None:
            return
        if not messagebox.askyesno(t("okno.potwierdzenie"),
                                   t("inw.pytanie_usun", miejsce=sesja["lokalizacja_nazwa"],
                                     data=data_lokalna(sesja["rozpoczeto"])), parent=self):
            return
        try:
            inw.usun(self.db, sesja["id"])
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.sesja_id = None
        self.dane_zmienione()
