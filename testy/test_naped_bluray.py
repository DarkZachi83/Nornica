# SPDX-License-Identifier: GPL-3.0-or-later
"""Blu-ray i HD DVD na liście rodzajów napędów optycznych (migracja 008)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from baza import dane_startowe
from baza.migracje import KATALOG_SCHEMATU, biezaca_wersja, migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki


def wartosci(db):
    kat = db.execute("SELECT id FROM kategoria WHERE kod = 'napedy_optyczne'").fetchone()[0]
    return next(p for p in slowniki.szablon(db, kat) if p["kod"] == "rodzaj_napedu")["wartosci"]


class TestBluray(unittest.TestCase):
    def test_nowa_baza(self):
        db = otworz_baze(":memory:")
        self.addCleanup(db.close)
        migruj(db)
        dane_startowe.wypelnij(db)
        self.assertEqual(["CD-ROM", "CD-R", "CD-RW", "DVD-ROM", "DVD±RW", "DVD-RAM", "HD DVD",
                          "BD-ROM", "BD-ROM/DVD±RW (combo)", "BD-R/RE"], wartosci(db))

    def test_stara_baza_z_wlasnymi_wartosciami(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for plik in sorted(KATALOG_SCHEMATU.glob("00[1-7]_*")):
            shutil.copy(plik, tmp)
        db = otworz_baze(":memory:")
        self.addCleanup(db.close)
        migruj(db, katalog=tmp)
        self.assertEqual(7, biezaca_wersja(db))
        szablon = [{"kod": "rodzaj_napedu", "typ": "enum", "nazwy": {"pl": "Rodzaj napędu"},
                    "wartosci": ["CD-ROM", "CD-R", "CD-RW", "DVD-ROM", "DVD±RW"],
                    "wartosci_wlasne": ["bd-rom", "Napęd ZIP-CD"]},       # użytkownik dopisał sam
                   {"kod": "predkosc", "typ": "text", "nazwy": {"pl": "Prędkość"}}]
        db.execute("INSERT INTO kategoria (kod, rodzaj, nazwy, szablon_atrybutow) VALUES "
                   "('napedy_optyczne', 'czesc', ?, ?)", (json.dumps({"pl": "Napędy optyczne"}), json.dumps(szablon)))
        db.execute("INSERT INTO model (kategoria_id, nazwa, atrybuty) VALUES (1, 'LG', ?)",
                   (json.dumps({"rodzaj_napedu": "bd-rom"}),))
        self.assertEqual([8], migruj(db)[0])
        pole = json.loads(db.execute("SELECT szablon_atrybutow FROM kategoria").fetchone()[0])[0]
        self.assertEqual(["CD-ROM", "CD-R", "CD-RW", "DVD-ROM", "DVD±RW", "DVD-RAM", "HD DVD",
                          "BD-ROM", "BD-ROM/DVD±RW (combo)", "BD-R/RE"], pole["wartosci"])
        self.assertEqual(["Napęd ZIP-CD"], pole["wartosci_wlasne"])              # bez dubla
        self.assertEqual({"rodzaj_napedu": "bd-rom"},                              # dane bez zmian
                         json.loads(db.execute("SELECT atrybuty FROM model").fetchone()[0]))
        self.assertEqual([], migruj(db)[0])                                         # drugi raz: nic


if __name__ == "__main__":
    unittest.main()
