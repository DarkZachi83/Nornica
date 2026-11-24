# SPDX-License-Identifier: GPL-3.0-or-later
"""Motyw jasny i ciemny: palety, przełączanie, zapamiętywanie, działanie bez ttkbootstrap."""
import sys
import unittest
from unittest import mock

from gui import styl
from testy import test_gui


def _jasnosc(kolor: str) -> float:
    def skladowa(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(kolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * skladowa(r) + 0.7152 * skladowa(g) + 0.0722 * skladowa(b)


def kontrast(a: str, b: str) -> float:
    """Współczynnik kontrastu WCAG 2.x (1–21)."""
    jasniejszy, ciemniejszy = sorted((_jasnosc(a), _jasnosc(b)), reverse=True)
    return (jasniejszy + 0.05) / (ciemniejszy + 0.05)


class TestPalet(unittest.TestCase):
    def test_palety_maja_te_same_klucze(self):
        self.assertEqual(set(styl.PALETY["jasny"]), set(styl.PALETY["ciemny"]))
        self.assertEqual(set(styl.STATUSY["jasny"]), set(styl.STATUSY["ciemny"]))
        self.assertEqual(set(styl.MOTYWY), set(styl.PALETY))

    def test_kazdy_status_startowy_ma_kolor(self):
        from baza import dane_startowe
        from baza.migracje import migruj
        from baza.polaczenie import otworz_baze
        db = otworz_baze(":memory:")
        migruj(db)
        dane_startowe.wypelnij(db)
        kody = {w[0] for w in db.execute("SELECT kod FROM status WHERE kod IS NOT NULL")}
        db.close()
        self.assertEqual(kody - {"dziala"}, set(styl.STATUSY["jasny"]))

    def test_kontrast_tekstu_na_listach(self):
        """Tekst na tle list i pól (panel): zwykły co najmniej 7:1 (WCAG AAA),
        opisy, odnośniki i kolory statusów co najmniej 4:1."""
        for motyw in styl.MOTYWY:
            paleta = styl.PALETY[motyw]
            with self.subTest(motyw=motyw):
                self.assertGreaterEqual(kontrast(paleta["tusz"], paleta["panel"]), 7)
                self.assertGreaterEqual(kontrast(paleta["tusz"], paleta["zaznaczenie"]), 4.5)
                for nazwa in ("przygaszony", "laminat", "drewno"):
                    self.assertGreaterEqual(kontrast(paleta[nazwa], paleta["panel"]), 4, nazwa)
                    self.assertGreaterEqual(kontrast(paleta[nazwa], paleta["tlo"]), 4, nazwa)
                for kod, kolor in styl.STATUSY[motyw].items():
                    self.assertGreaterEqual(kontrast(kolor, paleta["panel"]), 4, kod)

    def test_nazwa_motywu_i_przelacznik(self):
        self.assertEqual("ciemny", styl.nazwa_motywu("ciemny"))
        for zla in (None, "", "dark", "CIEMNY"):
            self.assertEqual(styl.DOMYSLNY_MOTYW, styl.nazwa_motywu(zla))
        self.assertEqual(("☾", "ciemny"), styl.przelacznik("jasny"))
        self.assertEqual(("☀", "jasny"), styl.przelacznik("ciemny"))


class TestPrzelaczania(test_gui.TestPrzebudowy):
    def tearDown(self):
        super().tearDown()
        styl._ustaw_palete(styl.DOMYSLNY_MOTYW)      # następne testy zaczynają od jasnego

    def _przycisk_motywu(self):
        return self.okno._widzety["motyw"]

    def test_domyslnie_jasny_z_ksiezycem(self):
        self.assertEqual("jasny", self.okno.motyw)
        self.assertEqual("☾", self._przycisk_motywu().cget("text"))
        self.assertEqual(styl.PALETY["jasny"]["tlo"].lower(), self.okno.cget("background").lower())

    def test_przelaczenie_zmienia_kolory_zapamietuje_i_zachowuje_stan(self):
        from baza.repozytoria import ustawienia
        from gui.model_drzewa import iid_egzemplarza
        self.okno.odswiez(zaznacz=iid_egzemplarza(self.karta))
        self._przycisk_motywu().invoke()
        self.okno.update()
        self.assertEqual("ciemny", self.okno.motyw)
        self.assertEqual("ciemny", ustawienia.pobierz(self.db, "motyw"))
        self.assertEqual("ciemny", self.okno.motyw_var.get())           # menu Widok
        self.assertEqual("☀", self._przycisk_motywu().cget("text"))
        self.assertEqual(styl.PALETY["ciemny"]["tlo"].lower(), self.okno.cget("background").lower())
        self.assertEqual(styl.PALETY["ciemny"]["tusz"], styl.KOLORY_STATUSOW["dziala"])
        drzewo = self.drzewo()
        self.assertEqual((iid_egzemplarza(self.karta),), drzewo.selection())   # przebudowa nie gubi zaznaczenia
        self.assertEqual(styl.STATUSY["ciemny"]["uszkodzony"],
                         str(drzewo.tag_configure("status_uszkodzony", "foreground")))
        import tkinter as tk
        pole = tk.Text(self.okno)                   # klasyczne pole tk — kolory z bazy opcji
        self.assertEqual(styl.PALETY["ciemny"]["panel"].lower(), str(pole.cget("background")).lower())
        self.assertEqual(styl.PALETY["ciemny"]["tusz"].lower(), str(pole.cget("foreground")).lower())
        pole.destroy()
        self.okno.przelacz_motyw("jasny")
        self.assertEqual("jasny", ustawienia.pobierz(self.db, "motyw"))
        self.assertEqual("☾", self._przycisk_motywu().cget("text"))

    def test_otwarte_okno_dostaje_nowe_tlo(self):
        okno = self.okno.edytuj_egzemplarz(self.pc)
        self.okno.update()
        self.okno.przelacz_motyw("ciemny")
        self.okno.update()
        self.assertTrue(okno.winfo_exists())
        self.assertEqual(styl.PALETY["ciemny"]["tlo"].lower(), okno.cget("background").lower())

    def test_motyw_z_ustawien_po_ponownym_uruchomieniu(self):
        from gui.okno_glowne import OknoGlowne
        self.okno.przelacz_motyw("ciemny")
        self.okno.destroy()
        self.okno = OknoGlowne(self.db, pokaz_powitanie=False)
        self.okno.update()
        self.assertEqual("ciemny", self.okno.motyw)
        self.assertEqual("☀", self._przycisk_motywu().cget("text"))

    def test_bez_ttkbootstrap_zwykly_ttk_z_ta_sama_paleta(self):
        from tkinter import ttk
        brak = {"ttkbootstrap": None, "ttkbootstrap.style": None, "ttkbootstrap.style.theme": None}
        with mock.patch.dict(sys.modules, brak):
            self.okno.przelacz_motyw("ciemny")
        self.assertEqual("clam", ttk.Style(self.okno).theme_use())
        self.assertEqual(styl.PALETY["ciemny"]["tlo"].lower(), self.okno.cget("background").lower())
        self.assertEqual(styl.PALETY["ciemny"]["panel"].lower(),
                         str(ttk.Style(self.okno).lookup("Treeview", "fieldbackground")).lower())

    def test_pasek_miesci_sie_w_domyslnym_oknie(self):
        """Przy 1180 px napisy „Skanuj” i „Szukaj” mają pełną szerokość w obu językach
        (wcześniej po polsku „Skanuj” dostawało 1 piksel)."""
        from i18n.tlumacz import t, ustaw_jezyk
        for jezyk in ("pl", "en"):
            with self.subTest(jezyk=jezyk):
                ustaw_jezyk(jezyk)
                self.okno.przebuduj()
                self.okno.geometry("1180x720")
                self.okno.update()
                ramka = self.okno._widzety["szukaj"].master
                napisy = [w for w in ramka.winfo_children() if w.winfo_class() == "TLabel"]
                self.assertEqual({t("pasek.skanuj"), t("pasek.szukaj")}, {str(w.cget("text")) for w in napisy})
                for napis in napisy:
                    self.assertGreaterEqual(napis.winfo_width(), napis.winfo_reqwidth())


if __name__ == "__main__":
    unittest.main()
