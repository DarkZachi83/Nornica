# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy usług inwentarza i modelu drzewa (bez ekranu)."""
import unittest

from baza.repozytoria import egzemplarze, slowniki
from gui.model_drzewa import WEZEL_BEZ_LOKALIZACJI, zbuduj_wezly
from testy.test_baza import BazaTestowa
from uslugi import inwentarz
from uslugi.formatowanie import minor_na_tekst, tekst_na_minor
from wyjatki import BladNornicy


class Kolekcja(BazaTestowa):
    """Mała kolekcja: regał z półką, na półce PC z płytą i procesorem."""

    def setUp(self):
        super().setUp()
        self.kat_skladaki = self.kat("skladaki_pc")
        self.kat_czesci = self.kat("plyty_glowne")
        self.st = slowniki.status_id(self.db, "dziala")
        self.regal = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Regał A", "typ": "regal"})
        self.polka = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Półka 2", "rodzic_id": self.regal})
        self.pc = self.nowy(nazwa_wlasna="DOS 486", kategoria_id=self.kat_skladaki,
                            lokalizacja_id=self.polka)
        self.plyta = self.nowy(nazwa_wlasna="Płyta VLB", rodzic_id=self.pc, pozycja_montazu="")
        self.cpu = self.nowy(nazwa_wlasna="486DX2-66", rodzic_id=self.plyta, pozycja_montazu="Socket 3")

    def kat(self, kod):
        return self.db.execute("SELECT id FROM kategoria WHERE kod = ?", (kod,)).fetchone()[0]

    def nowy(self, **dane):
        dane.setdefault("kategoria_id", self.kat_czesci)
        dane.setdefault("status_id", self.st)
        return inwentarz.zapisz_egzemplarz(self.db, dane)


class TestInwentarza(Kolekcja):
    def test_kody_nadawane_automatycznie(self):
        kody = [egzemplarze.pobierz(self.db, i)["kod_inwentarzowy"] for i in (self.pc, self.plyta, self.cpu)]
        self.assertEqual(["NOR-000001", "NOR-000002", "NOR-000003"], kody)
        self.assertEqual("LOC-0002", self.db.execute(
            "SELECT kod_etykiety FROM lokalizacja WHERE id = ?", (self.polka,)).fetchone()[0])

    def test_puste_pola_jako_null(self):
        self.assertIsNone(egzemplarze.pobierz(self.db, self.plyta)["pozycja_montazu"])

    def test_cykl_glebszy_niz_jeden_poziom(self):
        with self.assertRaises(BladNornicy) as k:
            inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "DOS 486", "kategoria_id": self.kat_skladaki,
                                                  "status_id": self.st, "rodzic_id": self.cpu}, self.pc)
        self.assertEqual("blad.cykl_montazu", k.exception.klucz)

    def test_wymagana_kategoria_bez_modelu(self):
        with self.assertRaises(BladNornicy) as k:
            inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "X", "status_id": self.st,
                                                  "kategoria_id": None})
        self.assertEqual("blad.wybierz_kategorie", k.exception.klucz)

    def test_model_zastepuje_kategorie(self):
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat_czesci, "producent": "Asus",
                                             "nazwa": "VL/I-486SV2GX4"})
        e = self.nowy(model_id=m, kategoria_id=self.kat_skladaki)
        wiersz = egzemplarze.pobierz(self.db, e)
        self.assertIsNone(wiersz["kategoria_id"])
        self.assertEqual(self.kat_czesci, wiersz["kat_id"])
        self.assertEqual("Asus", wiersz["producent"])

    def test_producent_tworzony_raz(self):
        for numer, nazwa in enumerate(("Creative", "creative")):
            inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat_czesci, "producent": nazwa,
                                             "nazwa": f"Sound Blaster {numer}"})
        self.assertEqual(1, len(slowniki.producenci(self.db)))

    def test_usuniecie_komputera_odklada_czesci(self):
        self.assertEqual(1, inwentarz.usun_egzemplarz(self.db, self.pc))
        plyta = egzemplarze.pobierz(self.db, self.plyta)
        self.assertIsNone(plyta["rodzic_id"])
        self.assertEqual(self.polka, plyta["lokalizacja_id"])
        self.assertEqual(self.plyta, egzemplarze.pobierz(self.db, self.cpu)["rodzic_id"])

    def test_wydzielenie_z_partii(self):
        partia = self.nowy(nazwa_wlasna="SIMM 4 MB", ilosc=10, lokalizacja_id=self.polka,
                           cena_minor=5000, waluta_kod="PLN")
        sztuka = inwentarz.wydziel_z_partii(self.db, partia)
        self.assertEqual(9, egzemplarze.pobierz(self.db, partia)["ilosc"])
        nowa = egzemplarze.pobierz(self.db, sztuka)
        self.assertEqual((1, self.polka, None), (nowa["ilosc"], nowa["lokalizacja_id"], nowa["cena_minor"]))
        self.assertNotEqual(nowa["kod_inwentarzowy"], egzemplarze.pobierz(self.db, partia)["kod_inwentarzowy"])
        with self.assertRaises(BladNornicy):
            inwentarz.wydziel_z_partii(self.db, sztuka)

    def test_usuniecie_lokalizacji_z_przeniesieniem(self):
        inwentarz.usun_lokalizacje(self.db, self.polka, przenies_zawartosc=True)
        self.assertEqual(self.regal, egzemplarze.pobierz(self.db, self.pc)["lokalizacja_id"])

    def test_cykl_lokalizacji(self):
        with self.assertRaises(BladNornicy):
            inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Regał A", "rodzic_id": self.polka}, self.regal)


