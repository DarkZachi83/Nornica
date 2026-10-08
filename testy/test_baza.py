# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy schematu, migracji, danych startowych i reguł integralności."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from baza import dane_startowe
from baza.bledy import klucz_bledu_bazy
from baza.migracje import KATALOG_SCHEMATU, biezaca_wersja, migruj
from baza.polaczenie import otworz_baze, transakcja
from wyjatki import BladNornicy


class BazaTestowa(unittest.TestCase):
    def setUp(self):
        self.db = otworz_baze(":memory:")
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        self.status = self.db.execute("SELECT id FROM status WHERE kod='dziala'").fetchone()[0]

    def tearDown(self):
        self.db.close()

    def egzemplarz(self, **pola):
        pola.setdefault("status_id", self.status)
        pola.setdefault("nazwa_wlasna", "test")
        if "model_id" not in pola:
            pola.setdefault("kategoria_id", self.db.execute(
                "SELECT id FROM kategoria WHERE kod = 'akcesoria_inne'").fetchone()[0])
        kolumny = ", ".join(pola)
        znaki = ", ".join("?" * len(pola))
        kursor = self.db.execute(f"INSERT INTO egzemplarz ({kolumny}) VALUES ({znaki})",
                                 tuple(pola.values()))
        return kursor.lastrowid

    def lokalizacja(self, nazwa, rodzic=None):
        return self.db.execute("INSERT INTO lokalizacja (nazwa, rodzic_id) VALUES (?, ?)",
                               (nazwa, rodzic)).lastrowid

    def oczekuj_bledu(self, klucz, funkcja, *argumenty, **nazwane):
        with self.assertRaises(sqlite3.IntegrityError) as kontekst:
            funkcja(*argumenty, **nazwane)
        self.assertEqual(klucz, klucz_bledu_bazy(kontekst.exception)[0])


