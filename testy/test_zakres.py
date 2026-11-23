# SPDX-License-Identifier: GPL-3.0-or-later
"""Pole typu „zakres” (widełki): napięcie rdzenia procesora 1,225–1,325 V."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from baza import dane_startowe
from baza.migracje import KATALOG_SCHEMATU, biezaca_wersja, migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki
from i18n.tlumacz import ustaw_jezyk
from uslugi import inwentarz, slowniki_edycja
from uslugi.formatowanie import liczba_na_tekst, tekst_na_zakres
from wyjatki import BladNornicy


class TestOdczytuZakresu(unittest.TestCase):
    def test_zapisy_z_dokumentacji_i_z_klawiatury(self):
        for tekst in ("1,225-1,325", "1.225-1.325", "1,225 – 1,325", "1,225—1,325", "1.225...1.325",
                      "1,225…1,325", "1,325-1,225", "1,225-1,325 V", "1,225-1,325v"):
            self.assertEqual([1.225, 1.325], tekst_na_zakres(tekst, "V"), tekst)

    def test_jedna_liczba_i_puste(self):
        self.assertEqual(1.3, tekst_na_zakres("1,3"))
        self.assertEqual(1.5, tekst_na_zakres("1,5-1,5"))
        self.assertIsNone(tekst_na_zakres("  "))

    def test_bledne(self):
        for tekst in ("abc", "1,2-", "-1,2", "1-2-3", "1,2,3", "1,2 do 1,3"):
            with self.assertRaises(ValueError, msg=tekst):
                tekst_na_zakres(tekst)

    def test_wyswietlanie_w_obu_jezykach(self):
        self.assertEqual("1,225–1,325", liczba_na_tekst([1.225, 1.325], "pl"))
        self.assertEqual("1.225–1.325", liczba_na_tekst([1.225, 1.325], "en"))
        self.assertEqual("1–2", liczba_na_tekst([1, 2], "pl"))
        self.assertEqual("1,3", liczba_na_tekst(1.3, "pl"))
        # zwykłe listy (np. z importu) nie udają zakresu
        self.assertEqual("['a', 'b']", liczba_na_tekst(["a", "b"], "pl"))
        # zakres przechodzi z ekranu z powrotem do bazy bez strat
        self.assertEqual([1.225, 1.325], tekst_na_zakres(liczba_na_tekst([1.225, 1.325], "pl")))


class TestPolaZakresu(unittest.TestCase):
    def setUp(self):
        ustaw_jezyk("pl")
        self.db = otworz_baze(":memory:")
        self.addCleanup(self.db.close)
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        self.procesory = self.db.execute("SELECT id FROM kategoria WHERE kod = 'procesory'").fetchone()[0]

    def pole(self, kod="napiecie_v"):
        return next(p for p in slowniki.szablon(self.db, self.procesory) if p["kod"] == kod)

    def test_napiecie_rdzenia_jest_zakresem(self):
        self.assertEqual(("zakres", "V"), (self.pole()["typ"], self.pole()["jednostka"]))

    def test_zmiana_typu_liczby_na_zakres_przy_wpisanych_wartosciach(self):
        kat = slowniki_edycja.zapisz_kategorie(self.db, {"nazwy": {"en": "PSU", "pl": "Zasilacze ATX"},
                                                         "rodzic_id": None, "rodzaj": "czesc"})
        kod = slowniki_edycja.dodaj_pole(self.db, kat, {"typ": "real", "nazwy": {"en": "5V", "pl": "Napięcie 5V"},
                                                        "jednostka": "V"})
        inwentarz.zapisz_model(self.db, {"nazwa": "FSP", "kategoria_id": kat, "atrybuty": {kod: 5.0}})
        slowniki_edycja.zapisz_pole(self.db, kat, kod, {"typ": "zakres", "nazwy": {"en": "5V", "pl": "Napięcie 5V"},
                                                        "jednostka": "V"})
        pole = next(p for p in slowniki.szablon(self.db, kat) if p["kod"] == kod)
        self.assertEqual(("zakres", "V"), (pole["typ"], pole["jednostka"]))
        with self.assertRaises(BladNornicy):       # zakres -> tekst przy wpisanej wartości nadal zablokowany
            slowniki_edycja.zapisz_pole(self.db, kat, kod, {"typ": "text", "nazwy": {"en": "5V", "pl": "Napięcie 5V"}})


class TestMigracji007(unittest.TestCase):
    """Baza sprzed zmiany: migracje 001–006, napięcie rdzenia jako liczba."""

    def test_stara_baza_dostaje_zakres_a_wartosci_zostaja(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for plik in sorted(KATALOG_SCHEMATU.glob("00[1-6]_*")):
            shutil.copy(plik, tmp)
        db = otworz_baze(":memory:")
        self.addCleanup(db.close)
        migruj(db, katalog=tmp)
        self.assertEqual(6, biezaca_wersja(db))
        szablon = [{"kod": "taktowanie_mhz", "typ": "real", "jednostka": "MHz", "nazwy": {"pl": "Taktowanie"}},
                   {"kod": "napiecie_v", "typ": "real", "jednostka": "V", "nazwy": {"pl": "Napięcie rdzenia"}}]
        db.execute("INSERT INTO kategoria (kod, rodzaj, nazwy, szablon_atrybutow) VALUES "
                   "('procesory', 'czesc', '{\"pl\": \"Procesory\"}', ?)", (json.dumps(szablon),))
        db.execute("INSERT INTO model (kategoria_id, nazwa, atrybuty) VALUES (1, 'Pentium MMX', ?)",
                   (json.dumps({"napiecie_v": 2.8, "taktowanie_mhz": 166.0}),))
        self.assertEqual(7, migruj(db)[0][0])               # 007 jako pierwsza z oczekujących
        typy = {p["kod"]: p["typ"] for p in json.loads(
            db.execute("SELECT szablon_atrybutow FROM kategoria").fetchone()[0])}
        self.assertEqual({"taktowanie_mhz": "real", "napiecie_v": "zakres"}, typy)
        self.assertEqual({"napiecie_v": 2.8, "taktowanie_mhz": 166.0},
                         json.loads(db.execute("SELECT atrybuty FROM model").fetchone()[0]))

if __name__ == "__main__":
    unittest.main()


from testy import test_gui   # noqa: E402 — moduł, nie klasa: inaczej jej testy uruchomiłyby się drugi raz


@unittest.skipUnless(test_gui.EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestFormularzaZakresu(test_gui.TestPrzebudowy):
    def test_widelki_w_formularzu_i_na_karcie(self):
        ustaw_jezyk("pl")
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = 'procesory'").fetchone()[0]
        model = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "producent": "Intel", "nazwa": "E4300",
                                                 "atrybuty": {"napiecie_v": [1.225, 1.325]}})
        okno = self.okno.nowy_egzemplarz(lokalizacja_id=self.regal)
        okno.kategoria.ustaw(kat)
        okno._kategoria_zmieniona(kat)
        okno.model.ustaw(model)
        okno._model_zmieniony(model)
        self.okno.update()
        pole = okno.atrybuty.pola["napiecie_v"]
        self.assertEqual("1,225–1,325", pole.get())                      # widełki z modelu
        pole.set("1,25-1,3")                                              # ten egzemplarz: węższe
        okno.zapisz()
        self.okno.update()
        egz, atrybuty = self.db.execute("SELECT id, atrybuty FROM egzemplarz WHERE model_id = ?",
                                        (model,)).fetchone()
        self.assertEqual({"napiecie_v": [1.25, 1.3]}, json.loads(atrybuty))
        from raporty import dane                                         # eksport i karta: ten sam opis
        self.assertIn("Napięcie rdzenia: 1,25–1,3 V",
                      dane.opis_parametrow(self.db, kat, {"napiecie_v": [1.225, 1.325]},
                                           {"napiecie_v": [1.25, 1.3]}, "pl"))
        self.okno.odswiez(zaznacz=f"E{egz}")
        self.okno.update()

    def test_bledny_zakres_nie_zamyka_okna(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = 'procesory'").fetchone()[0]
        okno = self.okno.nowy_egzemplarz(lokalizacja_id=self.regal)
        okno.kategoria.ustaw(kat)
        okno._kategoria_zmieniona(kat)
        okno.v["nazwa_wlasna"].set("Celeron")
        self.okno.update()
        okno.atrybuty.pola["napiecie_v"].set("1,2 do 1,3")
        from unittest import mock
        with mock.patch("tkinter.messagebox.showerror") as blad:
            okno.zapisz()
        self.assertTrue(blad.called)
        self.assertTrue(okno.winfo_exists())
