# SPDX-License-Identifier: GPL-3.0-or-later
"""Kopia zapasowa ZIP: tworzenie, sprawdzanie i przywracanie (uslugi/archiwum.py)."""
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki, ustawienia
from uslugi import archiwum, inwentarz, pliki
from wyjatki import BladNornicy


class TestArchiwum(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.db = self.nowa_baza("dane")
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='skladaki_pc'").fetchone()[0]
        self.regal = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Regał", "typ": "regal"})
        self.pc = inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "DOS 486", "kategoria_id": kat,
                                                         "status_id": slowniki.status_id(self.db, "dziala"),
                                                         "lokalizacja_id": self.regal})
        (self.tmp / "bios.bin").write_bytes(b"\x55\xaa" * 5000)
        from PIL import Image
        Image.new("RGB", (40, 30), (200, 30, 30)).save(self.tmp / "foto.jpg")
        self.bios = pliki.dodaj_plik(self.db, self.tmp / "bios.bin", {"egzemplarz_id": self.pc}, typ="bios")
        self.foto = pliki.dodaj_plik(self.db, self.tmp / "foto.jpg", {"egzemplarz_id": self.pc})
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, self.foto)

    def nowa_baza(self, nazwa):
        sciezka = self.tmp / nazwa / "nornica.sqlite3"
        db = otworz_baze(sciezka)
        self.addCleanup(db.close)
        migruj(db)
        dane_startowe.wypelnij(db)
        return db

    def sciezka_zasobu(self, db, zasob_id):
        return pliki.sciezka_pliku(db, db.execute("SELECT plik_sciezka FROM zasob WHERE id = ?",
                                                  (zasob_id,)).fetchone()[0])

    def kopia(self, nazwa="kopia.zip"):
        cel = self.tmp / "pendrive" / nazwa
        return cel, archiwum.utworz_kopie(self.db, cel)

    # ------------------------------------------------------------ tworzenie
    def test_kopia_zawiera_baze_pliki_i_manifest(self):
        postep = []
        cel = self.tmp / "pendrive" / "k.zip"
        manifest = archiwum.zapisz(archiwum.migawka(self.db), cel, lambda z, w: postep.append((z, w)))
        with zipfile.ZipFile(cel) as z:
            nazwy = set(z.namelist())
            zapisany = json.loads(z.read("manifest.json"))
            foto = next(i for i in z.infolist() if i.filename.endswith(".jpg"))
            bios = next(i for i in z.infolist() if i.filename.endswith(".bin"))
        self.assertEqual(manifest, zapisany)
        self.assertEqual(4, len(nazwy))                                  # manifest, baza, 2 pliki
        self.assertEqual({"egzemplarze": 1, "lokalizacje": 1, "modele": 0, "zasoby": 2, "pliki": 2},
                         manifest["liczby"])
        self.assertEqual(zipfile.ZIP_STORED, foto.compress_type)         # JPEG już skompresowany
        self.assertEqual(zipfile.ZIP_DEFLATED, bios.compress_type)
        self.assertEqual(postep[-1][0], postep[-1][1])                   # postęp dochodzi do 100%
        self.assertEqual([], [p for p in (self.tmp / "pendrive").iterdir() if p.name != "k.zip"])

    def test_zapamietuje_date_i_folder(self):
        cel, manifest = self.kopia()
        self.assertEqual(manifest["utworzono"], ustawienia.pobierz(self.db, "kopia_ostatnia"))
        self.assertEqual(str(cel.parent.resolve()), ustawienia.pobierz(self.db, "kopia_folder"))

    def test_brakujacy_plik_odnotowany_kopia_powstaje(self):
        self.sciezka_zasobu(self.db, self.bios).unlink()
        _, manifest = self.kopia()
        self.assertEqual(1, manifest["liczby"]["pliki"])
        self.assertEqual(1, len(manifest["brakujace_pliki"]))

    def test_nieudane_pakowanie_nie_zostawia_pliku(self):
        cel = self.tmp / "pendrive" / "k.zip"
        with mock.patch.object(archiwum, "_dopisz", side_effect=OSError("brak miejsca")):
            with self.assertRaises(OSError):
                archiwum.zapisz(archiwum.migawka(self.db), cel)
        self.assertEqual([], list((self.tmp / "pendrive").iterdir()))

    # ------------------------------------------------------------ przywracanie
    def test_przywrocenie_na_nowym_dysku(self):
        """Padł dysk: nowa, pusta instalacja + kopia z pendrive'a = pełna kolekcja."""
        cel, _ = self.kopia()
        nowa = self.nowa_baza("nowy_dysk")
        wynik = archiwum.przywroc(nowa, cel, self.tmp / "nowy_dysk" / "kopie")
        self.assertEqual(2, wynik["dodane_pliki"])
        self.assertTrue(wynik["kopia_bezpieczenstwa"].is_file())
        self.assertEqual("DOS 486", nowa.execute("SELECT nazwa_wlasna FROM egzemplarz").fetchone()[0])
        self.assertEqual(self.foto, nowa.execute("SELECT zdjecie_glowne_id FROM egzemplarz").fetchone()[0])
        for zasob in (self.bios, self.foto):
            self.assertEqual(self.sciezka_zasobu(self.db, zasob).read_bytes(),
                             self.sciezka_zasobu(nowa, zasob).read_bytes())
        self.assertEqual("ok", nowa.execute("PRAGMA integrity_check").fetchone()[0])
        self.assertEqual([], nowa.execute("PRAGMA foreign_key_check").fetchall())

    def test_przywrocenie_cofa_zmiany_i_zostawia_kopie_bezpieczenstwa(self):
        cel, _ = self.kopia()
        inwentarz.usun_egzemplarz(self.db, self.pc)                     # „pomyłka” po kopii
        wynik = archiwum.przywroc(self.db, cel, self.tmp / "dane" / "kopie")
        self.assertEqual(0, wynik["dodane_pliki"])                       # pliki już są
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])
        import sqlite3
        przed = sqlite3.connect(wynik["kopia_bezpieczenstwa"])
        self.assertEqual(0, przed.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])
        przed.close()

    def test_obcy_zip_odrzucony(self):
        obcy = self.tmp / "zdjecia.zip"
        with zipfile.ZipFile(obcy, "w") as z:
            z.writestr("wakacje.jpg", b"x")
        (self.tmp / "nie_zip.zip").write_bytes(b"to nie jest zip")
        for plik in (obcy, self.tmp / "nie_zip.zip", self.tmp / "nie_ma.zip"):
            with self.assertRaises(BladNornicy) as blad:
                archiwum.przywroc(self.db, plik, self.tmp / "kopie")
            self.assertEqual("blad.kopia_nieprawidlowa", blad.exception.klucz)
        self.assertFalse((self.tmp / "kopie").exists())                  # nic nie ruszone

    def _przepakuj(self, cel, zmien):
        """Kopia z podmienioną zawartością (uszkodzenie, sfałszowany manifest)."""
        with zipfile.ZipFile(cel) as z:
            wpisy = {n: z.read(n) for n in z.namelist()}
        zmien(wpisy)
        with zipfile.ZipFile(cel, "w") as z:
            for nazwa, dane in wpisy.items():
                z.writestr(nazwa, dane)

    def test_uszkodzona_baza_w_kopii_odrzucona(self):
        cel, _ = self.kopia()
        self._przepakuj(cel, lambda w: w.update({"nornica.sqlite3": w["nornica.sqlite3"][:-100] + b"\0" * 100}))
        with self.assertRaises(BladNornicy) as blad:
            archiwum.przywroc(self.db, cel, self.tmp / "kopie")
        self.assertEqual("blad.kopia_uszkodzona", blad.exception.klucz)
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])

    def test_kopia_z_nowszej_wersji_programu_odrzucona(self):
        cel, _ = self.kopia()

        def nowsza(w):
            m = json.loads(w["manifest.json"])
            m["wersja_schematu"] = 999
            w["manifest.json"] = json.dumps(m).encode()
        self._przepakuj(cel, nowsza)
        with self.assertRaises(BladNornicy) as blad:
            archiwum.przywroc(self.db, cel, self.tmp / "kopie")
        self.assertEqual("blad.kopia_nowsza", blad.exception.klucz)

    def test_sciezki_poza_folderem_odrzucone(self):
        cel, _ = self.kopia()

        def zlosliwa(w):
            m = json.loads(w["manifest.json"])
            m["sumy_sha256"]["pliki/../../poza.txt"] = "0" * 64
            w["manifest.json"] = json.dumps(m).encode()
            w["pliki/../../poza.txt"] = b"x"
        self._przepakuj(cel, zlosliwa)
        with self.assertRaises(BladNornicy):
            archiwum.przywroc(self.db, cel, self.tmp / "kopie")
        self.assertFalse((self.tmp / "poza.txt").exists())
        for sciezka in ("a/../b", "/etc/passwd", "C:\\x", "..", "a//b", ""):
            self.assertFalse(archiwum._bezpieczna(sciezka), sciezka)
        self.assertTrue(archiwum._bezpieczna("3f/3fa9.jpg"))

    def test_zly_plik_w_kopii_nie_trafia_do_magazynu(self):
        cel, manifest = self.kopia()
        nazwa = next(n for n in manifest["sumy_sha256"] if n.endswith(".bin"))
        self._przepakuj(cel, lambda w: w.update({nazwa: b"podmieniony"}))
        nowa = self.nowa_baza("nowy_dysk")
        with self.assertRaises(BladNornicy):
            archiwum.przywroc(nowa, cel, self.tmp / "kopie")
        self.assertEqual(0, nowa.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])
        magazyn = pliki.katalog_plikow(nowa)
        self.assertFalse(any(p.suffix == ".bin" for p in magazyn.rglob("*")) if magazyn.exists() else False)


