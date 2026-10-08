# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy licencji: pilnują, żeby nowe pliki miały nagłówek GPL, migracje go
NIE dostały (strażnik sum kontrolnych zablokowałby program), a każda nowa
biblioteka trafiła do spisu licencji zewnętrznych."""
import re
import unittest
from pathlib import Path

from testy.test_gui import EKRAN, TestPrzebudowy

KORZEN = Path(__file__).resolve().parents[1]
NAGLOWEK = "SPDX-License-Identifier: GPL-3.0-or-later"


class TestLicencji(unittest.TestCase):
    def test_plik_licencji(self):
        tekst = (KORZEN / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(tekst.lstrip().startswith("GNU GENERAL PUBLIC LICENSE"))   # tytuł wyśrodkowany spacjami
        self.assertIn("Version 3, 29 June 2007", tekst)
        self.assertIn("END OF TERMS AND CONDITIONS", tekst)

    def test_naglowek_w_kazdym_pliku_python(self):
        bez_naglowka = []
        for plik in KORZEN.rglob("*.py"):
            if "schemat" in plik.parts:
                continue
            if NAGLOWEK not in "".join(plik.read_text(encoding="utf-8").splitlines(keepends=True)[:2]):
                bez_naglowka.append(str(plik.relative_to(KORZEN)))
        self.assertEqual([], sorted(bez_naglowka))

    def test_migracje_bez_naglowka(self):
        """Dopisanie nagłówka do zastosowanej migracji zmienia jej sumę kontrolną —
        strażnik migracji odmówiłby wtedy uruchomienia programu u użytkownika."""
        for plik in (KORZEN / "baza" / "schemat").iterdir():
            if plik.suffix not in (".sql", ".py"):
                continue                         # np. __pycache__ po imporcie migracji w Pythonie
            with self.subTest(plik=plik.name):
                self.assertNotIn("SPDX", plik.read_text(encoding="utf-8"))

    def test_jsqr_zachowuje_wlasna_licencje(self):
        self.assertNotIn("GPL", (KORZEN / "zasoby" / "www" / "jsQR.js").read_text(encoding="utf-8")[:2000])
        self.assertIn("Apache License", (KORZEN / "zasoby" / "www" / "LICENSE-jsQR.txt").read_text(encoding="utf-8"))

    def test_kazda_biblioteka_w_spisie_licencji(self):
        spis = (KORZEN / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").casefold()
        wymagania = []
        for nazwa in ("requirements.txt", "requirements-opcjonalne.txt"):
            for linia in (KORZEN / nazwa).read_text(encoding="utf-8").splitlines():
                linia = linia.split("#")[0].strip()
                if linia:
                    wymagania.append(re.split(r"[<>=!~\[ ]", linia)[0])
        brakujace = [w for w in wymagania if w.casefold() not in spis]
        self.assertEqual([], brakujace)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOknaInformacji(TestPrzebudowy):
    def test_notka_licencji(self):
        from gui.okna_info import OknoOProgramie
        from i18n.tlumacz import t
        okno = OknoOProgramie(self.okno)
        okno.pokaz()
        self.okno.update()
        teksty = [w.cget("text") for w in okno.winfo_children()[0].winfo_children() if w.winfo_class() == "TLabel"]
        self.assertTrue(any("GPL-3.0-or-later" in tekst for tekst in teksty))
        self.assertIn(t("info.gwarancja"), teksty)

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
