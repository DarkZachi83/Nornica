# SPDX-License-Identifier: GPL-3.0-or-later
"""Funkcje odczytu przeniesione z okien do repozytoriów (porządki 0.7.5)."""
import json
import unittest

from baza.repozytoria import lokalizacje, modele, slowniki, szczegoly, zasoby, zlacza
from testy.test_baza import BazaTestowa
from uslugi import archiwum


class TestOdczytu(BazaTestowa):
    def test_kategoria_po_kodzie(self):
        self.assertEqual("czesci", slowniki.kategoria_po_kodzie(self.db, "czesci")["kod"])
        self.assertIsNone(slowniki.kategoria_po_kodzie(self.db, "nie_ma_takiej"))

    def test_status(self):
        wiersz = slowniki.status(self.db, self.status)
        self.assertEqual("dziala", wiersz["kod"])
        self.assertIn("pl", json.loads(wiersz["nazwy"]))
        self.assertIsNone(slowniki.status(self.db, None))
        self.assertIsNone(slowniki.status(self.db, 99999))

    def test_liczby_egzemplarzy(self):
        kat = slowniki.kategoria_po_kodzie(self.db, "czesci")["id"]
        model = modele.wstaw(self.db, {"kategoria_id": kat, "nazwa": "SIMM 72"})
        pudlo = self.lokalizacja("Pudło 7")
        self.assertEqual(0, modele.liczba_egzemplarzy(self.db, model))
        self.egzemplarz(model_id=model, lokalizacja_id=pudlo)
        self.egzemplarz(model_id=model)
        self.assertEqual(2, modele.liczba_egzemplarzy(self.db, model))
        self.assertEqual(1, lokalizacje.liczba_egzemplarzy(self.db, pudlo))

    def test_brakujace_wiersze(self):
        self.assertIsNone(szczegoly.zdarzenie(self.db, None))
        self.assertIsNone(szczegoly.zdarzenie(self.db, 12345))
        self.assertIsNone(zasoby.pobierz(self.db, None))
        self.assertIsNone(zlacza.typ(self.db, 12345))

    def test_typ_zlacza(self):
        typ = zlacza.typy(self.db)[0]
        self.assertEqual(typ["rodzaj"], zlacza.typ(self.db, typ["id"])["rodzaj"])

    def test_zawartosc_kopii(self):
        self.lokalizacja("Regał")
        self.egzemplarz()
        wynik = archiwum.zawartosc(self.db)
        self.assertEqual({"egzemplarze": 1, "lokalizacje": 1, "pliki": 0, "rozmiar": 0}, wynik)


if __name__ == "__main__":
    unittest.main()
