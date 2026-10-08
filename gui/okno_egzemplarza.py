# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno dodawania i edycji egzemplarza.

Cały stan formularza żyje w atrybutach (StringVar, PoleWyboru, PoleTekstu,
FormularzAtrybutow), więc okno przeżywa przebudowę po zmianie języka
z wpisanymi, a jeszcze niezapisanymi danymi.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from baza.enumy import opcje
from baza.repozytoria import egzemplarze, lokalizacje, modele, slowniki, ustawienia
from baza.repozytoria import zlacza as repo_zlaczy
from gui.bazowe import OknoDialogowe, pokaz_blad
from gui.model_drzewa import iid_egzemplarza
from gui.pola import FormularzAtrybutow, PoleTekstu, PoleWyboru
from gui.zlacza import EdytorZlaczy
from i18n.tlumacz import nazwa, t
from uslugi import inwentarz
from uslugi.formatowanie import minor_na_tekst, sprawdz_date, tekst_na_minor
from wyjatki import BladNornicy

POLA_TEKSTOWE = ("nazwa_wlasna", "kod_inwentarzowy", "numer_seryjny", "rewizja",
                 "pozycja_montazu", "data_nabycia", "zrodlo_nabycia", "cena")


class OknoEgzemplarza(OknoDialogowe):
    ZAKLADKA_ZLACZY = 2

    def __init__(self, glowne, egz_id: int | None,
                 lokalizacja_id: int | None = None, rodzic_id: int | None = None,
                 zakladka: int = 0):
        super().__init__(glowne)
        self.egz_id = egz_id
        self._zakladka = zakladka
        e = egzemplarze.pobierz(self.db, egz_id) if egz_id else None
        self._wykluczeni = ({egz_id} | egzemplarze.potomkowie(self.db, egz_id)) if egz_id else set()

        def wartosc(klucz, domyslna=None):
            return e[klucz] if e is not None and e[klucz] is not None else domyslna

        self.v = {k: tk.StringVar(value=wartosc(k, "")) for k in POLA_TEKSTOWE if k != "cena"}
        self.v["ilosc"] = tk.StringVar(value=str(wartosc("ilosc", 1)))
        waluta = wartosc("waluta_kod") or ustawienia.pobierz(self.db, "domyslna_waluta", "PLN")
        self.v["cena"] = tk.StringVar(value=minor_na_tekst(
            wartosc("cena_minor"), slowniki.miejsca_dziesietne(self.db, waluta)))

        rodzic_id = wartosc("rodzic_id", rodzic_id)
        self.umiejscowienie = tk.StringVar(value="montaz" if rodzic_id else "lokalizacja")
        self.kategoria = PoleWyboru(self._opcje_kategorii, wartosc("kat_id"),
                                    przy_zmianie=self._kategoria_zmieniona)
        self.model = PoleWyboru(self._opcje_modeli, wartosc("model_id"),
                                przy_zmianie=self._model_zmieniony)
        self.status = PoleWyboru(self._opcje_statusow,
                                 wartosc("status_id", slowniki.status_id(self.db, "nietestowany")))
        self.stan_wizualny = PoleWyboru(lambda: [(None, "—")] + opcje("egzemplarz.stan_wizualny"),
                                        wartosc("stan_wizualny"))
        self.lokalizacja = PoleWyboru(self._opcje_lokalizacji, wartosc("lokalizacja_id", lokalizacja_id))
        self.rodzic = PoleWyboru(self._opcje_rodzicow, rodzic_id)
        self.waluta = PoleWyboru(self._opcje_walut, waluta)
        self.uwagi = PoleTekstu(wartosc("uwagi", ""))
        self.atrybuty = FormularzAtrybutow(json.loads(wartosc("atrybuty", "{}")),
                                           self._atrybuty_modelu(wartosc("model_id")))
        z_modelu = repo_zlaczy.modelu(self.db, wartosc("model_id"))
        self.zlacza = EdytorZlaczy(
            self.db, repo_zlaczy.efektywne(z_modelu, repo_zlaczy.nadpisania_egzemplarza(self.db, egz_id)),
            dziedziczone=z_modelu, glowne=glowne)
        if e is None and rodzic_id:
            # część dodawana „do środka” — domyślnie kategoria Części
            wiersz = self.db.execute("SELECT id FROM kategoria WHERE kod = 'czesci'").fetchone()
            self.kategoria.wartosc = wiersz[0] if wiersz else None

    def _atrybuty_modelu(self, model_id: int | None) -> dict:
        m = modele.pobierz(self.db, model_id) if model_id else None
        return json.loads(m["atrybuty"] or "{}") if m else {}

    # ------------------------------------------------------------------ opcje
    def _opcje_kategorii(self):
        return [(kid, "    " * glebokosc + nazwa_) for kid, glebokosc, nazwa_ in
                slowniki.kategorie_plasko(self.db)]

    def _opcje_modeli(self):
        wynik = [(None, t("egzemplarz.bez_modelu"))]
        if self.kategoria.wartosc:
            wynik += [(m["id"], modele.etykieta(m)) for m in modele.w_kategorii(self.db, self.kategoria.wartosc)]
        return wynik

    def _opcje_statusow(self):
        return [(s["id"], nazwa(s["nazwy"])) for s in slowniki.statusy(self.db)]

    def _opcje_lokalizacji(self):
        sciezki = lokalizacje.sciezki(self.db)
        from baza.polaczenie import klucz_sortowania
        return [(None, t("lokalizacja.brak"))] + sorted(sciezki.items(),
                                                        key=lambda p: klucz_sortowania(p[1]))

    def _opcje_rodzicow(self):
        from baza.polaczenie import klucz_sortowania
        wynik = []
        for e in egzemplarze.lista(self.db):
            if e["id"] in self._wykluczeni or e["ilosc"] > 1:
                continue
            tekst = egzemplarze.nazwa_wyswietlana(e)
            wynik.append((e["id"], f"{tekst} ({e['kod_inwentarzowy']})" if e["kod_inwentarzowy"] else tekst))
        return sorted(wynik, key=lambda p: klucz_sortowania(p[1]))

    def _opcje_walut(self):
        return [(w["kod"], f"{w['kod']}  {nazwa(w['nazwy'])}") for w in slowniki.waluty(self.db)]

    # ---------------------------------------------------------------- budowa
    def zbuduj_ui(self) -> None:
        self.title(t("okno.egzemplarz_nowy") if self.egz_id is None else t("okno.egzemplarz_edycja"))
        ramka = ttk.Frame(self, padding=14)
        ramka.pack(fill="both", expand=True)
        self._notatnik = ttk.Notebook(ramka)
        self._notatnik.pack(fill="both", expand=True)

        # --- Ogólne
        ogolne = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(ogolne, text=t("zakladka.ogolne"))
        wiersz = 0

        def etykieta(tekst_klucz, r):
            ttk.Label(ogolne, text=t(tekst_klucz), style="Pole.TLabel").grid(
                row=r, column=0, sticky="w", padx=(0, 10), pady=3)

        etykieta("pole.kategoria", wiersz)
        self.kategoria.zbuduj(ogolne, width=40).grid(row=wiersz, column=1, columnspan=2, sticky="we", pady=3)
        wiersz += 1
        etykieta("pole.model", wiersz)
        self.model.zbuduj(ogolne, width=40).grid(row=wiersz, column=1, sticky="we", pady=3)
        przyciski_modelu = ttk.Frame(ogolne)
        przyciski_modelu.grid(row=wiersz, column=2, sticky="w", padx=(6, 0))
        ttk.Button(przyciski_modelu, text=t("akcja.nowy_model"), command=self._nowy_model).pack(side="left")
        self._przycisk_edycji_modelu = ttk.Button(przyciski_modelu, text=t("akcja.edytuj_model_okno"),
                                                  command=self._edytuj_model)
        self._przycisk_edycji_modelu.pack(side="left", padx=(4, 0))
        self._odswiez_przycisk_modelu()
        wiersz += 1
        for klucz, pole in (("pole.nazwa_wlasna", "nazwa_wlasna"),
                            ("pole.kod_inwentarzowy", "kod_inwentarzowy"),
                            ("pole.numer_seryjny", "numer_seryjny"), ("pole.rewizja", "rewizja")):
            etykieta(klucz, wiersz)
            ttk.Entry(ogolne, textvariable=self.v[pole]).grid(row=wiersz, column=1, columnspan=2,
                                                             sticky="we", pady=3)
            wiersz += 1
            if pole == "kod_inwentarzowy":     # podpowiedź tuż pod polem, którego dotyczy
                ttk.Label(ogolne, text=t("formularz.kod_auto"), style="Opis.TLabel").grid(
                    row=wiersz, column=1, columnspan=2, sticky="w", pady=(0, 4))
                wiersz += 1
        etykieta("pole.status", wiersz)
        self.status.zbuduj(ogolne).grid(row=wiersz, column=1, sticky="we", pady=3)
        wiersz += 1
        etykieta("pole.stan_wizualny", wiersz)
        self.stan_wizualny.zbuduj(ogolne).grid(row=wiersz, column=1, sticky="we", pady=3)
        wiersz += 1
        etykieta("pole.ilosc", wiersz)
        ttk.Spinbox(ogolne, from_=1, to=100000, textvariable=self.v["ilosc"], width=8).grid(
            row=wiersz, column=1, sticky="w", pady=3)
        wiersz += 1

        ttk.Separator(ogolne).grid(row=wiersz, column=0, columnspan=3, sticky="we", pady=8)
        wiersz += 1
        etykieta("pole.miejsce", wiersz)
        wybor = ttk.Frame(ogolne)
        wybor.grid(row=wiersz, column=1, columnspan=2, sticky="w")
        for wartosc_, klucz in (("lokalizacja", "formularz.w_lokalizacji"),
                                ("montaz", "formularz.zamontowany_w")):
            ttk.Radiobutton(wybor, text=t(klucz), value=wartosc_, variable=self.umiejscowienie,
                            command=self._umiejscowienie_zmienione).pack(side="left", padx=(0, 12))
        wiersz += 1
        etykieta("pole.lokalizacja", wiersz)
        self._lok = self.lokalizacja.zbuduj(ogolne, width=40)
        self._lok.grid(row=wiersz, column=1, sticky="we", pady=3)
        self._przycisk_lokalizacji = ttk.Button(ogolne, text=t("akcja.nowa_lokalizacja_okno"),
                                                command=self._nowa_lokalizacja)
        self._przycisk_lokalizacji.grid(row=wiersz, column=2, sticky="w", padx=(6, 0))
        wiersz += 1
        etykieta("pole.zamontowany_w", wiersz)
        self._rodz = self.rodzic.zbuduj(ogolne, width=40)
        self._rodz.grid(row=wiersz, column=1, columnspan=2, sticky="we", pady=3)
        wiersz += 1
        etykieta("pole.pozycja_montazu", wiersz)
        self._poz = ttk.Entry(ogolne, textvariable=self.v["pozycja_montazu"])
        self._poz.grid(row=wiersz, column=1, columnspan=2, sticky="we", pady=3)
        ogolne.columnconfigure(1, weight=1)
        self._umiejscowienie_zmienione()

        # --- Parametry
        self._parametry = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(self._parametry, text=t("zakladka.parametry"))
        self._zbuduj_parametry()

        # --- Złącza (z modelu + zmiany tego egzemplarza)
        karta_zlaczy = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(karta_zlaczy, text=t("zakladka.zlacza"))
        self.zlacza.zbuduj(karta_zlaczy)

        # --- Prywatne i uwagi
        prywatne = ttk.Frame(self._notatnik, padding=12)
        self._notatnik.add(prywatne, text=t("zakladka.prywatne"))
        ttk.Label(prywatne, text=t("formularz.dane_prywatne"), style="Opis.TLabel",
                  wraplength=460, justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        for r, (klucz, pole) in enumerate((("pole.data_nabycia", "data_nabycia"),
                                           ("pole.zrodlo_nabycia", "zrodlo_nabycia")), 1):
            ttk.Label(prywatne, text=t(klucz), style="Pole.TLabel").grid(row=r, column=0, sticky="w",
                                                                        padx=(0, 10), pady=3)
            if pole == "data_nabycia":
                ttk.Entry(prywatne, textvariable=self.v[pole], width=14).grid(row=r, column=1, sticky="w", pady=3)
                ttk.Label(prywatne, text=t("formularz.format_daty"), style="Opis.TLabel").grid(
                    row=r, column=2, sticky="w", padx=(6, 0))
            else:
                ttk.Entry(prywatne, textvariable=self.v[pole]).grid(row=r, column=1, columnspan=2,
                                                                   sticky="we", pady=3)
        ttk.Label(prywatne, text=t("pole.cena"), style="Pole.TLabel").grid(row=3, column=0, sticky="w",
                                                                          padx=(0, 10), pady=3)
        ttk.Entry(prywatne, textvariable=self.v["cena"], width=14).grid(row=3, column=1, sticky="w", pady=3)
        self.waluta.zbuduj(prywatne, width=30).grid(row=3, column=2, sticky="we", padx=(6, 0), pady=3)
        ttk.Label(prywatne, text=t("pole.uwagi"), style="Pole.TLabel").grid(row=4, column=0, sticky="nw",
                                                                           padx=(0, 10), pady=(10, 3))
        self.uwagi.zbuduj(prywatne, height=6, width=50).grid(row=4, column=1, columnspan=2,
                                                             sticky="nsew", pady=(10, 3))
        prywatne.columnconfigure(2, weight=1)
        prywatne.rowconfigure(4, weight=1)

        self.przyciski(ramka, self.zapisz).pack(fill="x", pady=(12, 0))

    def _zbuduj_parametry(self) -> None:
        if not hasattr(self, "_parametry") or not self._parametry.winfo_exists():
            return
        self.atrybuty.zbuduj(self._parametry, slowniki.szablon(self.db, self.kategoria.wartosc))

    def _odswiez_przycisk_modelu(self) -> None:
        przycisk = getattr(self, "_przycisk_edycji_modelu", None)
        if przycisk is not None and przycisk.winfo_exists():
            przycisk.configure(state="normal" if self.model.wartosc else "disabled")

    def zapamietaj_stan(self) -> None:
        super().zapamietaj_stan()
        self.uwagi.zapamietaj()

    # --------------------------------------------------------------- reakcje
    def _kategoria_zmieniona(self, wartosc) -> None:
        # Zgłoszenie: zmiana kategorii odłączała model (lista pokazuje tylko modele z wybranej
        # kategorii) i parametry znikały. Kategoria należy do modelu — proponujemy przeniesienie.
        model_id = self.model.wartosc
        if model_id and wartosc:
            kat_modelu = self.db.execute("SELECT kategoria_id FROM model WHERE id = ?", (model_id,)).fetchone()[0]
            if wartosc != kat_modelu:
                self.kategoria.ustaw(kat_modelu)        # cofnięcie — model zostaje
                if messagebox.askyesno(t("okno.potwierdzenie"), self._pytanie_o_przeniesienie(model_id, wartosc),
                                       parent=self):
                    from gui.okno_przeniesienia import OknoPrzeniesienia
                    OknoPrzeniesienia(self.glowne, model_id=model_id, kategoria_id=wartosc,
                                      po_przeniesieniu=self._model_przeniesiony).pokaz()
                return
        poprzedni = self.model.wartosc
        self.model.odswiez_opcje()           # model spoza nowej kategorii zostaje wyczyszczony
        if self.model.wartosc != poprzedni:
            self.atrybuty.ustaw_dziedziczone(self._atrybuty_modelu(self.model.wartosc))
            self.zlacza.ustaw_dziedziczone(repo_zlaczy.modelu(self.db, self.model.wartosc))
        self._odswiez_przycisk_modelu()
        self._zbuduj_parametry()

    def _pytanie_o_przeniesienie(self, model_id: int, kategoria_id: int) -> str:
        from i18n.tlumacz import nazwa
        model = self.db.execute("SELECT nazwa FROM model WHERE id = ?", (model_id,)).fetchone()[0]
        kategoria = self.db.execute("SELECT nazwy FROM kategoria WHERE id = ?", (kategoria_id,)).fetchone()[0]
        liczba = self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE model_id = ?", (model_id,)).fetchone()[0]
        return t("pytanie.przenies_model", model=model, kategoria=nazwa(kategoria), liczba=liczba)

    def _model_przeniesiony(self, kategoria_id: int) -> None:
        """Po przeniesieniu modelu: formularz w nowej kategorii, z tym samym modelem."""
        self.kategoria.ustaw(kategoria_id)
        self.model.odswiez_opcje()
        self.atrybuty.ustaw_dziedziczone(self._atrybuty_modelu(self.model.wartosc))
        self._zbuduj_parametry()

    def _model_zmieniony(self, model_id) -> None:
        self.atrybuty.ustaw_dziedziczone(self._atrybuty_modelu(model_id))
        self.zlacza.ustaw_dziedziczone(repo_zlaczy.modelu(self.db, model_id))
        self._odswiez_przycisk_modelu()

    def _umiejscowienie_zmienione(self) -> None:
        montaz = self.umiejscowienie.get() == "montaz"
        self._lok.configure(state="disabled" if montaz else "readonly")
        self._przycisk_lokalizacji.configure(state="disabled" if montaz else "normal")
        self._rodz.configure(state="readonly" if montaz else "disabled")
        self._poz.configure(state="normal" if montaz else "disabled")

    def _nowy_model(self) -> None:
        from gui.okno_modelu import OknoModelu

        OknoModelu(self.glowne, None, kategoria_id=self.kategoria.wartosc,
                   po_zapisie=self._model_zapisany).pokaz()

    def _nowa_lokalizacja(self) -> None:
        from gui.okno_lokalizacji import OknoLokalizacji

        def po_zapisie(lok_id: int) -> None:
            if self.winfo_exists():
                self.lokalizacja.odswiez_opcje()
                self.lokalizacja.ustaw(lok_id)

        OknoLokalizacji(self.glowne, None, rodzic_id=self.lokalizacja.wartosc,
                        po_zapisie=po_zapisie).pokaz()

    def _edytuj_model(self) -> None:
        from gui.okno_modelu import OknoModelu
        if self.model.wartosc:
            OknoModelu(self.glowne, self.model.wartosc, po_zapisie=self._model_zapisany).pokaz()

    def _model_zapisany(self, model_id: int) -> None:
        """Po dodaniu lub poprawieniu modelu: nowa etykieta na liście, kategoria
        modelu i jego aktualne parametry jako wartości dziedziczone."""
        self.glowne.odswiez()
        m = modele.pobierz(self.db, model_id)
        if not self.winfo_exists() or m is None:
            return
        self.kategoria.ustaw(m["kategoria_id"])
        self.model.odswiez_opcje()
        self.model.ustaw(model_id)
        self.atrybuty.ustaw_dziedziczone(self._atrybuty_modelu(model_id))
        self.zlacza.ustaw_dziedziczone(repo_zlaczy.modelu(self.db, model_id))
        self._odswiez_przycisk_modelu()
        self._zbuduj_parametry()

    # ----------------------------------------------------------------- zapis
    def _zbierz(self) -> dict:
        try:
            ilosc = int(self.v["ilosc"].get())
            if ilosc < 1:
                raise ValueError
        except ValueError:
            raise BladNornicy("blad.wartosc_liczbowa", pole=t("pole.ilosc")) from None
        try:
            data = sprawdz_date(self.v["data_nabycia"].get())
        except ValueError:
            raise BladNornicy("blad.zla_data") from None
        cena_tekst = self.v["cena"].get()
        cena = None
        if cena_tekst.strip():
            if not self.waluta.wartosc:
                raise BladNornicy("blad.cena_wymaga_waluty")
            try:
                cena = tekst_na_minor(cena_tekst, slowniki.miejsca_dziesietne(self.db, self.waluta.wartosc))
            except ValueError:
                raise BladNornicy("blad.zla_kwota") from None
        montaz = self.umiejscowienie.get() == "montaz"
        if montaz and not self.rodzic.wartosc:
            raise BladNornicy("blad.wybierz_rodzica")
        return {
            "kategoria_id": self.kategoria.wartosc,
            "model_id": self.model.wartosc,
            "nazwa_wlasna": self.v["nazwa_wlasna"].get(),
            "kod_inwentarzowy": self.v["kod_inwentarzowy"].get(),
            "numer_seryjny": self.v["numer_seryjny"].get(),
            "rewizja": self.v["rewizja"].get(),
            "status_id": self.status.wartosc,
            "stan_wizualny": self.stan_wizualny.wartosc,
            "ilosc": ilosc,
            "rodzic_id": self.rodzic.wartosc if montaz else None,
            "pozycja_montazu": self.v["pozycja_montazu"].get() if montaz else None,
            "lokalizacja_id": None if montaz else self.lokalizacja.wartosc,
            "atrybuty": self.atrybuty.zbierz(slowniki.szablon(self.db, self.kategoria.wartosc)),
            "data_nabycia": data,
            "zrodlo_nabycia": self.v["zrodlo_nabycia"].get(),
            "cena_minor": cena,
            "waluta_kod": self.waluta.wartosc if cena is not None else None,
            "uwagi": self.uwagi.zapamietaj(),
            "zlacza": self.zlacza.wynik(),
        }

    def zapisz(self) -> None:
        try:
            nowy_id = inwentarz.zapisz_egzemplarz(self.db, self._zbierz(), self.egz_id)
        except Exception as blad:   # noqa: BLE001 — każdy błąd trafia do użytkownika
            pokaz_blad(self, blad)
            return
        self.glowne.odswiez(zaznacz=iid_egzemplarza(nowy_id))
        self.zamknij()
