# SPDX-License-Identifier: GPL-3.0-or-later
"""Usuwanie zdjęć przyciskiem pod miniaturą i sprzątanie wpisów, których plik
usunięto poza programem. Zgłoszenie: brak sposobu na usunięcie zdjęcia,
a plik skasowany z katalogu zostawiał miniaturę i błąd „Nie znaleziono pliku”."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from uslugi import inwentarz, pliki


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestUsuwaniaZdjec(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp / "dane")})
        straznik.start()
        self.addCleanup(straznik.stop)

    def zdjecie(self, nazwa: str, kolor=(200, 30, 30)) -> Path:
        from PIL import Image
        sciezka = self.tmp / nazwa
        Image.new("RGB", (120, 90), kolor).save(sciezka)
        return sciezka

    def pokaz_zasoby(self):
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        panel = self.okno._widzety["szczegoly"]
        panel.notatnik.select(3)
        self.okno.update()
        return panel

    def widzety(self, typ: str):
        wynik, kolejka = [], [self.okno._widzety["szczegoly"].karty[3]]
        while kolejka:
            w = kolejka.pop()
            kolejka.extend(w.winfo_children())
            if w.winfo_class() == typ:
                wynik.append(w)
        return wynik

    def przyciski_usun(self):
        return [b for b in self.widzety("TButton") if b.cget("text") == t("akcja.usun_zdjecie")]

    def test_przycisk_usuwa_zdjecie_i_plik(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie("a.png"), {"egzemplarz_id": self.pc})
        pliki.ustaw_zdjecie_glowne(self.db, self.pc, z)
        plik = pliki.sciezka_pliku(self.db, self.db.execute(
            "SELECT plik_sciezka FROM zasob WHERE id = ?", (z,)).fetchone()[0])
        self.pokaz_zasoby()
        self.assertEqual(1, len(self.przyciski_usun()))
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as pytanie:
            self.przyciski_usun()[0].invoke()
        self.assertEqual(1, pytanie.call_count)                     # jedno potwierdzenie, nie dwa
        self.assertFalse(plik.exists())
        self.assertIsNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())
        self.assertIsNone(pliki.zdjecie_glowne(self.db, self.pc))

    def test_odmowa_niczego_nie_zmienia(self):
        z = pliki.dodaj_plik(self.db, self.zdjecie("a.png"), {"egzemplarz_id": self.pc})
        self.pokaz_zasoby()
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            self.przyciski_usun()[0].invoke()
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM zasob_powiazanie WHERE zasob_id = ?", (z,)).fetchone())

    def test_plik_uzywany_gdzie_indziej_zostaje(self):
        """To samo zdjęcie podpięte też do innego egzemplarza: po usunięciu z jednego plik zostaje."""
        sciezka = self.zdjecie("wspolne.png")
        z = pliki.dodaj_plik(self.db, sciezka, {"egzemplarz_id": self.pc})
        pliki.dodaj_plik(self.db, sciezka, {"egzemplarz_id": self.karta})   # ten sam plik (ta sama suma)
        plik = pliki.sciezka_pliku(self.db, self.db.execute(
            "SELECT plik_sciezka FROM zasob WHERE id = ?", (z,)).fetchone()[0])
        self.pokaz_zasoby()
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            self.przyciski_usun()[0].invoke()
        self.assertTrue(plik.exists())
        self.assertEqual([], pliki.zdjecia_egzemplarza(self.db, self.pc))
        self.assertEqual(1, len(pliki.zdjecia_egzemplarza(self.db, self.karta)))

    def test_zdjecie_z_modelu_pytanie_o_wszystkie_egzemplarze(self):
        kat = self.db.execute("SELECT kategoria_id FROM egzemplarz WHERE id = ?", (self.pc,)).fetchone()[0]
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "Wzorcowy"})
        self.db.execute("UPDATE egzemplarz SET model_id = ?, kategoria_id = NULL WHERE id = ?", (m, self.pc))
        z = pliki.dodaj_plik(self.db, self.zdjecie("model.png"), {"model_id": m})
        self.pokaz_zasoby()
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as pytanie:
            self.przyciski_usun()[0].invoke()
        self.assertIn(t("pochodzenie.model"), pytanie.call_args[0][1])     # mówi, skąd zdjęcie pochodzi
        self.assertIsNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())

    def test_plik_usuniety_poza_programem(self):
        """Odtworzenie zgłoszenia: plik skasowany z katalogu ręcznie."""
        z = pliki.dodaj_plik(self.db, self.zdjecie("zgubione.png"), {"egzemplarz_id": self.pc})
        wpis = self.db.execute("SELECT plik_sciezka, tytul FROM zasob WHERE id = ?", (z,)).fetchone()
        pliki.sciezka_pliku(self.db, wpis[0]).unlink()
        self.pokaz_zasoby()
        napisy = [w.cget("text") for w in self.widzety("TLabel")]
        self.assertIn(t("zasoby.brak_pliku"), napisy)                    # widać, że plik zniknął
        panel = self.okno._widzety["szczegoly"]
        zasob = next(x for x in pliki.zdjecia_egzemplarza(self.db, self.pc) if x["id"] == z)
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as pytanie, \
                mock.patch("tkinter.messagebox.showerror") as blad:
            panel._otworz(self.pc, zasob)                                 # kliknięcie w miniaturę
        blad.assert_not_called()                                          # zamiast błędu — propozycja
        self.assertIn(wpis[1], pytanie.call_args[0][1])
        self.assertIsNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
