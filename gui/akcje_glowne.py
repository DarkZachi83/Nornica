# SPDX-License-Identifier: GPL-3.0-or-later
"""Akcje okna głównego: otwieranie okien, usuwanie, przenoszenie, wydzielanie.

Klasa pomocnicza okna głównego (gui/okno_glowne.py): korzysta z jego
atrybutów — db, stan, _dialogi, _widzety, odswiez() — i nie działa samodzielnie.
"""
from __future__ import annotations

from tkinter import messagebox

from baza.repozytoria import egzemplarze, lokalizacje
from baza.zaleznosci import opis, zaleznosci
from gui.bazowe import pokaz_blad
from gui.model_drzewa import iid_egzemplarza, iid_lokalizacji, rozbierz_iid
from i18n.tlumacz import t
from uslugi import inwentarz


class AkcjeGlowne:
    """Polecenia z menu, paska, skrótów i menu kontekstowego drzewa."""

    def jedno_okno(self, klasa, **opcje):
        """Okno, które ma istnieć tylko raz: ponowne wywołanie wyciąga istniejące na wierzch."""
        for okno in self._dialogi:
            if isinstance(okno, klasa) and okno.winfo_exists():
                okno.lift()
                return okno
        okno = klasa(self, **opcje)
        okno.pokaz()
        return okno

    # ------------------------------------------------------------ otwieranie okien
    def nowy_egzemplarz(self, lokalizacja_id: int | None = None, rodzic_id: int | None = None):
        from gui.okno_egzemplarza import OknoEgzemplarza
        if lokalizacja_id is None and rodzic_id is None:
            rodzaj, ident = rozbierz_iid(self.stan.zaznaczone)
            if rodzaj == "L":
                lokalizacja_id = ident
        okno = OknoEgzemplarza(self, None, lokalizacja_id=lokalizacja_id, rodzic_id=rodzic_id)
        okno.pokaz()
        return okno

    def edytuj_egzemplarz(self, egz_id: int, zakladka: int = 0):
        from gui.okno_egzemplarza import OknoEgzemplarza
        okno = OknoEgzemplarza(self, egz_id, zakladka=zakladka)
        okno.pokaz()
        return okno

    def nowa_lokalizacja(self, rodzic_id: int | None = None):
        from gui.okno_lokalizacji import OknoLokalizacji
        okno = OknoLokalizacji(self, None, rodzic_id=rodzic_id)
        okno.pokaz()
        return okno

    def edytuj_lokalizacje(self, lok_id: int):
        from gui.okno_lokalizacji import OknoLokalizacji
        okno = OknoLokalizacji(self, lok_id)
        okno.pokaz()
        return okno

    def edytuj_model(self, model_id: int):
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self, model_id, po_zapisie=lambda _id: self.odswiez())
        okno.pokaz()
        return okno

    def katalog_modeli(self):
        """Katalog modeli (jedno okno)."""
        from gui.okno_katalogu import OknoKataloguModeli
        return self.jedno_okno(OknoKataloguModeli)

    def drukuj_etykiety(self):
        """Okno etykiet dla bieżącego zaznaczenia (egzemplarz, lokalizacja albo całość)."""
        from gui.okno_etykiet import OknoEtykiet
        okno = OknoEtykiet(self, self.stan.zaznaczone)
        okno.pokaz()
        return okno

    def eksportuj(self):
        from gui.okno_eksportu import OknoEksportu
        okno = OknoEksportu(self, self.stan.zaznaczone)
        okno.pokaz()
        return okno

    # ------------------------------------------------------------------ zmiany
    def przenies_kategorie(self, egz_id: int):
        """Egzemplarz z modelem: przenosi się model (kategoria należy do niego)."""
        from gui.okno_przeniesienia import OknoPrzeniesienia
        model_id = egzemplarze.pobierz(self.db, egz_id)["model_id"]
        okno = (OknoPrzeniesienia(self, model_id=model_id) if model_id is not None
                else OknoPrzeniesienia(self, egz_id=egz_id))
        okno.pokaz()
        return okno

    def asystent_ai(self, **opcje):
        """Asystent AI dla kilku przedmiotów naraz (jedno okno); opcje — dla testów."""
        from gui.okno_wsadowe import OknoWsadowe
        return self.jedno_okno(OknoWsadowe, **opcje)

    def slowniki(self):
        """Słowniki (jedno okno)."""
        from gui.okno_slownikow import OknoSlownikow
        return self.jedno_okno(OknoSlownikow)

    def porzadki(self):
        """Porządki (jedno okno)."""
        from gui.okno_porzadkow import OknoPorzadkow
        return self.jedno_okno(OknoPorzadkow)

    def inwentaryzacje(self):
        """Inwentaryzacje (jedno okno)."""
        from gui.okno_inwentaryzacji import OknoInwentaryzacji
        return self.jedno_okno(OknoInwentaryzacji)

    def kopia_zapasowa(self):
        """Kopia zapasowa (jedno okno)."""
        from gui.okno_kopii import OknoKopii
        return self.jedno_okno(OknoKopii)

    def o_programie(self) -> None:
        from gui.okna_info import OknoOProgramie
        OknoOProgramie(self).pokaz()

    def usun_zaznaczone(self) -> None:
        rodzaj, ident = rozbierz_iid(self.stan.zaznaczone)
        if rodzaj == "E":
            self.usun_egzemplarz(ident)
        elif rodzaj == "L":
            self.usun_lokalizacje(ident)

    def usun_egzemplarz(self, egz_id: int) -> None:
        blokujace, kaskadowe = zaleznosci(self.db, "egzemplarz", egz_id)
        czesci = blokujace.pop(("egzemplarz", "rodzic_id"), 0)
        if blokujace:
            messagebox.showwarning(t("okno.uwaga"), t("blad.usuwanie_zablokowane",
                                                      lista=opis(blokujace)), parent=self)
            return
        wiersz = egzemplarze.pobierz(self.db, egz_id)
        pytanie = t("pytanie.usun_egzemplarz", nazwa=egzemplarze.nazwa_wyswietlana(wiersz))
        if czesci:
            pytanie += "\n\n" + t("pytanie.usun_z_czesciami", liczba=czesci)
        if kaskadowe:
            pytanie += "\n\n" + t("pytanie.usun_tez", lista=opis(kaskadowe))
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            inwentarz.usun_egzemplarz(self.db, egz_id)
        except Exception as blad:   # noqa: BLE001 — każdy błąd trafia do użytkownika
            pokaz_blad(self, blad)
            return
        self.stan.zaznaczone = None
        self.odswiez()

    def usun_lokalizacje(self, lok_id: int) -> None:
        wiersz = lokalizacje.pobierz(self.db, lok_id)
        blokujace, _ = zaleznosci(self.db, "lokalizacja", lok_id)
        przenies = False
        if blokujace:
            cel = (lokalizacje.pobierz(self.db, wiersz["rodzic_id"])["nazwa"]
                   if wiersz["rodzic_id"] else t("lokalizacja.brak"))
            pytanie = t("pytanie.usun_lokalizacje_z_zawartoscia", nazwa=wiersz["nazwa"],
                        lista=opis(blokujace), cel=cel)
            przenies = True
        else:
            pytanie = t("pytanie.usun_lokalizacje", nazwa=wiersz["nazwa"])
        if not messagebox.askyesno(t("okno.potwierdzenie"), pytanie, parent=self):
            return
        try:
            inwentarz.usun_lokalizacje(self.db, lok_id, przenies_zawartosc=przenies)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.stan.zaznaczone = iid_lokalizacji(wiersz["rodzic_id"]) if wiersz["rodzic_id"] else None
        self.odswiez()

    def wydziel_z_partii(self, egz_id: int) -> None:
        try:
            nowy = inwentarz.wydziel_z_partii(self.db, egz_id)
        except Exception as blad:   # noqa: BLE001
            pokaz_blad(self, blad)
            return
        self.odswiez(zaznacz=iid_egzemplarza(nowy))
        self.edytuj_egzemplarz(nowy)