class TestDrzewa(Kolekcja):
    def wezly(self, tryb, filtr=""):
        from baza.repozytoria import lokalizacje
        return zbuduj_wezly(lokalizacje.wszystkie(self.db), egzemplarze.lista(self.db), tryb, filtr, "pl")

    def test_lokalizacje_rodzic_przed_dzieckiem(self):
        wezly = self.wezly("lokalizacje")
        kolejnosc = [w.iid for w in wezly]
        self.assertEqual(["L1", "L2", f"E{self.pc}", f"E{self.plyta}", f"E{self.cpu}"], kolejnosc)
        rodzice = {w.iid: w.rodzic for w in wezly}
        self.assertEqual(f"E{self.plyta}", rodzice[f"E{self.cpu}"])

    def test_wezel_bez_lokalizacji(self):
        self.nowy(nazwa_wlasna="Joystick")
        self.assertIn(WEZEL_BEZ_LOKALIZACJI, [w.iid for w in self.wezly("lokalizacje")])

    def test_tryb_montazu_bez_lokalizacji(self):
        wezly = self.wezly("montaz")
        self.assertEqual({f"E{self.pc}", f"E{self.plyta}", f"E{self.cpu}"}, {w.iid for w in wezly})

    def test_filtr_pokazuje_przodkow(self):
        iid = {w.iid for w in self.wezly("lokalizacje", "dx2")}
        self.assertEqual({"L1", "L2", f"E{self.pc}", f"E{self.plyta}", f"E{self.cpu}"}, iid)
        self.assertEqual(set(), {w.iid for w in self.wezly("lokalizacje", "nie ma takiego")})

    def test_napisy_w_jezyku(self):
        wezel = next(w for w in self.wezly("lokalizacje") if w.iid == "L1")
        self.assertEqual("Regał", wezel.wartosci[2])


class TestSzablonow(BazaTestowa):
    def szablon(self, kod):
        import json
        return json.loads(self.db.execute("SELECT szablon_atrybutow FROM kategoria WHERE kod = ?",
                                          (kod,)).fetchone()[0])

    def test_taktowanie_za_procesorem(self):
        kody = [p["kod"] for p in self.szablon("komputery_fabryczne")]
        self.assertEqual(kody.index("procesor") + 1, kody.index("taktowanie_mhz"))

    def test_uzupelnienie_istniejacej_bazy(self):
        import json
        from baza import dane_startowe
        # baza sprzed zmiany: szablon bez taktowania, z polem dopisanym przez użytkownika
        stary = [p for p in self.szablon("komputery_fabryczne") if p["kod"] != "taktowanie_mhz"]
        stary.append({"kod": "moje_pole", "typ": "text", "nazwy": {"pl": "Moje pole"}})
        self.db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE kod = 'komputery_fabryczne'",
                        (json.dumps(stary),))
        dane_startowe.wypelnij(self.db)
        kody = [p["kod"] for p in self.szablon("komputery_fabryczne")]
        self.assertEqual(kody.index("procesor") + 1, kody.index("taktowanie_mhz"))
        self.assertEqual("moje_pole", kody[-1])
        self.assertEqual(0, dane_startowe.wypelnij(self.db))     # drugi przebieg niczego nie zmienia

    def test_scalanie_na_poczatku_gdy_brak_poprzednika(self):
        from baza.dane_startowe import scal_szablon
        wynik = scal_szablon([{"kod": "b"}], [{"kod": "a"}, {"kod": "b"}])
        self.assertEqual(["a", "b"], [p["kod"] for p in wynik])

    def test_taktowanie_w_formularzu(self):
        from gui.pola import FormularzAtrybutow
        import tkinter as tk
        try:
            korzen = tk.Tk()
        except tk.TclError:
            self.skipTest("brak ekranu")
        try:
            formularz = FormularzAtrybutow({})
            szablon = self.szablon("komputery_fabryczne")
            formularz.zbuduj(tk.Frame(korzen), szablon)
            formularz.pola["taktowanie_mhz"].set("7,09")
            self.assertEqual(7.09, formularz.zbierz(szablon)["taktowanie_mhz"])
        finally:
            korzen.destroy()


class TestFormatowania(unittest.TestCase):
    def test_kwoty(self):
        self.assertEqual(19999, tekst_na_minor("199,99", 2))
        self.assertEqual(19999, tekst_na_minor("199.99", 2))
        self.assertEqual(1500000, tekst_na_minor("1 500 000", 0))
        for zle in ("abc", "1.234", "-5"):
            with self.assertRaises(ValueError):
                tekst_na_minor(zle, 2)
        self.assertEqual("199,99", minor_na_tekst(19999, 2, "pl"))
        self.assertEqual("199.99", minor_na_tekst(19999, 2, "en"))

    def test_liczby_rzeczywiste(self):
        from uslugi.formatowanie import liczba_na_tekst
        self.assertEqual("7,09", liczba_na_tekst(7.09, "pl"))
        self.assertEqual("7.09", liczba_na_tekst(7.09, "en"))
        self.assertEqual("33", liczba_na_tekst(33.0, "pl"))


if __name__ == "__main__":
    unittest.main()
