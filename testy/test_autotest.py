# SPDX-License-Identifier: GPL-3.0-or-later
"""Samosprawdzenie (--autotest), którym GitHub Actions sprawdza paczkę dla Windows."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import nornica
from testy.test_gui import EKRAN


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestAutotestu(unittest.TestCase):
    def test_wszystko_dziala_i_nie_dotyka_danych_uzytkownika(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        prawdziwe = tmp / "prawdziwe_dane"
        with mock.patch.dict(os.environ, {"NORNICA_DANE": str(prawdziwe)}):
            wynik = nornica.main(["--autotest", str(tmp / "raport.txt")])
        raport = (tmp / "raport.txt").read_text(encoding="utf-8")
        self.assertEqual(0, wynik, raport)
        self.assertIn("WYNIK: wszystko działa", raport)
        self.assertEqual(8, raport.count("OK    "))
        self.assertFalse(prawdziwe.exists())                     # folder użytkownika nietknięty
