# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy: złącza z dziedziczeniem po modelu, historia testów i napraw,
informacje o modelu na karcie egzemplarza."""
import unittest
from unittest import mock

from baza.repozytoria import slowniki
from baza.repozytoria import zlacza as repo
from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from testy.test_uslugi import Kolekcja
from uslugi import inwentarz
from wyjatki import BladNornicy


def typ(db, kod):
    return db.execute("SELECT id FROM zlacze_typ WHERE kod = ?", (kod,)).fetchone()[0]


class TestZlaczyUslugi(Kolekcja):
    def test_roznice(self):
        model = {(1, "posiada"): 2, (2, "posiada"): 1}
        self.assertEqual({(1, "posiada"): 3, (2, "posiada"): 0, (3, "wymaga"): 1},
                         repo.roznice({(1, "posiada"): 3, (3, "wymaga"): 1}, model))
        self.assertEqual({}, repo.roznice(dict(model), model))

    def test_model_i_nadpisania_egzemplarza(self):
        joy, sio = typ(self.db, "db9_joystick"), typ(self.db, "sio_atari")
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat("komputery_fabryczne"),
                                             "nazwa": "65XE", "zlacza": {(joy, "posiada"): 1, (sio, "posiada"): 1}})
        self.assertEqual({(joy, "posiada"): 1, (sio, "posiada"): 1}, repo.modelu(self.db, m))
        # egzemplarz z dolutowanym drugim portem joysticka i bez SIO
        e = self.nowy(model_id=m, zlacza={(joy, "posiada"): 2})
        self.assertEqual({(joy, "posiada"): 2, (sio, "posiada"): 0}, repo.nadpisania_egzemplarza(self.db, e))
        # egzemplarz bez zmian nie ma nadpisań
        e2 = self.nowy(model_id=m, zlacza={(joy, "posiada"): 1, (sio, "posiada"): 1})
        self.assertEqual({}, repo.nadpisania_egzemplarza(self.db, e2))


class TestTypowZlaczyUslugi(Kolekcja):
    def test_dodanie_i_duplikat(self):
        typ_id = inwentarz.dodaj_typ_zlacza(self.db, "port", {"pl": "Zasilanie DIN-7", "en": ""})
        wiersz = self.db.execute("SELECT rodzaj, nazwy, kod FROM zlacze_typ WHERE id = ?", (typ_id,)).fetchone()
        self.assertEqual(("port", '{"pl": "Zasilanie DIN-7"}', None), tuple(wiersz))
        with self.assertRaises(BladNornicy) as k:
            inwentarz.dodaj_typ_zlacza(self.db, "port", {"en": "zasilanie din-7"})
        self.assertEqual("blad.duplikat", k.exception.klucz)
        # ta sama nazwa innego rodzaju jest dozwolona
        inwentarz.dodaj_typ_zlacza(self.db, "gniazdo", {"pl": "Zasilanie DIN-7"})

    def test_wymagana_nazwa(self):
        with self.assertRaises(BladNornicy) as k:
            inwentarz.dodaj_typ_zlacza(self.db, "port", {"pl": " ", "en": ""})
        self.assertEqual("blad.wymagana_nazwa", k.exception.klucz)

    def test_nazwa_jednojezyczna_w_obu_jezykach(self):
        from i18n.tlumacz import nazwa
        typ_id = inwentarz.dodaj_typ_zlacza(self.db, "slot", {"pl": "Złącze ECI"})
        nazwy = self.db.execute("SELECT nazwy FROM zlacze_typ WHERE id = ?", (typ_id,)).fetchone()[0]
        self.assertEqual("Złącze ECI", nazwa(nazwy, "en"))


class TestHistoriiUslugi(Kolekcja):
    def test_test_nieudany_zmienia_status(self):
        uszkodzony = slowniki.status_id(self.db, "uszkodzony")
        z = inwentarz.zapisz_zdarzenie(self.db, {"egzemplarz_id": self.pc, "typ": "test", "podtyp": "naprawa",
                                                 "data": "2026-09-30", "wynik": "blad"}, None, uszkodzony)
        wiersz = self.db.execute("SELECT typ, podtyp FROM zdarzenie WHERE id = ?", (z,)).fetchone()
        self.assertEqual(("test", None), tuple(wiersz))       # test nie ma podtypu
        self.assertEqual(uszkodzony, self.db.execute("SELECT status_id FROM egzemplarz WHERE id = ?",
                                                     (self.pc,)).fetchone()[0])

    def test_naprawa_domyslnie_naprawa_i_edycja(self):
        z = inwentarz.zapisz_zdarzenie(self.db, {"egzemplarz_id": self.pc, "typ": "naprawa",
                                                 "data": "2026-09-30", "opis": "Recap"})
        inwentarz.zapisz_zdarzenie(self.db, {"typ": "naprawa", "podtyp": "modyfikacja",
                                             "data": "2026-10-01", "opis": "Recap + mod"}, z)
        self.assertEqual(("modyfikacja", "2026-10-01"), tuple(self.db.execute(
            "SELECT podtyp, data FROM zdarzenie WHERE id = ?", (z,)).fetchone()))
        inwentarz.usun_zdarzenie(self.db, z)
        self.assertIsNone(self.db.execute("SELECT 1 FROM zdarzenie WHERE id = ?", (z,)).fetchone())

    def test_zla_data(self):
        with self.assertRaises(BladNornicy) as k:
            inwentarz.zapisz_zdarzenie(self.db, {"egzemplarz_id": self.pc, "typ": "test", "data": "30.09.2026"})
        self.assertEqual("blad.zla_data", k.exception.klucz)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestGuiZlaczyIHistorii(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.joy, self.sio, self.cart = (typ(self.db, k) for k in ("db9_joystick", "sio_atari", "c64_kartridz"))
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='komputery_fabryczne'").fetchone()[0]
        self.atari = inwentarz.zapisz_model(self.db, {
            "kategoria_id": kat, "producent": "Atari", "nazwa": "65XE", "rok_od": 1985, "rok_do": 1992,
            "opis": "Komputer 8-bit z 64 KB RAM.", "zrodlo_url": "https://example.org/65xe",
            "zlacza": {(self.joy, "posiada"): 2, (self.sio, "posiada"): 1}})
        self.egz = inwentarz.zapisz_egzemplarz(self.db, {"model_id": self.atari, "lokalizacja_id": self.regal,
                                                         "status_id": slowniki.status_id(self.db, "nietestowany")})

    def test_edycja_zlaczy_egzemplarza_przezywa_przebudowe(self):
        okno = self.okno.edytuj_egzemplarz(self.egz, zakladka=2)
        self.okno.update()
        self.assertEqual(2, okno._notatnik.index("current"))
        edytor = okno.zlacza
        self.assertEqual({(self.joy, "posiada"): 2, (self.sio, "posiada"): 1}, edytor.wynik())
        edytor.zaznaczony = (self.sio, "posiada")
        edytor.usun()                                   # wylutowane SIO
        edytor.nowy_typ.ustaw(self.cart)
        edytor.dodaj()                                  # dodany port (umownie)
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        wiersze = {okno.zlacza._lista.item(i, "values")[1]: okno.zlacza._lista.item(i, "values")[3]
                   for i in okno.zlacza._lista.get_children()}
        self.assertEqual("usunięte (model: 1)", wiersze["Atari SIO"])
        self.assertEqual(t("zlacza.dodane"), wiersze["Port kartridża C64"])
        okno.zapisz()
        self.assertEqual({(self.sio, "posiada"): 0, (self.cart, "posiada"): 1},
                         repo.nadpisania_egzemplarza(self.db, self.egz))

    def test_przywrocenie_z_modelu(self):
        okno = self.okno.edytuj_egzemplarz(self.egz, zakladka=2)
        okno.zlacza.zaznaczony = (self.joy, "posiada")
        okno.zlacza.zmien(-1)
        okno.zlacza.przywroc()
        okno.zapisz()
        self.assertEqual({}, repo.nadpisania_egzemplarza(self.db, self.egz))

    def test_zlacza_w_oknie_modelu_i_rozciagany_opis(self):
        okno = self.okno.edytuj_model(self.atari)
        self.okno.update()
        self.assertEqual(1, okno.opis.widzet.master.master.grid_rowconfigure(8)["weight"])
        okno.zlacza.zaznaczony = (self.joy, "posiada")
        okno.zlacza.zmien(-1)
        okno.zapisz()
        self.assertEqual({(self.joy, "posiada"): 1, (self.sio, "posiada"): 1}, repo.modelu(self.db, self.atari))

    def test_karta_pokazuje_opis_i_strone_modelu(self):
        self.okno.odswiez(zaznacz=f"E{self.egz}")
        teksty = [w.cget("text") for w in self.okno._widzety["szczegoly"].karty[0].winfo_children()
                  if w.winfo_class() == "TLabel"]
        import tkinter as tk
        karta = self.okno._widzety["szczegoly"].karty[0]
        pola_tekstu = [w for ramka in karta.winfo_children() for w in ramka.winfo_children()
                       if isinstance(w, tk.Text)]
        self.assertEqual("Komputer 8-bit z 64 KB RAM.", pola_tekstu[0].get("1.0", "end-1c"))
        self.assertEqual("disabled", str(pola_tekstu[0].cget("state")))
        wiersz_opisu = pola_tekstu[0].master.grid_info()["row"]
        self.assertEqual(1, karta.grid_rowconfigure(wiersz_opisu)["weight"])   # rośnie z oknem
        # wąski panel: pasek przewijania nie może zostać „zjedzony” przez pole tekstowe
        self.okno._widzety["podzial"].sashpos(0, 900)
        self.okno.update()
        # karta mogła zostać przebudowana — widżety szukamy od nowa, nie trzymamy starych
        karta = self.okno._widzety["szczegoly"].karty[0]
        ramka_opisu = next(r for r in karta.winfo_children()
                           if any(isinstance(w, tk.Text) for w in r.winfo_children()))
        pasek = next(w for w in ramka_opisu.winfo_children() if w.winfo_class() == "TScrollbar")
        self.assertGreater(pasek.winfo_width(), 5)
        self.assertLessEqual(pasek.winfo_rootx() + pasek.winfo_width(),
                             karta.winfo_rootx() + karta.winfo_width())
        self.assertIn("example.org/65xe", teksty)
        self.assertIn("1985–1992", teksty)

    def test_test_z_propozycja_statusu(self):
        panel = self.okno._widzety["szczegoly"]
        okno = panel.okno_zdarzenia(self.egz, typ="test")
        self.okno.update()
        self.assertEqual("disabled", str(okno._podtyp_widzet.cget("state")))
        okno.wynik.ustaw("ok")
        okno._zaproponuj_status()
        self.assertEqual(slowniki.status_id(self.db, "dziala"), okno.nowy_status.wartosc)
        okno.opis.widzet.insert("1.0", "Wszystkie testy OK, SIO działa")
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        okno.zapisz()
        self.assertEqual(("test", "ok"), tuple(self.db.execute(
            "SELECT typ, wynik FROM zdarzenie WHERE egzemplarz_id = ?", (self.egz,)).fetchone()))
        self.assertEqual(slowniki.status_id(self.db, "dziala"), self.db.execute(
            "SELECT status_id FROM egzemplarz WHERE id = ?", (self.egz,)).fetchone()[0])

    def test_usuniecie_wpisu_historii(self):
        z = inwentarz.zapisz_zdarzenie(self.db, {"egzemplarz_id": self.egz, "typ": "naprawa",
                                                 "data": "2026-09-01"})
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            self.okno._widzety["szczegoly"]._usun_zdarzenie(z)
        self.assertIsNone(self.db.execute("SELECT 1 FROM zdarzenie WHERE id = ?", (z,)).fetchone())

    def test_opis_nie_zostawia_wagi_dla_kolejnego_elementu(self):
        panel = self.okno._widzety["szczegoly"]
        self.okno.odswiez(zaznacz=f"E{self.egz}")
        panel.pokaz(f"E{self.karta}")            # egzemplarz bez modelu i bez opisu
        karta = panel.karty[0]
        self.assertTrue(all(karta.grid_rowconfigure(w)["weight"] == 0 for w in range(karta.grid_size()[1])))

    def test_wlasny_typ_zlacza_z_edytora(self):
        okno = self.okno.edytuj_egzemplarz(self.egz, zakladka=2)
        drugie = self.okno.edytuj_model(self.atari)          # drugi otwarty edytor złączy
        self.okno.update()
        okno.zlacza.nowy_typ_zlacza()
        self.okno.update()
        from gui.okno_typu_zlacza import OknoTypuZlacza
        dialog = next(d for d in self.okno._dialogi if isinstance(d, OknoTypuZlacza))
        dialog.rodzaj.ustaw("slot")
        dialog.nazwy["en"].set("Atari ECI")
        self.okno.przelacz_jezyk("pl")                 # przebudowa z otwartym oknem typu
        self.okno.update()
        dialog.zapisz()
        self.okno.update()
        nowy = self.db.execute("SELECT id FROM zlacze_typ WHERE nazwy LIKE '%Atari ECI%'").fetchone()[0]
        self.assertEqual(nowy, okno.zlacza.nowy_typ.wartosc)          # od razu wybrany
        self.assertIn("Slot: Atari ECI  (własny)", drugie.zlacza.nowy_typ.widzet.cget("values"))
        okno.zlacza.dodaj()
        okno.zapisz()
        self.assertEqual(1, repo.nadpisania_egzemplarza(self.db, self.egz)[(nowy, "posiada")])

    def test_poprawka_i_usuniecie_wlasnego_typu(self):
        okno = self.okno.edytuj_egzemplarz(self.egz, zakladka=2)
        self.okno.update()
        ed = okno.zlacza
        # wbudowany typ: przyciski edycji typu nieaktywne
        ed.nowy_typ.ustaw(self.joy)
        ed._odswiez_przyciski()
        self.assertEqual(["disabled", "disabled"], [str(p.cget("state")) for p in ed._przyciski_typu])
        # błędnie wpisany własny typ: poprawa nazwy
        bledny = inwentarz.dodaj_typ_zlacza(self.db, "port", {"pl": "Zasialnie DIN-7"})
        self.okno.odswiez()
        ed.nowy_typ.ustaw(bledny)
        ed._odswiez_przyciski()
        self.assertEqual(["normal", "normal"], [str(p.cget("state")) for p in ed._przyciski_typu])
        ed.edytuj_typ_zlacza()
        self.okno.update()
        from gui.okno_typu_zlacza import OknoTypuZlacza
        dialog = next(d for d in self.okno._dialogi if isinstance(d, OknoTypuZlacza))
        self.assertEqual("Zasialnie DIN-7", dialog.nazwy["pl"].get())
        dialog.nazwy["pl"].set("Zasilanie DIN-7")
        dialog.zapisz()
        self.okno.update()
        self.assertTrue(any("Zasilanie DIN-7" in w for w in ed.nowy_typ.widzet.cget("values")))
        # użyty w niezapisanym oknie: blokada z komunikatem
        ed.dodaj()
        with mock.patch("tkinter.messagebox.showwarning") as ostrzezenie:
            ed.usun_typ_zlacza()
        self.assertEqual(t("blad.typ_w_uzyciu_tutaj"), ostrzezenie.call_args[0][1])
        # po usunięciu złącza z listy: typ można usunąć
        ed.usun()
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            ed.usun_typ_zlacza()
        self.assertIsNone(self.db.execute("SELECT 1 FROM zlacze_typ WHERE id = ?", (bledny,)).fetchone())
        self.assertIsNone(ed.nowy_typ.wartosc)

    def test_typ_uzyty_w_bazie_chroniony(self):
        typ_id = inwentarz.dodaj_typ_zlacza(self.db, "slot", {"pl": "ECI"})
        inwentarz.zapisz_model(self.db, {"kategoria_id": self.db.execute(
            "SELECT id FROM kategoria WHERE kod='komputery_fabryczne'").fetchone()[0],
            "nazwa": "130XE", "zlacza": {(typ_id, "posiada"): 1}})
        with self.assertRaises(BladNornicy) as k:
            inwentarz.usun_typ_zlacza(self.db, typ_id)
        self.assertEqual("blad.usuwanie_zablokowane", k.exception.klucz)
        with self.assertRaises(BladNornicy) as k:
            inwentarz.usun_typ_zlacza(self.db, self.joy)
        self.assertEqual("blad.typ_wbudowany", k.exception.klucz)

    def test_wiersz_usuwany_klawiszem_delete(self):
        okno = self.okno.edytuj_egzemplarz(self.egz, zakladka=2)
        self.okno.update()
        ed = okno.zlacza
        self.assertEqual("disabled", str(ed._przyciski_wiersza[0].cget("state")))   # nic nie zaznaczono
        ed._lista.selection_set(f"{self.sio}|posiada")
        self.okno.update()
        self.assertEqual("normal", str(ed._przyciski_wiersza[0].cget("state")))
        ed._lista.focus_set()
        ed._lista.event_generate("<Delete>")
        self.okno.update()
        self.assertEqual(0, ed.wartosci[(self.sio, "posiada")])     # z modelu: oznaczone jako usunięte

    def test_skrot_adresu(self):
        from gui.szczegoly import skroc_adres
        self.assertEqual("www.mit.krakow.pl/…",
                         skroc_adres("https://www.mit.krakow.pl/zbior/mim-1726-vii-142-2/"))

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
