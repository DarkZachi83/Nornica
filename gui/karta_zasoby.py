# SPDX-License-Identifier: GPL-3.0-or-later
"""Zakładka Zasoby: zdjęcia, pliki, odnośniki i notatki egzemplarza.

Klasa pomocnicza panelu szczegółów (gui/szczegoly.py): korzysta z jego
atrybutów — glowne, db, notatnik, gora, rodzic — i nie działa samodzielnie.
"""
from __future__ import annotations

import base64
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from baza.enumy import etykieta
from baza.repozytoria import ustawienia
from baza.repozytoria.szczegoly import cel_powiazania, zasoby_dziedziczone
from gui.bazowe import pokaz_blad
from i18n.tlumacz import t
from uslugi import pliki
from wyjatki import BladNornicy

# Linux: wzorce plików w oknie wyboru rozróżniają wielkość liter — aparaty
# zapisują „IMG_0001.JPG”, więc wielkie litery muszą być na liście.
WZORCE_ZDJEC = " ".join(f"*{r} *{r.upper()}" for r in sorted(pliki.ROZSZERZENIA_ZDJEC))
SKALA_PASKA = 2          # miniatury 160 px w bazie, w pasku pokazane w połowie

class ZasobyKarty:
    """Pasek miniatur, lista pozostałych zasobów oraz dodawanie, otwieranie i usuwanie."""

    # ------------------------------------------------------------------ zasoby
    def _zasoby(self, karta: ttk.Frame, egz_id: int) -> None:
        przyciski = ttk.Frame(karta)
        przyciski.pack(fill="x", pady=(0, 8))
        for i, (klucz, polecenie) in enumerate((
                ("akcja.dodaj_zdjecia", lambda: self.dodaj_zdjecia(egz_id)),
                ("akcja.dodaj_plik", lambda: self._dodaj_plik(egz_id)),
                ("akcja.dodaj_odnosnik", lambda: self._okno_zasobu(egz_id, "link")),
                ("akcja.dodaj_notatke", lambda: self._okno_zasobu(egz_id, "notatka")))):
            ttk.Button(przyciski, text=t(klucz), command=polecenie).grid(
                row=i // 2, column=i % 2, sticky="we", padx=(0, 6), pady=(0, 4))

        zasoby = zasoby_dziedziczone(self.db, egz_id)
        zdjecia = [z for z in zasoby if z["typ"] == "zdjecie"]
        pozostale = [z for z in zasoby if z["typ"] != "zdjecie"]
        if not zasoby:
            ttk.Label(karta, text=t("pusty.zasoby"), style="Opis.TLabel", wraplength=380,
                      justify="left").pack(anchor="w")
            return
        if zdjecia:
            self._pasek_miniatur(karta, egz_id, zdjecia)
        if zdjecia and not pliki.pillow_dostepne():
            ttk.Label(karta, text=t("zasoby.brak_pillow"), style="Opis.TLabel", wraplength=380,
                      justify="left").pack(anchor="w", pady=(0, 6))
        if pozostale:
            lista = ttk.Treeview(karta, columns=("typ", "tytul", "wersja", "skad"), show="headings", height=6)
            for kod, klucz, szerokosc in (("typ", "kolumna.typ", 90), ("tytul", "kolumna.tytul", 150),
                                          ("wersja", "kolumna.wersja", 60),
                                          ("skad", "kolumna.pochodzenie", 115)):
                lista.heading(kod, text=t(klucz), anchor="w")
                lista.column(kod, width=szerokosc, stretch=kod == "tytul")
            po_iid = {}
            for z in pozostale:
                iid = lista.insert("", "end", values=(etykieta("zasob.typ", z["typ"]), z["tytul"],
                                                       z["wersja"] or "", t(f"pochodzenie.{z['pochodzenie']}")))
                po_iid[iid] = z
            lista.pack(fill="both", expand=True)
            wybrany = lambda: po_iid.get(next(iter(lista.selection()), None))  # noqa: E731
            lista.bind("<Double-1>", lambda _e: wybrany() and self._otworz(egz_id, wybrany()))
            menu = lambda e: (lista.selection_set(lista.identify_row(e.y)) if lista.identify_row(e.y) else None,  # noqa: E731
                              wybrany() and self._menu_zasobu(e, egz_id, wybrany()))
            lista.bind("<Button-3>", menu)
            lista.bind("<Button-2>", menu)
        ttk.Label(karta, text=t("zasoby.podpowiedz"), style="Opis.TLabel", wraplength=380,
                  justify="left").pack(anchor="w", pady=(6, 0))

    def _pasek_miniatur(self, karta: ttk.Frame, egz_id: int, zdjecia: list) -> None:
        """Poziomy, przewijany pasek miniatur. Kliknięcie otwiera zdjęcie,
        prawy przycisk — menu (opis, odpięcie). Pole „Główne” wybiera zdjęcie
        pokazywane na karcie Ogólne (zaznaczenie innego odznacza poprzednie)."""
        glowne_ = pliki.zdjecie_glowne(self.db, egz_id)
        glowne_id = glowne_["id"] if glowne_ is not None else None
        ramka = ttk.Frame(karta)
        ramka.pack(fill="x", pady=(0, 8))
        wysokosc = 160 // SKALA_PASKA + 30
        plotno = tk.Canvas(ramka, height=wysokosc, highlightthickness=0,
                           background=self.glowne.cget("background"))
        przewijak = ttk.Scrollbar(ramka, orient="horizontal", command=plotno.xview)
        plotno.configure(xscrollcommand=przewijak.set)
        plotno.pack(fill="x")
        wnetrze = ttk.Frame(plotno)
        plotno.create_window(0, 0, window=wnetrze, anchor="nw")
        for z in zdjecia:
            komorka = ttk.Frame(wnetrze, padding=(0, 0, 8, 0))
            komorka.pack(side="left", anchor="n")
            obraz = None
            if z["miniatura"]:
                try:
                    obraz = tk.PhotoImage(master=self.glowne,
                                          data=base64.b64encode(z["miniatura"])).subsample(SKALA_PASKA)
                    self._miniatury.append(obraz)
                except tk.TclError:
                    obraz = None
            if obraz is not None:
                podglad = ttk.Label(komorka, image=obraz, cursor="hand2")
            else:
                podglad = ttk.Label(komorka, text=t("zasoby.bez_podgladu"), width=10, anchor="center",
                                    style="Opis.TLabel", cursor="hand2")
            podglad.pack()
            podpis = z["tytul"] if len(z["tytul"]) <= 14 else z["tytul"][:13] + "…"
            ttk.Label(komorka, text=podpis, style="Opis.TLabel").pack()
            if z["plik_sciezka"] and not pliki.plik_istnieje(self.db, z["plik_sciezka"]):
                # plik usunięty z dysku poza programem — miniatura w bazie została
                ttk.Label(komorka, text=t("zasoby.brak_pliku"), style="Ostrzezenie.TLabel").pack()
            zaznaczone = tk.IntVar(master=self.glowne, value=int(z["id"] == glowne_id))
            self._wybor_glownego.append(zaznaczone)
            ttk.Checkbutton(komorka, text=t("zasoby.glowne"), variable=zaznaczone,
                            command=lambda z=z, v=zaznaczone: self.ustaw_glowne(egz_id, z["id"] if v.get() else None)
                            ).pack()
            ttk.Button(komorka, text=t("akcja.usun_zdjecie"), style="Maly.TButton",
                       command=lambda z=z: self.usun_zdjecie(z)).pack(pady=(2, 0))
            podglad.bind("<Button-1>", lambda _e, z=z: self._otworz(egz_id, z))
            podglad.bind("<Button-3>", lambda e, z=z: self._menu_zasobu(e, egz_id, z))
            podglad.bind("<Button-2>", lambda e, z=z: self._menu_zasobu(e, egz_id, z))

        def dopasuj(_e=None):
            # wysokość paska = wysokość miniatur z podpisem (zdjęcia poziome są niższe)
            plotno.configure(scrollregion=plotno.bbox("all"), height=wnetrze.winfo_reqheight())
            if wnetrze.winfo_reqwidth() > plotno.winfo_width():
                przewijak.pack(side="bottom", fill="x", before=plotno)
            else:
                przewijak.pack_forget()

        wnetrze.bind("<Configure>", dopasuj)
        plotno.bind("<Configure>", dopasuj)

    def _menu_zasobu(self, zdarzenie, egz_id: int, zasob) -> None:
        menu = tk.Menu(self.glowne, tearoff=False)
        menu.add_command(label=t("akcja.otworz"), command=lambda: self._otworz(egz_id, zasob))
        menu.add_command(label=t("akcja.edytuj_opis"),
                         command=lambda: self._okno_zasobu(egz_id, "edycja", zasob_id=zasob["id"]))
        if zasob["typ"] == "zdjecie":
            menu.add_command(label=t("akcja.ustaw_glowne"), command=lambda: self.ustaw_glowne(egz_id, zasob["id"]))
        menu.add_separator()
        if zasob["typ"] == "zdjecie":
            menu.add_command(label=t("akcja.usun_zdjecie_pelne"), command=lambda: self.usun_zdjecie(zasob))
        menu.add_command(label=t("akcja.odepnij"), command=lambda: self._odepnij(zasob))
        try:
            menu.tk_popup(zdarzenie.x_root, zdarzenie.y_root)
        finally:
            menu.grab_release()

    # ---------------------------------------------------------------- akcje
    def _okno_zasobu(self, egz_id: int, tryb: str, **opcje):
        from gui.okno_zasobu import OknoZasobu
        okno = OknoZasobu(self.glowne, egz_id, tryb, **opcje)
        okno.pokaz()
        return okno

    def _katalog_startowy(self) -> str:
        return ustawienia.pobierz(self.db, "ostatni_katalog", str(Path.home())) or str(Path.home())

    def _zapamietaj_katalog(self, sciezka: str) -> None:
        ustawienia.zapisz(self.db, "ostatni_katalog", str(Path(sciezka).parent))

    def dodaj_zdjecia(self, egz_id: int) -> None:
        """Wybór wielu zdjęć naraz; każde podpinane do tego egzemplarza."""
        sciezki = filedialog.askopenfilenames(
            parent=self.glowne, title=t("okno.wybierz_zdjecia"), initialdir=self._katalog_startowy(),
            filetypes=[(t("plik.zdjecia"), WZORCE_ZDJEC), (t("plik.wszystkie"), "*")])
        if not sciezki:
            return
        self._zapamietaj_katalog(sciezki[0])
        self.dodaj_pliki_zdjec(egz_id, list(sciezki))

    def dodaj_pliki_zdjec(self, egz_id: int, sciezki: list[str]) -> None:
        bledy = []
        for sciezka in sciezki:
            try:
                pliki.dodaj_plik(self.db, sciezka, {"egzemplarz_id": egz_id}, typ="zdjecie")
            except Exception as blad:   # noqa: BLE001 — jeden zły plik nie zatrzymuje reszty
                bledy.append(f"{Path(sciezka).name}: {blad}")
        self.glowne.odswiez()
        if bledy:
            messagebox.showwarning(t("okno.uwaga"), t("zasoby.bledy_dodawania", lista="\n".join(bledy)),
                                   parent=self.glowne)

    def _dodaj_plik(self, egz_id: int) -> None:
        sciezka = filedialog.askopenfilename(parent=self.glowne, title=t("okno.wybierz_plik"),
                                             initialdir=self._katalog_startowy())
        if sciezka:
            self._zapamietaj_katalog(sciezka)
            self._okno_zasobu(egz_id, "plik", sciezka=sciezka)

    def _otworz(self, egz_id: int, zasob) -> None:
        if zasob["typ"] == "notatka" and not zasob["plik_sciezka"]:
            self._okno_zasobu(egz_id, "edycja", zasob_id=zasob["id"])
            return
        try:
            pliki.otworz_zasob(self.db, zasob)
        except BladNornicy as blad:
            if blad.klucz == "blad.brak_pliku":
                # plik usunięty poza programem: zamiast samego błędu — propozycja sprzątnięcia wpisu
                if messagebox.askyesno(t("okno.potwierdzenie"),
                                       t("pytanie.brak_pliku_usun_wpis", tytul=zasob["tytul"],
                                         sciezka=blad.pola.get("sciezka", "")), parent=self.glowne):
                    self._usun_zasob(zasob)
                return
            pokaz_blad(self.glowne, blad)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)

    def ustaw_glowne(self, egz_id: int, zasob_id: int | None) -> None:
        try:
            pliki.ustaw_zdjecie_glowne(self.db, egz_id, zasob_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()       # odświeża kartę: nowe zdjęcie, jedno zaznaczone pole

    def usun_zdjecie(self, zasob) -> None:
        """Przycisk „Usuń” pod miniaturą: jedno potwierdzenie, odpięcie i — gdy nic
        innego z niego nie korzysta — usunięcie pliku z dysku. Zdjęcie dziedziczone
        z modelu lub kategorii znika ze wszystkich egzemplarzy, więc pytanie to mówi."""
        if zasob["pochodzenie"] == "egzemplarz":
            pytanie = t("pytanie.usun_zdjecie", tytul=zasob["tytul"])
        else:
            pytanie = t("pytanie.usun_zdjecie_wspolne", tytul=zasob["tytul"],
                        skad=t(f"pochodzenie.{zasob['pochodzenie']}"))
        if messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self.glowne):
            self._usun_zasob(zasob)

    def _usun_zasob(self, zasob) -> None:
        """Odpięcie, a gdy zasób został sierotą — usunięcie rekordu i pliku.
        Plik używany gdzie indziej (np. przez model) zostaje."""
        try:
            if pliki.odepnij(self.db, zasob["id"], cel_powiazania(zasob)):
                pliki.usun_sieroty_z_plikami(self.db, [zasob["id"]])
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()

    def _odepnij(self, zasob) -> None:
        if zasob["pochodzenie"] == "egzemplarz":
            pytanie = t("pytanie.odepnij", tytul=zasob["tytul"])
        else:
            pytanie = t("pytanie.odepnij_wspolny", tytul=zasob["tytul"],
                        skad=t(f"pochodzenie.{zasob['pochodzenie']}"))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self.glowne):
            return
        try:
            sierota = pliki.odepnij(self.db, zasob["id"], cel_powiazania(zasob))
            if sierota and messagebox.askyesno(t("okno.potwierdzenie"),
                                               t("pytanie.usun_sierote", tytul=zasob["tytul"]),
                                               parent=self.glowne):
                pliki.usun_sieroty_z_plikami(self.db, [zasob["id"]])
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self.glowne, blad)
        self.glowne.odswiez()
