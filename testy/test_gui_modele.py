# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy interfejsu: dziedziczenie parametrów po modelu, edycja modelu
z okna egzemplarza, katalog modeli."""
import json
import tkinter as tk
import unittest
from unittest import mock

from baza.repozytoria import slowniki
from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from uslugi import inwentarz


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestModeli(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.kat_komputery = self.db.execute(
            "SELECT id FROM kategoria WHERE kod='komputery_fabryczne'").fetchone()[0]
        self.atari = inwentarz.zapisz_model(self.db, {
            "kategoria_id": self.kat_komputery, "producent": "Atari", "nazwa": "65XE",
            "atrybuty": {"procesor": "6502C", "taktowanie_mhz": 1.77, "pamiec": 65536, "norma_tv": "PAL"}})

    def nowy_z_modelem(self):
        okno = self.okno.nowy_egzemplarz(lokalizacja_id=self.regal)
        okno.kategoria.ustaw(self.kat_komputery)
        okno._kategoria_zmieniona(self.kat_komputery)
        okno.model.ustaw(self.atari)
        okno._model_zmieniony(self.atari)
        okno._notatnik.select(1)
        self.okno.update()
        return okno

    def test_pola_wypelnione_wartosciami_modelu(self):
        okno = self.nowy_z_modelem()
        pola = okno.atrybuty.pola
        self.assertEqual("6502C", pola["procesor"].get())
        self.assertEqual("1.77", pola["taktowanie_mhz"].get())
        self.assertEqual("PAL", pola["norma_tv"].wartosc)
        self.assertEqual(t("formularz.z_modelu"), okno.atrybuty._podpowiedzi["procesor"].cget("text"))

    def test_zapisywane_tylko_zmiany(self):
        okno = self.nowy_z_modelem()
        okno.atrybuty.pola["pamiec"].liczba.set("320")   # rozszerzona pamięć (jednostka KB z modelu)
        self.okno.update()
        self.assertIn("64 KB", okno.atrybuty._podpowiedzi["pamiec"].cget("text"))
        okno.zapisz()
        wiersz = self.db.execute("SELECT atrybuty FROM egzemplarz WHERE model_id = ?",
                                 (self.atari,)).fetchone()
        self.assertEqual({"pamiec": 320 * 1024}, json.loads(wiersz[0]))      # w bajtach

    def test_poprawka_modelu_z_okna_egzemplarza(self):
        okno = self.nowy_z_modelem()
        okno.atrybuty.pola["pamiec"].liczba.set("320")
        self.assertEqual("normal", str(okno._przycisk_edycji_modelu.cget("state")))
        okno._edytuj_model()
        self.okno.update()
        from gui.okno_modelu import OknoModelu
        edycja = next(d for d in self.okno._dialogi if isinstance(d, OknoModelu))
        edycja.atrybuty.pola["taktowanie_mhz"].set("1,79")   # poprawiona pomyłka
        edycja.zapisz()
        self.okno.update()
        self.assertFalse(edycja.winfo_exists())
        # wartość dziedziczona poszła za modelem, nadpisana została
        self.assertEqual("1.79", okno.atrybuty.pola["taktowanie_mhz"].get())
        self.assertEqual("320 KB", okno.atrybuty.pola["pamiec"].tekst())
        atrybuty = json.loads(self.db.execute("SELECT atrybuty FROM model WHERE id = ?",
                                              (self.atari,)).fetchone()[0])
        self.assertEqual(1.79, atrybuty["taktowanie_mhz"])

    def test_przycisk_edycji_wylaczony_bez_modelu(self):
        okno = self.okno.nowy_egzemplarz()
        self.assertEqual("disabled", str(okno._przycisk_edycji_modelu.cget("state")))

    def test_katalog_edycja_i_przebudowa(self):
        katalog = self.okno.katalog_modeli()
        self.assertIs(katalog, self.okno.katalog_modeli())      # jedno okno katalogu
        self.assertTrue(katalog._lista.exists(str(self.atari)))
        katalog.filtr.set("65")
        katalog._lista.selection_set(str(self.atari))
        self.okno.update()
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertEqual("65", katalog.filtr.get())
        self.assertEqual((str(self.atari),), katalog._lista.selection())
        self.assertEqual(t("kolumna.producent"), katalog._lista.heading("producent", "text"))
        katalog.edytuj()
        self.okno.update()
        from gui.okno_modelu import OknoModelu
        self.assertTrue(any(isinstance(d, OknoModelu) and d.model_id == self.atari
                            for d in self.okno._dialogi))

    def test_katalog_usuwanie(self):
        st = slowniki.status_id(self.db, "dziala")
        inwentarz.zapisz_egzemplarz(self.db, {"model_id": self.atari, "status_id": st})
        katalog = self.okno.katalog_modeli()
        katalog.zaznaczony = self.atari
        with mock.patch("tkinter.messagebox.showwarning") as ostrzezenie:
            katalog.usun()
        self.assertIn(t("tabela.egzemplarz"), ostrzezenie.call_args[0][1])
        wolny = inwentarz.zapisz_model(self.db, {"kategoria_id": self.kat_komputery, "nazwa": "130XE"})
        katalog.zaznaczony = wolny
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            katalog.usun()
        self.assertIsNone(self.db.execute("SELECT 1 FROM model WHERE id = ?", (wolny,)).fetchone())

    # testy z klasy bazowej nie są tu powtarzane
    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
