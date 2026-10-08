# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy poprawek z trzeciej recenzji: rekursja wyzwalaczy, wartość -1
w indeksie modeli, zasoby-sieroty."""
import unittest

from baza.migracje import biezaca_wersja
from baza.polaczenie import transakcja
from baza.repozytoria.zasoby import osierocone, usun_osierocone
from testy.test_baza import BazaTestowa


class TestRekursjiWyzwalaczy(BazaTestowa):
    def test_pragma_domyslnie_wylaczona(self):
        self.assertEqual(0, self.db.execute("PRAGMA recursive_triggers").fetchone()[0])

    def test_bez_petli_przy_wlaczonej_rekursji(self):
        # Odtworzenie błędu: dwie części montowane jednym poleceniem do tego
        # samego komputera. Przed migracją 002 kończyło się to wyjątkiem
        # 'too many levels of trigger recursion'.
        self.db.execute("PRAGMA recursive_triggers = ON")
        pc = self.egzemplarz()
        a, b = self.egzemplarz(), self.egzemplarz()
        self.db.execute("UPDATE egzemplarz SET rodzic_id = ? WHERE id IN (?, ?)", (pc, a, b))
        self.db.execute("UPDATE egzemplarz SET uwagi = 'x' WHERE id IN (?, ?, ?)", (pc, a, b))
        self.assertEqual(2, self.db.execute(
            "SELECT COUNT(*) FROM egzemplarz WHERE rodzic_id = ?", (pc,)).fetchone()[0])

    def test_znacznik_nadal_dziala(self):
        e = self.egzemplarz()
        self.db.execute("UPDATE egzemplarz SET zmieniono = '2000-01-01 00:00:00.000' WHERE id = ?", (e,))
        self.db.execute("UPDATE egzemplarz SET uwagi = 'recap' WHERE id = ?", (e,))
        self.assertNotEqual("2000-01-01 00:00:00.000", self.db.execute(
            "SELECT zmieniono FROM egzemplarz WHERE id = ?", (e,)).fetchone()[0])


class TestIndeksuModeli(BazaTestowa):
    def test_producent_z_id_zero_nie_koliduje_z_brakiem_producenta(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='karty_inne'").fetchone()[0]
        self.db.execute("INSERT INTO producent (id, nazwa) VALUES (0, 'Import ze starej bazy')")
        self.db.execute("INSERT INTO model (kategoria_id, producent_id, nazwa) VALUES (?, 0, 'X')", (kat,))
        self.db.execute("INSERT INTO model (kategoria_id, producent_id, nazwa) VALUES (?, NULL, 'X')", (kat,))
        self.oczekuj_bledu("blad.duplikat", self.db.execute,
                           "INSERT INTO model (kategoria_id, nazwa) VALUES (?, 'x')", (kat,))

    def test_wersja_schematu(self):
        self.assertGreaterEqual(biezaca_wersja(self.db), 2)


class TestSierot(BazaTestowa):
    def zasob(self, tytul, plik=None):
        return self.db.execute(
            "INSERT INTO zasob (typ, tytul, url, plik_sciezka) VALUES ('bios', ?, 'https://x.org', ?)",
            (tytul, plik)).lastrowid

    def test_sierota_po_usunieciu_egzemplarza(self):
        e = self.egzemplarz()
        z = self.zasob("BIOS 1.02", "ab/abcd.bin")
        self.db.execute("INSERT INTO zasob_powiazanie (zasob_id, egzemplarz_id) VALUES (?, ?)", (z, e))
        self.assertEqual([], osierocone(self.db))
        self.db.execute("DELETE FROM egzemplarz WHERE id = ?", (e,))
        self.assertEqual([z], [w["id"] for w in osierocone(self.db)])
        with transakcja(self.db):
            self.assertEqual(["ab/abcd.bin"], usun_osierocone(self.db, [z]))
        self.assertIsNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())

    def test_podpiety_w_miedzyczasie_nie_jest_usuwany(self):
        z = self.zasob("Sterownik")
        lista = [w["id"] for w in osierocone(self.db)]
        e = self.egzemplarz()
        self.db.execute("INSERT INTO zasob_powiazanie (zasob_id, egzemplarz_id) VALUES (?, ?)", (z, e))
        with transakcja(self.db):
            self.assertEqual([], usun_osierocone(self.db, lista))
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM zasob WHERE id = ?", (z,)).fetchone())

    def test_zapytanie_korzysta_z_indeksu(self):
        plan = " ".join(w[3] for w in self.db.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM zasob z WHERE NOT EXISTS "
            "(SELECT 1 FROM zasob_powiazanie p WHERE p.zasob_id = z.id)"))
        self.assertIn("ix_zp_zasob", plan)


if __name__ == "__main__":
    unittest.main()