if __name__ == "__main__":
    unittest.main()


from testy import test_gui   # noqa: E402 — moduł, nie klasa: inaczej jej testy uruchomiłyby się drugi raz


@unittest.skipUnless(test_gui.EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOknaKopii(test_gui.TestPrzebudowy):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp / "dane")})
        straznik.start()
        self.addCleanup(straznik.stop)
        super().setUp()

    def czekaj(self, okno):
        import time
        koniec = time.time() + 10
        while okno.pracuje and time.time() < koniec:
            self.okno.update()
            time.sleep(0.02)
        self.assertFalse(okno.pracuje)

    def test_kopia_i_przywrocenie_z_okna(self):
        from i18n.tlumacz import t
        okno = self.okno.kopia_zapasowa()
        self.assertIs(okno, self.okno.kopia_zapasowa())
        cel = self.tmp / "pendrive" / "kopia.zip"
        okno.utworz(str(cel))
        self.okno.przelacz_jezyk("pl")                 # zmiana języka w trakcie pakowania
        self.czekaj(okno)
        self.okno.update()
        self.assertTrue(cel.is_file())
        self.assertEqual(100.0, okno.postep)
        self.assertTrue(okno._stan.cget("text").startswith(t("kopia.gotowa", plik="", rozmiar="")[:15]))
        self.assertIsNotNone(ustawienia.pobierz(self.db, "kopia_ostatnia"))

        inwentarz.usun_egzemplarz(self.db, self.karta)
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as pytanie:
            okno.przywroc(str(cel))
        self.assertIn("2", pytanie.call_args[0][1])     # liczba egzemplarzy w pytaniu
        self.okno.update()
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])
        self.assertTrue(self.drzewo().exists(f"E{self.karta}"))
        self.assertIn(str(self.tmp / "dane" / "kopie"), okno._stan.cget("text"))

    def test_odmowa_nie_zmienia_niczego(self):
        okno = self.okno.kopia_zapasowa()
        cel = self.tmp / "kopia.zip"
        okno.utworz(str(cel))
        self.czekaj(okno)
        inwentarz.usun_egzemplarz(self.db, self.karta)
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            okno.przywroc(str(cel))
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])

    def test_zly_plik_pokazuje_blad(self):
        okno = self.okno.kopia_zapasowa()
        zly = self.tmp / "zly.zip"
        zly.write_bytes(b"nie zip")
        with mock.patch("tkinter.messagebox.showerror") as blad:
            okno.przywroc(str(zly))
        self.assertEqual(1, blad.call_count)
        self.assertFalse(okno.pracuje)
