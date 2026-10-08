# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy magazynu plików: kopiowanie, deduplikacja, miniatury, odpinanie, usuwanie."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria.szczegoly import cel_powiazania, zasoby_dziedziczone
from testy.test_uslugi import Kolekcja
from uslugi import inwentarz, pliki
from wyjatki import BladNornicy

try:
    from PIL import Image
    PILLOW = True
except ImportError:
    PILLOW = False


class TestPlikow(Kolekcja):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp / "dane")})
        straznik.start()
        self.addCleanup(straznik.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def zdjecie(self, nazwa="fota.JPG", kolor=(200, 30, 30), rozmiar=(800, 600)):
        sciezka = self.tmp / nazwa
        if PILLOW:
            Image.new("RGB", rozmiar, kolor).save(sciezka, format="JPEG")
        else:
            sciezka.write_bytes(os.urandom(2048))
        return sciezka

    def test_kopia_w_magazynie_pod_suma(self):
        zrodlo = self.zdjecie()
        z = pliki.dodaj_plik(self.db, zrodlo, {"egzemplarz_id": self.pc})
        wiersz = self.db.execute("SELECT * FROM zasob WHERE id = ?", (z,)).fetchone()
        suma, rozmiar = pliki.suma_pliku(zrodlo)
        self.assertEqual(f"{suma[:2]}/{suma}.jpg", wiersz["plik_sciezka"])
        self.assertEqual(("zdjecie", "fota", rozmiar), (wiersz["typ"], wiersz["tytul"], wiersz["plik_rozmiar"]))
        self.assertTrue(pliki.sciezka_pliku(self.db, wiersz["plik_sciezka"]).exists())
        zrodlo.unlink()            # oryginał można usunąć — kopia zostaje
        self.assertTrue(pliki.sciezka_pliku(self.db, wiersz["plik_sciezka"]).exists())

    @unittest.skipUnless(PILLOW, "brak Pillow")
    def test_miniatura_w_bazie(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie(rozmiar=(1200, 400)), {"egzemplarz_id": self.pc})
        import io
        miniatura = Image.open(io.BytesIO(self.db.execute(
            "SELECT miniatura FROM zasob WHERE id = ?", (z,)).fetchone()[0]))
        self.assertEqual((160, 53), miniatura.size)

    def test_ten_sam_plik_raz_na_dysku(self):
        zrodlo = self.zdjecie()
        kopia = self.tmp / "inna_nazwa.jpg"
        shutil.copy(zrodlo, kopia)
        a = pliki.dodaj_plik(self.db, zrodlo, {"egzemplarz_id": self.pc})
        b = pliki.dodaj_plik(self.db, kopia, {"egzemplarz_id": self.cpu})
        self.assertEqual(a, b)
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) FROM zasob_powiazanie WHERE zasob_id = ?",
                                            (a,)).fetchone()[0])
        pliki.dodaj_plik(self.db, zrodlo, {"egzemplarz_id": self.pc})   # powtórka: bez błędu
        self.assertEqual(1, len(list((self.tmp / "dane" / "pliki").rglob("*.jpg"))))

    def test_instrukcja_modelu_widoczna_w_egzemplarzu(self):
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat_czesci, "nazwa": "SB16"})
        e = self.nowy(model_id=m)
        pdf = self.tmp / "sb16.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        z = pliki.dodaj_plik(self.db, pdf, {"model_id": m}, typ="instrukcja")
        wiersz = zasoby_dziedziczone(self.db, e)[0]
        self.assertEqual((z, "model", {"model_id": m}), (wiersz["id"], wiersz["pochodzenie"],
                                                        cel_powiazania(wiersz)))

    def test_odpiecie_i_usuniecie_z_plikiem(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.pc})
        wzgledna = self.db.execute("SELECT plik_sciezka FROM zasob WHERE id = ?", (z,)).fetchone()[0]
        self.assertTrue(pliki.odepnij(self.db, z, {"egzemplarz_id": self.pc}))
        self.assertEqual(1, pliki.usun_sieroty_z_plikami(self.db, [z]))
        self.assertFalse(pliki.sciezka_pliku(self.db, wzgledna).exists())

    def test_odpiecie_wspolnego_nie_tworzy_sieroty(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.pc})
        pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.cpu})
        self.assertFalse(pliki.odepnij(self.db, z, {"egzemplarz_id": self.pc}))

    def test_odnosnik_i_notatka(self):
        pliki.dodaj_zasob(self.db, {"typ": "link", "tytul": "The Retro Web",
                                    "url": "https://theretroweb.com/"}, {"egzemplarz_id": self.pc})
        n = pliki.dodaj_zasob(self.db, {"typ": "notatka", "tytul": "Recap",
                                        "tresc": "C12 wymieniony"}, {"egzemplarz_id": self.pc})
        pliki.zapisz_zasob(self.db, n, {"typ": "notatka", "tytul": "Recap 2024", "tresc": "C12, C14"})
        self.assertEqual(("Recap 2024", "C12, C14"), tuple(self.db.execute(
            "SELECT tytul, tresc FROM zasob WHERE id = ?", (n,)).fetchone()))
        with self.assertRaises(BladNornicy):
            pliki.dodaj_zasob(self.db, {"typ": "notatka", "tytul": " "}, {"egzemplarz_id": self.pc})

    def test_brak_pliku(self):
        with self.assertRaises(BladNornicy) as k:
            pliki.dodaj_plik(self.db, self.tmp / "nie_ma.jpg", {"egzemplarz_id": self.pc})
        self.assertEqual("blad.brak_pliku", k.exception.klucz)

    def test_zdjecie_glowne(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.pc})
        self.assertIsNone(pliki.zdjecie_glowne(self.db, self.pc))          # domyślnie brak wyboru
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, z)
        self.assertEqual(z, pliki.zdjecie_glowne(self.db, self.pc)["id"])
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, None)
        self.assertIsNone(pliki.zdjecie_glowne(self.db, self.pc))

    def test_zdjecie_glowne_tylko_widoczne_zdjecie(self):
        obce = pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.cpu})
        notatka = pliki.dodaj_zasob(self.db, {"typ": "notatka", "tytul": "N", "tresc": "x"},
                                    {"egzemplarz_id": self.pc})
        for zasob in (obce, notatka):
            with self.assertRaises(BladNornicy) as k:
                pliki.ustaw_zdjecie_glowne(self.db, self.pc, zasob)
            self.assertEqual("blad.nie_zdjecie", k.exception.klucz)

    def test_zdjecie_modelu_jako_glowne_i_odpiecie(self):
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat_czesci, "nazwa": "SB16"})
        e = self.nowy(model_id=m)
        z = pliki.dodaj_plik(self.db, self.zdjecie(), {"model_id": m})
        pliki.ustaw_zdjecie_glowne(self.db, e, z)
        self.assertEqual(z, pliki.zdjecie_glowne(self.db, e)["id"])
        pliki.odepnij(self.db, z, {"model_id": m})
        self.assertIsNone(pliki.zdjecie_glowne(self.db, e))      # niewidoczne = nieobowiązujące

    def test_odpiecie_i_usuniecie_czyszcza_wybor(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie(), {"egzemplarz_id": self.pc})
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, z)
        pliki.odepnij(self.db, z, {"egzemplarz_id": self.pc})
        self.assertIsNone(self.db.execute("SELECT zdjecie_glowne_id FROM egzemplarz WHERE id = ?",
                                          (self.pc,)).fetchone()[0])
        z2 = pliki.dodaj_plik(self.db, self.zdjecie(kolor=(1, 2, 3)), {"egzemplarz_id": self.pc})
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, z2)
        self.db.execute("DELETE FROM zasob WHERE id = ?", (z2,))           # ON DELETE SET NULL
        self.assertIsNone(self.db.execute("SELECT zdjecie_glowne_id FROM egzemplarz WHERE id = ?",
                                          (self.pc,)).fetchone()[0])

    @unittest.skipUnless(PILLOW, "brak Pillow")
    def test_podglad_miesci_sie_w_ramce(self):
        import io
        z = pliki.dodaj_plik(self.db, self.zdjecie(rozmiar=(3000, 4000)), {"egzemplarz_id": self.pc})
        wiersz = self.db.execute("SELECT * FROM zasob WHERE id = ?", (z,)).fetchone()
        obraz = Image.open(io.BytesIO(pliki.podglad(self.db, wiersz, 280, 210)))
        szerokosc, wysokosc = obraz.size
        self.assertEqual(210, wysokosc)                       # pionowe zdjęcie: ogranicza wysokość
        self.assertAlmostEqual(3000 / 4000, szerokosc / wysokosc, delta=0.01)   # proporcje zachowane

    def test_magazyn_obok_pliku_bazy(self):
        plik_bazy = self.tmp / "inna" / "kolekcja.sqlite3"
        db = otworz_baze(plik_bazy)
        migruj(db)
        dane_startowe.wypelnij(db)
        self.assertEqual(plik_bazy.parent / "pliki", pliki.katalog_plikow(db))
        db.close()


if __name__ == "__main__":
    unittest.main()
