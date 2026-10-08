# SPDX-License-Identifier: GPL-3.0-or-later
"""Kolejność wpisów wbudowanych nie zależy od historii bazy.

Baza założona starszą wersją programu ma kategorie, statusy i złącza
z numerami kolejności z ówczesnej listy; pozycje dopisane w nowszej wersji
dostawały numery zajęte już przez inne. Po uzupełnieniu danych startowych
kolejność ma być taka sama jak w bazie założonej od zera, a wpisy własne
zawsze za wbudowanymi."""
import unittest
from unittest import mock

from baza import dane_startowe as D
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki, zlacza
from i18n.tlumacz import ustaw_jezyk
from uslugi import slowniki_edycja


def baza(kategorie=None, zlacza_=None, statusy=None):
    db = otworz_baze(":memory:")
    migruj(db)
    with mock.patch.object(D, "KATEGORIE", kategorie or D.KATEGORIE), \
            mock.patch.object(D, "ZLACZA", zlacza_ or D.ZLACZA), \
            mock.patch.object(D, "STATUSY", statusy or D.STATUSY):
        D.wypelnij(db)
    return db


def kody_kategorii(db):
    kody = {w["id"]: w["kod"] for w in slowniki.kategorie(db)}
    return [kody[i] for i, _, _ in slowniki.kategorie_plasko(db)]


class TestKolejnosci(unittest.TestCase):
    def setUp(self):
        ustaw_jezyk("en")
        self.wzor = baza()

    def test_stara_baza_dostaje_kolejnosc_z_listy(self):
        # stara wersja: bez konsol, części w odwróconej kolejności, bez złącza SATA power
        czesci = [k for k in D.KATEGORIE if k["rodzic"] == "czesci"]
        stare = [k for k in D.KATEGORIE if k["kod"] != "konsole" and k["rodzic"] != "czesci"] + czesci[::-1]
        db = baza(kategorie=stare, zlacza_=[z for z in D.ZLACZA if z[0] != "zasilanie_sata"],
                  statusy=D.STATUSY[::-1])
        self.assertNotEqual(kody_kategorii(self.wzor), kody_kategorii(db))
        D.wypelnij(db)                                          # start nowej wersji
        self.assertEqual(kody_kategorii(self.wzor), kody_kategorii(db))
        self.assertEqual([w["kod"] for w in zlacza.typy(self.wzor)], [w["kod"] for w in zlacza.typy(db)])
        self.assertEqual([w["kod"] for w in slowniki.statusy(self.wzor)], [w["kod"] for w in slowniki.statusy(db)])
        self.assertEqual(0, D.wypelnij(db))                     # drugi przebieg niczego nie zmienia

    def test_wlasne_zawsze_za_wbudowanymi(self):
        db = baza(kategorie=[k for k in D.KATEGORIE if k["kod"] != "konsole"])
        wlasna = slowniki_edycja.zapisz_kategorie(db, {"nazwy": {"en": "AAA first by name", "pl": "AAA"},
                                                       "rodzic_id": None, "rodzaj": "komputer_fabryczny"})
        D.wypelnij(db)                                          # nowa wersja dokłada „konsole”
        gora = [i for i, glebokosc, _ in slowniki.kategorie_plasko(db) if glebokosc == 0]
        kody = {w["id"]: w["kod"] for w in slowniki.kategorie(db)}
        self.assertEqual(wlasna, gora[-1])                      # własna na końcu, mimo nazwy „AAA…”
        self.assertEqual([k["kod"] for k in D.KATEGORIE if k["rodzic"] is None], [kody[i] for i in gora[:-1]])

if __name__ == "__main__":
    unittest.main()
