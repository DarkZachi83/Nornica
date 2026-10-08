# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy interfejsu: lokalizacje w otwartym formularzu, zdjęcia na karcie egzemplarza."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from testy.test_gui import EKRAN, TestPrzebudowy
from uslugi import inwentarz, pliki


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestLokalizacjiIZasobow(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp)})
        straznik.start()
        self.addCleanup(straznik.stop)
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_lokalizacja_dodana_gdzie_indziej_pojawia_sie_w_formularzu(self):
        okno = self.okno.nowy_egzemplarz()
        nowa = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Pudełko #12"})
        self.okno.odswiez()
        self.assertIn("Pudełko #12", okno.lokalizacja.widzet.cget("values"))

    def test_nowa_lokalizacja_z_formularza(self):
        okno = self.okno.nowy_egzemplarz()
        okno.lokalizacja.ustaw(self.polka)
        okno._nowa_lokalizacja()
        self.okno.update()
        from gui.okno_lokalizacji import OknoLokalizacji
        lok = next(d for d in self.okno._dialogi if isinstance(d, OknoLokalizacji))
        self.assertEqual(self.polka, lok.rodzic.wartosc)       # domyślnie wewnątrz wybranej
        lok.nazwa.set("Pudełko #3")
        lok.zapisz()
        self.okno.update()
        nowa = self.db.execute("SELECT id FROM lokalizacja WHERE nazwa = 'Pudełko #3'").fetchone()[0]
        self.assertEqual(nowa, okno.lokalizacja.wartosc)
        self.assertIn("Pudełko #3", okno.lokalizacja.widzet.get())

    def test_zdjecia_na_karcie(self):
        from PIL import Image
        sciezki = []
        for i, kolor in enumerate(((200, 0, 0), (0, 150, 0), (0, 0, 200))):
            sciezka = self.tmp / f"zdj{i}.jpg"
            Image.new("RGB", (640, 480), kolor).save(sciezka)
            sciezki.append(str(sciezka))
        panel = self.okno._widzety["szczegoly"]
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        panel.dodaj_pliki_zdjec(self.pc, sciezki)
        self.okno.update()
        miniatury = [o for o in panel._miniatury if o.width() <= 80]     # pasek; bez ramki zdjęcia głównego
        self.assertEqual(3, len(miniatury))
        self.assertEqual(80, miniatury[0].width())
        # przebudowa po zmianie języka odtwarza miniatury
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.okno._widzety["szczegoly"].pokaz(f"E{self.pc}", 3)
        self.assertEqual(3, len([o for o in self.okno._widzety["szczegoly"]._miniatury if o.width() <= 80]))

    def plotna(self):
        import tkinter as tk
        gora = self.okno._widzety["szczegoly"].gora
        return [w for w in gora.winfo_children() if isinstance(w, tk.Canvas)]

    def napis_braku(self):
        plotno = self.plotna()[0]
        elementy = plotno.find_withtag("napis_braku")
        return plotno.itemcget(elementy[0], "text") if elementy else None

    def test_brak_zdjecia_w_jezyku_interfejsu(self):
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        self.okno.update()
        self.assertEqual("NO IMAGE", self.napis_braku())
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertEqual("BRAK ZDJĘCIA", self.napis_braku())

    def test_wybor_zdjecia_glownego_polem_w_zasobach(self):
        from PIL import Image
        sciezki = []
        for i, rozmiar in enumerate(((1600, 1200), (800, 1200))):
            sciezka = self.tmp / f"z{i}.jpg"
            Image.new("RGB", rozmiar, (40 * i, 90, 160)).save(sciezka)
            sciezki.append(str(sciezka))
        panel = self.okno._widzety["szczegoly"]
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        panel.dodaj_pliki_zdjec(self.pc, sciezki)
        self.okno.update()
        panel = self.okno._widzety["szczegoly"]
        self.assertEqual([0, 0], [v.get() for v in panel._wybor_glownego])
        drugie = pliki.zdjecia_egzemplarza(self.db, self.pc)[1]["id"]
        panel._wybor_glownego[1].set(1)
        panel.ustaw_glowne(self.pc, drugie)               # to, co robi kliknięcie pola
        self.okno.update()
        panel = self.okno._widzety["szczegoly"]
        self.assertEqual(drugie, panel.zdjecie_na_karcie)
        self.assertIsNone(self.napis_braku())
        zdjecie = panel._miniatury[0]                       # pierwszy obraz = zdjęcie główne
        self.assertLessEqual((zdjecie.width(), zdjecie.height()), (280, 210))
        self.assertEqual([0, 1], [v.get() for v in panel._wybor_glownego])
        panel.ustaw_glowne(self.pc, None)                   # odznaczenie
        self.okno.update()
        self.assertEqual("NO IMAGE", self.napis_braku())

    def test_ramka_zdjecia_skaluje_sie_z_karta(self):
        panel = self.okno._widzety["szczegoly"]
        self.assertEqual((280, 210), panel._rozmiar_zdjecia(900))      # szeroki panel: pełny rozmiar
        maly = panel._rozmiar_zdjecia(560)
        self.assertLess(maly[0], 280)
        self.assertAlmostEqual(280 / 210, maly[0] / maly[1], delta=0.02)   # proporcje zachowane
        self.assertEqual((126, 94), panel._rozmiar_zdjecia(100))       # nie mniej niż 45%
        # zmiana szerokości przerysowuje ramkę
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        self.okno.update()
        panel._dopasuj_zdjecie(2000)
        plotno = panel._ramka_zdjecia["plotno"]
        self.assertEqual(280, int(plotno.cget("width")))
        self.assertEqual("NO IMAGE", self.napis_braku())

    def test_ramka_podaza_za_zmiana_rozmiaru_okna(self):
        """Regresja: wcześniejszy test wołał _dopasuj_zdjecie bezpośrednio i nie
        zauważył, że zdarzenie zmiany rozmiaru w ogóle nie było podpięte.
        Ten zmienia rozmiar prawdziwego okna — w obie strony."""
        import tkinter as tk

        def stan():
            karta = self.okno._widzety["szczegoly"].karty[0]
            return [int(c.cget("width")) for c in self.plotna()], karta.grid_bbox(1, 0)[2]   # szerokość kolumny wartości

        for poczatek, koniec in (("1900x1000", "1100x700"), ("1100x700", "1900x1000")):
            self.okno.geometry(poczatek + "+0+0")
            self.okno.update()
            self.okno.odswiez(zaznacz=f"E{self.pc}")
            self.okno.update()
            przed, _ = stan()
            self.okno.geometry(koniec + "+0+0")
            for _ in range(5):
                self.okno.update()
            po, szerokosc_wartosci = stan()
            with self.subTest(poczatek=poczatek, koniec=koniec):
                self.assertEqual(1, len(po))                   # jedna ramka, stara usunięta
                self.assertNotEqual(przed, po)                 # rozmiar poszedł za oknem
                self.assertGreaterEqual(szerokosc_wartosci, 120)  # wartości nie zostały ściśnięte do zera

    def test_zdjecie_widoczne_przy_kazdej_zakladce(self):
        panel = self.okno._widzety["szczegoly"]
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        self.okno.update()
        for zakladka in range(5):
            panel.notatnik.select(zakladka)
            self.okno.update()
            with self.subTest(zakladka=zakladka):
                self.assertEqual(1, len(self.plotna()))
                self.assertTrue(self.plotna()[0].winfo_ismapped())

    def test_lokalizacja_bez_ramki_zdjecia(self):
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        self.okno.update()
        self.okno.odswiez(zaznacz=f"L{self.regal}")
        self.okno.update()
        self.assertEqual([], self.plotna())

    def test_odpiecie_z_karty_z_usunieciem_pliku(self):
        sciezka = self.tmp / "fota.png"
        from PIL import Image
        Image.new("RGB", (100, 100)).save(sciezka)
        z = pliki.dodaj_plik(self.db, sciezka, {"egzemplarz_id": self.pc})
        wiersz = self.db.execute("SELECT z.*, NULL AS p_kategoria_id, NULL AS p_model_id, "
                                 "? AS p_egzemplarz_id, 'egzemplarz' AS pochodzenie "
                                 "FROM zasob z WHERE id = ?", (self.pc, z)).fetchone()
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            self.okno._widzety["szczegoly"]._odepnij(wiersz)
        self.assertIsNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())

    def test_okno_notatki_przezywa_przebudowe(self):
        okno = self.okno._widzety["szczegoly"]._okno_zasobu(self.pc, "notatka")
        okno.tytul.set("Recap")
        okno.tresc.widzet.insert("1.0", "Wymienione C12")
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        okno.zapisz()
        self.assertEqual(("Recap", "Wymienione C12"), tuple(self.db.execute(
            "SELECT tytul, tresc FROM zasob WHERE typ = 'notatka'").fetchone()))

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
