# SPDX-License-Identifier: GPL-3.0-or-later
"""Dziennik błędów i okno awaryjne. Zgłoszenie: okno „Telefon jako skaner”
skurczone do pustej ramki, bez komunikatu — błąd był widoczny tylko w terminalu."""
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import dziennik
from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy


class ZDziennikiem:
    def wlacz_dziennik(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        przed = (list(dziennik.DZIENNIK.handlers), threading.excepthook, sys.excepthook)

        def przywroc():
            for h in dziennik.DZIENNIK.handlers[len(przed[0]):]:
                h.close()
            dziennik.DZIENNIK.handlers[:] = przed[0]
            threading.excepthook, sys.excepthook = przed[1], przed[2]

        self.addCleanup(przywroc)
        dziennik.wlacz(self.tmp / "nornica.log")

    def tresc(self) -> str:
        for h in dziennik.DZIENNIK.handlers:
            h.flush()
        return (self.tmp / "nornica.log").read_text(encoding="utf-8")


class TestDziennika(ZDziennikiem, unittest.TestCase):
    def setUp(self):
        self.wlacz_dziennik()

    def test_blad_w_watku_w_tle(self):
        """Np. serwer telefonu: błąd w wątku trafia do pliku, nie tylko do terminala."""
        def zepsuty():
            raise RuntimeError("awaria w tle")
        watek = threading.Thread(target=zepsuty, name="serwer-skanera")
        watek.start()
        watek.join()
        tresc = self.tresc()
        self.assertIn("serwer-skanera", tresc)
        self.assertIn("RuntimeError: awaria w tle", tresc)

    def test_rozmiar_ograniczony(self):
        obsluga = dziennik.DZIENNIK.handlers[-1]
        self.assertEqual(1_000_000, obsluga.maxBytes)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOknaAwaryjnego(ZDziennikiem, TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.wlacz_dziennik()

    def zepsute_okno(self):
        from gui.bazowe import OknoDialogowe

        class Zepsute(OknoDialogowe):
            def zbuduj_ui(self):
                from tkinter import ttk
                ttk.Frame(self).pack()            # zaczęło się budować…
                raise KeyError("brak_klucza")     # …i przerwał błąd

        return Zepsute(self.okno)

    def test_komunikat_zamiast_pustej_ramki(self):
        with mock.patch.dict(os.environ, {"NORNICA_SUROWE_BLEDY": ""}):
            okno = self.zepsute_okno()
            okno.pokaz()
            self.okno.update()
        teksty = [w.cget("text") for r in okno.winfo_children() for w in r.winfo_children()]
        self.assertTrue(any("KeyError" in tekst and "nornica.log" in tekst for tekst in teksty))
        self.assertIn(t("przycisk.zamknij"), teksty)
        self.assertGreater(okno.winfo_width(), 200)                 # nie pusta ramka
        self.assertIn("Nie udało się zbudować okna Zepsute", self.tresc())
        self.assertIn("KeyError: 'brak_klucza'", self.tresc())

    def test_tez_po_przebudowie(self):
        with mock.patch.dict(os.environ, {"NORNICA_SUROWE_BLEDY": ""}):
            okno = self.zepsute_okno()
            okno.pokaz()
            self.okno.przelacz_jezyk("pl")
            self.okno.update()
        self.assertTrue(okno.winfo_exists())
        self.assertGreater(okno.winfo_width(), 200)

    def test_w_testach_blad_przerywa_test(self):
        """Okno awaryjne nie może ukrywać zepsutych okien przed testami."""
        okno = self.zepsute_okno()
        with self.assertRaises(KeyError):
            okno.pokaz()
        okno.zamknij()

    def test_blad_w_obsludze_klikniecia(self):
        def zepsuty():
            raise ZeroDivisionError("dzielenie przez zero")
        import io
        # wyciszenie terminala przez podmianę strumienia — NIE funkcji wypisującej ślad,
        # bo z tej samej funkcji korzysta zapis śladu w dzienniku
        with mock.patch("tkinter.messagebox.showerror") as komunikat, \
                mock.patch("sys.stderr", new=io.StringIO()):
            self.okno.after(0, zepsuty)
            self.okno.after(0, zepsuty)                              # seria: jeden komunikat
            for _ in range(5):
                self.okno.update()
        komunikat.assert_called_once()
        self.assertIn("ZeroDivisionError", komunikat.call_args[0][1])
        self.assertIn("nornica.log", komunikat.call_args[0][1])
        self.assertIn("ZeroDivisionError: dzielenie przez zero", self.tresc())

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
