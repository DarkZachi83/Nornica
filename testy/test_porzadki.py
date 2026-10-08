# SPDX-License-Identifier: GPL-3.0-or-later
"""Porządki w kolekcji: wykrywanie i bezpieczne usuwanie (uslugi/porzadki.py)."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki
from uslugi import inwentarz, pliki, porzadki

STARY = time.time() + porzadki.WIEK_PLIKU_BEZ_WPISU + 60    # „teraz” w przyszłości: pliki są stare


class TestPorzadkow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp / "dane")})
        straznik.start()
        self.addCleanup(straznik.stop)
        self.db = otworz_baze(str(self.tmp / "kolekcja.db"))
        self.addCleanup(self.db.close)
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        self.kat = self.db.execute("SELECT id FROM kategoria WHERE kod='skladaki_pc'").fetchone()[0]
        self.kat_plyty = self.db.execute("SELECT id FROM kategoria WHERE kod='plyty_glowne'").fetchone()[0]
        self.st = slowniki.status_id(self.db, "dziala")
        self.regal = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Regał", "typ": "regal"})
        self.polka = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Półka", "rodzic_id": self.regal})

    def egz(self, **dane) -> int:
        return inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "X", "kategoria_id": self.kat,
                                                     "status_id": self.st, **dane})

    def plik(self, nazwa: str, tresc: bytes = b"abc") -> Path:
        sciezka = self.tmp / nazwa
        sciezka.write_bytes(tresc)
        return sciezka

    def kody(self, kod):
        return [porzadki.klucz_pozycji(kod, p) for p in porzadki.znajdz(self.db, kod)]

    # ------------------------------------------------------------ wyszukiwanie
    def test_czysta_baza_bez_problemow_poza_pusta_polka(self):
        self.egz(lokalizacja_id=self.polka)
        wyniki = porzadki.przeglad(self.db)
        self.assertEqual(set(wyniki), {k.kod for k in porzadki.KONTROLE})
        self.assertEqual({k: [] for k in wyniki if k != "nieuzywane_modele"},
                         {k: v for k, v in wyniki.items() if k != "nieuzywane_modele"})

    def test_puste_lokalizacje_tylko_liscie(self):
        self.assertEqual([self.polka], self.kody("puste_lokalizacje"))     # regał ma półkę
        self.egz(lokalizacja_id=self.polka)
        self.assertEqual([], self.kody("puste_lokalizacje"))

    def test_bez_lokalizacji_pomija_zamontowane(self):
        luzem = self.egz()
        pc = self.egz(lokalizacja_id=self.polka)
        self.egz(rodzic_id=pc)
        self.assertEqual([luzem], self.kody("bez_lokalizacji"))

    def test_powtorzone_numery_bez_wielkosci_liter_i_spacji(self):
        a = self.egz(lokalizacja_id=self.polka, numer_seryjny="AB123")
        b = self.egz(lokalizacja_id=self.polka, numer_seryjny=" ab123 ")
        self.egz(lokalizacja_id=self.polka, numer_seryjny="XY1")
        self.egz(lokalizacja_id=self.polka, numer_seryjny="")
        self.egz(lokalizacja_id=self.polka)
        self.assertEqual({a, b}, set(self.kody("powtorzone_numery")))

    def test_nieuzywane_modele_i_producenci(self):
        uzywany = inwentarz.zapisz_model(self.db, {"nazwa": "4DPS", "producent": "Zida",
                                                   "kategoria_id": self.kat_plyty})
        wolny = inwentarz.zapisz_model(self.db, {"nazwa": "P5A", "producent": "Asus",
                                                 "kategoria_id": self.kat_plyty})
        self.db.execute("INSERT INTO producent (nazwa) VALUES ('Nikt')")
        self.egz(model_id=uzywany, nazwa_wlasna=None, kategoria_id=None, lokalizacja_id=self.polka)
        self.assertEqual([wolny], self.kody("nieuzywane_modele"))
        self.assertEqual(["Nikt"], [p["nazwa"] for p in porzadki.znajdz(self.db, "nieuzywani_producenci")])

    # ------------------------------------------------------------ pliki
    def test_pliki_bez_wpisu_i_brakujace(self):
        pc = self.egz(lokalizacja_id=self.polka)
        z1 = pliki.dodaj_plik(self.db, self.plik("a.txt", b"jeden"), {"egzemplarz_id": pc})
        z2 = pliki.dodaj_plik(self.db, self.plik("b.txt", b"dwa"), {"egzemplarz_id": pc})
        katalog = pliki.katalog_plikow(self.db)
        obcy = katalog / "zz" / "obcy.bin"
        obcy.parent.mkdir(parents=True)
        obcy.write_bytes(b"x" * 10)
        sciezka2 = self.db.execute("SELECT plik_sciezka FROM zasob WHERE id = ?", (z2,)).fetchone()[0]
        pliki.sciezka_pliku(self.db, sciezka2).unlink()

        self.assertEqual([], porzadki.pliki_bez_wpisu(self.db))            # świeży — może być dodawany
        bez = porzadki.pliki_bez_wpisu(self.db, teraz=STARY)
        self.assertEqual([("zz/obcy.bin", 10)], [(p["sciezka"], p["rozmiar"]) for p in bez])
        brak = porzadki.brakujace_pliki(self.db)
        self.assertEqual([(z2, pc)], [(p["id"], p["egzemplarz_id"]) for p in brak])
        self.assertNotIn(z1, [p["id"] for p in brak])

    def test_usuwanie_pliku_bez_wpisu_sprawdza_ponownie(self):
        katalog = pliki.katalog_plikow(self.db)
        (katalog / "zz").mkdir(parents=True)
        (katalog / "zz" / "obcy.bin").write_bytes(b"x")
        (katalog / "yy").mkdir()
        (katalog / "yy" / "drugi.bin").write_bytes(b"y")
        poza = self.tmp / "poza.txt"
        poza.write_bytes(b"nie ruszac")
        # w międzyczasie „drugi.bin” dostał wpis w bazie
        self.db.execute("INSERT INTO zasob (typ, tytul, plik_sciezka) VALUES ('notatka', 'd', 'yy/drugi.bin')")
        usuniete = porzadki.usun_pliki_bez_wpisu(
            self.db, ["zz/obcy.bin", "yy/drugi.bin", "../poza.txt", "../../poza.txt"], teraz=STARY)
        self.assertEqual(1, usuniete)
        self.assertFalse((katalog / "zz").exists())                 # pusty podfolder sprzątnięty
        self.assertTrue((katalog / "yy" / "drugi.bin").exists())
        self.assertTrue(poza.exists())

    def test_usuwanie_wpisow_brakujacych_plikow(self):
        pc = self.egz(lokalizacja_id=self.polka)
        from PIL import Image
        Image.new("RGB", (20, 20), (200, 30, 30)).save(self.tmp / "a.png")
        z = pliki.dodaj_plik(self.db, self.tmp / "a.png", {"egzemplarz_id": pc})
        pliki.ustaw_zdjecie_glowne(self.db, pc, z)
        sciezka = pliki.sciezka_pliku(self.db, self.db.execute(
            "SELECT plik_sciezka FROM zasob WHERE id = ?", (z,)).fetchone()[0])
        self.assertEqual(0, porzadki.usun(self.db, "brakujace_pliki", [z]))     # plik jest — zostaje
        sciezka.unlink()
        self.assertEqual(1, porzadki.usun(self.db, "brakujace_pliki", [z]))
        self.assertIsNone(self.db.execute("SELECT zdjecie_glowne_id FROM egzemplarz WHERE id = ?",
                                          (pc,)).fetchone()[0])

    def test_usuwanie_sierot_razem_z_plikiem(self):
        pc = self.egz(lokalizacja_id=self.polka)
        z = pliki.dodaj_plik(self.db, self.plik("a.txt", b"jeden"), {"egzemplarz_id": pc})
        sciezka = pliki.sciezka_pliku(self.db, self.db.execute(
            "SELECT plik_sciezka FROM zasob WHERE id = ?", (z,)).fetchone()[0])
        self.assertEqual([], self.kody("zasoby_sieroty"))
        pliki.odepnij(self.db, z, {"egzemplarz_id": pc})
        self.assertEqual([z], self.kody("zasoby_sieroty"))
        self.assertEqual(1, porzadki.usun(self.db, "zasoby_sieroty", [z]))
        self.assertFalse(sciezka.exists())

    # ------------------------------------------------------------ usuwanie rekordów
    def test_usuwanie_lokalizacji_tylko_pustych(self):
        self.assertEqual(0, porzadki.usun(self.db, "puste_lokalizacje", [self.regal]))
        self.egz(lokalizacja_id=self.polka)                # półka przestała być pusta
        self.assertEqual(0, porzadki.usun(self.db, "puste_lokalizacje", [self.polka]))
        inna = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Pudło"})
        self.assertEqual(1, porzadki.usun(self.db, "puste_lokalizacje", [inna, self.regal]))
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) FROM lokalizacja").fetchone()[0])

    def test_usuwanie_modelu_zostawia_dokumenty_jako_sieroty(self):
        m = inwentarz.zapisz_model(self.db, {"nazwa": "P5A", "producent": "Asus", "kategoria_id": self.kat_plyty})
        z = pliki.dodaj_plik(self.db, self.plik("bios.bin", b"bios"), {"model_id": m})
        self.assertEqual(1, porzadki.usun(self.db, "nieuzywane_modele", [m]))
        self.assertEqual([z], self.kody("zasoby_sieroty"))
        self.assertEqual(["Asus"], [p["nazwa"] for p in porzadki.znajdz(self.db, "nieuzywani_producenci")])
        self.assertEqual(1, porzadki.usun(self.db, "nieuzywani_producenci",
                                          [p["id"] for p in porzadki.znajdz(self.db, "nieuzywani_producenci")]))

    def test_model_z_egzemplarzem_nie_jest_usuwany(self):
        m = inwentarz.zapisz_model(self.db, {"nazwa": "P5A", "producent": "Asus", "kategoria_id": self.kat_plyty})
        self.egz(model_id=m, nazwa_wlasna=None, kategoria_id=None)
        self.assertEqual(0, porzadki.usun(self.db, "nieuzywane_modele", [m]))
        p = self.db.execute("SELECT id FROM producent WHERE nazwa = 'Asus'").fetchone()[0]
        self.assertEqual(0, porzadki.usun(self.db, "nieuzywani_producenci", [p]))

    def test_kontrole_tylko_do_sprawdzenia_nie_usuwaja(self):
        with self.assertRaises(ValueError):
            porzadki.usun(self.db, "bez_lokalizacji", [1])


if __name__ == "__main__":
    unittest.main()


from testy import test_gui   # noqa: E402 — moduł, nie klasa: inaczej jej testy uruchomiłyby się drugi raz


@unittest.skipUnless(test_gui.EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOknaPorzadkow(test_gui.TestPrzebudowy):
    def test_okno_przezywa_zmiane_jezyka_i_usuwa(self):
        from i18n.tlumacz import t
        pusta = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Pudło 9", "typ": "pudelko"})
        okno = self.okno.porzadki()
        self.assertIs(okno, self.okno.porzadki())                 # jedno okno
        okno.kod = "puste_lokalizacje"
        okno._pokaz_kontrole()
        self.assertEqual([str(pusta)], list(okno._pozycje.get_children()))
        self.assertIn("(1)", okno._kontrole.item("puste_lokalizacje", "text"))
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertEqual("puste_lokalizacje", okno.kod)
        self.assertEqual(t("kolumna.kod"), okno._pozycje.heading("kod", "text"))
        self.assertEqual("Pudełko", okno._pozycje.item(str(pusta), "values")[2])
        okno._pozycje.selection_set(str(pusta))
        okno.update()
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            okno.usun_zaznaczone()
        self.okno.update()
        self.assertIsNone(self.db.execute("SELECT 1 FROM lokalizacja WHERE id = ?", (pusta,)).fetchone())
        self.assertEqual([], list(okno._pozycje.get_children()))
        self.assertEqual(t("porzadki.usunieto", liczba=1), okno._stan.cget("text"))

    def test_pokaz_zaznacza_egzemplarz_w_oknie_glownym(self):
        luzem = inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "Amiga", "kategoria_id": self.kat_skladaki,
                                                      "status_id": slowniki.status_id(self.db, "dziala")})
        self.okno.odswiez()
        okno = self.okno.porzadki()
        okno._kontrole.selection_set("bez_lokalizacji")
        okno.update()
        self.assertEqual("bez_lokalizacji", okno.kod)
        self.assertEqual("", okno._przyciski["usun"].winfo_manager())   # tu nic się nie usuwa
        okno._pozycje.selection_set(str(luzem))
        okno.update()
        okno.pokaz_pozycje()
        self.assertEqual((f"E{luzem}",), self.drzewo().selection())