class TestSchematu(BazaTestowa):
    def test_wersja_i_klucze_obce(self):
        self.assertGreaterEqual(biezaca_wersja(self.db), 1)
        self.assertEqual(1, self.db.execute("PRAGMA foreign_keys").fetchone()[0])

    def test_dane_startowe_idempotentne(self):
        self.assertEqual(0, dane_startowe.wypelnij(self.db))

    def test_hierarchia_kategorii(self):
        wiersz = self.db.execute(
            "SELECT r.kod FROM kategoria k JOIN kategoria r ON r.id = k.rodzic_id "
            "WHERE k.kod = 'karty_dzwiekowe'").fetchone()
        self.assertEqual("czesci", wiersz[0])

    def test_znacznik_zmieniono(self):
        e = self.egzemplarz()
        self.db.execute("UPDATE egzemplarz SET zmieniono = '2000-01-01 00:00:00' WHERE id = ?", (e,))
        self.assertEqual("2000-01-01 00:00:00", self.db.execute(
            "SELECT zmieniono FROM egzemplarz WHERE id = ?", (e,)).fetchone()[0])
        self.db.execute("UPDATE egzemplarz SET uwagi = 'recap' WHERE id = ?", (e,))
        self.assertNotEqual("2000-01-01 00:00:00", self.db.execute(
            "SELECT zmieniono FROM egzemplarz WHERE id = ?", (e,)).fetchone()[0])

    def test_model_bez_producenta_nie_dubluje_sie(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='karty_dzwiekowe'").fetchone()[0]
        sql = "INSERT INTO model (kategoria_id, nazwa) VALUES (?, 'Sound Blaster 16')"
        self.db.execute(sql, (kat,))
        self.oczekuj_bledu("blad.duplikat", self.db.execute, sql, (kat,))


class TestPartii(BazaTestowa):
    def test_partia_bez_numeru_seryjnego(self):
        self.oczekuj_bledu("blad.partia_bez_seryjnego_i_montazu",
                           self.egzemplarz, ilosc=50, numer_seryjny="X1")

    def test_partia_nie_moze_byc_rodzicem(self):
        partia = self.egzemplarz(ilosc=10)
        self.oczekuj_bledu("blad.partia_jako_rodzic", self.egzemplarz, rodzic_id=partia)

    def test_rodzic_z_dziecmi_nie_stanie_sie_partia(self):
        pc = self.egzemplarz()
        self.egzemplarz(rodzic_id=pc)
        self.oczekuj_bledu("blad.partia_z_zamontowanymi", self.db.execute,
                           "UPDATE egzemplarz SET ilosc = 5 WHERE id = ?", (pc,))

    def test_cykl_prosty(self):
        e = self.egzemplarz()
        self.oczekuj_bledu("blad.cykl_montazu", self.db.execute,
                           "UPDATE egzemplarz SET rodzic_id = id WHERE id = ?", (e,))


class TestLokalizacji(BazaTestowa):
    def test_zamontowany_bez_wlasnej_lokalizacji(self):
        lok = self.lokalizacja("Regał A")
        pc = self.egzemplarz(lokalizacja_id=lok)
        self.oczekuj_bledu("blad.zamontowany_bez_lokalizacji",
                           self.egzemplarz, rodzic_id=pc, lokalizacja_id=lok)

    def test_lokalizacja_dziedziczona_przez_drzewo(self):
        pudelko = self.lokalizacja("Pudełko #12")
        pc = self.egzemplarz(lokalizacja_id=pudelko)
        plyta = self.egzemplarz(rodzic_id=pc)
        procesor = self.egzemplarz(rodzic_id=plyta)
        wiersz = self.db.execute(
            "SELECT korzen_id, lokalizacja_id FROM v_egzemplarz_lokalizacja "
            "WHERE egzemplarz_id = ?", (procesor,)).fetchone()
        self.assertEqual((pc, pudelko), tuple(wiersz))

    def test_sciezka_lokalizacji(self):
        a = self.lokalizacja("Regał A")
        p = self.lokalizacja("Półka 2", a)
        b = self.lokalizacja("Pudełko #12", p)
        sciezka = self.db.execute("SELECT sciezka FROM v_lokalizacja_sciezka "
                                  "WHERE lokalizacja_id = ?", (b,)).fetchone()[0]
        self.assertEqual("Regał A › Półka 2 › Pudełko #12", sciezka)


class TestPozostalychRegul(BazaTestowa):
    def test_cena_wymaga_waluty(self):
        self.oczekuj_bledu("blad.cena_wymaga_waluty", self.egzemplarz, cena_minor=19999)
        self.egzemplarz(cena_minor=19999, waluta_kod="PLZ")

    def test_zasob_dokladnie_jedno_powiazanie(self):
        zasob = self.db.execute("INSERT INTO zasob (typ, tytul, url) "
                                "VALUES ('instrukcja', 'SB16 manual', 'https://example.org')").lastrowid
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='karty_dzwiekowe'").fetchone()[0]
        e = self.egzemplarz()
        self.db.execute("INSERT INTO zasob_powiazanie (zasob_id, kategoria_id) VALUES (?, ?)", (zasob, kat))
        self.oczekuj_bledu("blad.zasob_jedno_powiazanie", self.db.execute,
                           "INSERT INTO zasob_powiazanie (zasob_id, kategoria_id, egzemplarz_id) "
                           "VALUES (?, ?, ?)", (zasob, kat, e))
        self.oczekuj_bledu("blad.duplikat", self.db.execute,
                           "INSERT INTO zasob_powiazanie (zasob_id, kategoria_id) VALUES (?, ?)",
                           (zasob, kat))

    def test_podtyp_tylko_dla_napraw(self):
        e = self.egzemplarz()
        sql = "INSERT INTO zdarzenie (egzemplarz_id, typ, podtyp) VALUES (?, ?, ?)"
        self.db.execute(sql, (e, "naprawa", "modyfikacja"))
        self.oczekuj_bledu("blad.zdarzenie_podtyp", self.db.execute, sql, (e, "test", "naprawa"))
        self.oczekuj_bledu("blad.zdarzenie_podtyp", self.db.execute, sql, (e, "naprawa", None))

    def test_transakcja_wycofuje_calosc(self):
        przed = self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            with transakcja(self.db):
                self.egzemplarz()
                self.egzemplarz(cena_minor=100)   # brak waluty
        self.assertEqual(przed, self.db.execute("SELECT COUNT(*) FROM egzemplarz").fetchone()[0])


class TestMigracji(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.schemat = self.tmp / "schemat"
        self.schemat.mkdir()
        shutil.copy(KATALOG_SCHEMATU / "001_poczatkowy.sql", self.schemat)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_nieudana_migracja_nie_zostawia_sladow(self):
        db = otworz_baze(":memory:")
        migruj(db, katalog=self.schemat)
        (self.schemat / "002_zepsuta.sql").write_text(
            "CREATE TABLE polowiczna (a INTEGER);\nINSERT INTO nie_istnieje VALUES (1);",
            encoding="utf-8")
        with self.assertRaises(sqlite3.OperationalError):
            migruj(db, katalog=self.schemat)
        self.assertEqual(1, biezaca_wersja(db))
        self.assertIsNone(db.execute(
            "SELECT name FROM sqlite_master WHERE name='polowiczna'").fetchone())

    def test_kopia_przed_migracja_istniejacej_bazy(self):
        plik = self.tmp / "kolekcja.sqlite3"
        db = otworz_baze(plik)
        migruj(db, self.tmp / "kopie", self.schemat)
        (self.schemat / "002_dodatek.sql").write_text(
            "ALTER TABLE producent ADD COLUMN kraj TEXT;", encoding="utf-8")
        zastosowane, kopia = migruj(db, self.tmp / "kopie", self.schemat)
        self.assertEqual([2], zastosowane)
        self.assertTrue(kopia and kopia.exists())
        db.close()

    def test_baza_nowsza_niz_program(self):
        db = otworz_baze(":memory:")
        migruj(db, katalog=self.schemat)
        db.execute("INSERT INTO wersja_schematu (wersja, zastosowano) VALUES (99, CURRENT_TIMESTAMP)")
        with self.assertRaises(BladNornicy) as kontekst:
            migruj(db, katalog=self.schemat)
        self.assertEqual("blad.baza_nowsza", kontekst.exception.klucz)


if __name__ == "__main__":
    unittest.main()
