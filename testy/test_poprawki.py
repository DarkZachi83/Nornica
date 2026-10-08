# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy poprawek z drugiej recenzji schematu:
ON DELETE, znaczniki zmian w relacjach, kolacje, NULL w widoku lokalizacji,
liczniki kodów, strażnik zamrożonych migracji."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from baza.migracje import KATALOG_SCHEMATU, migruj
from baza.polaczenie import klucz_sortowania, otworz_baze, transakcja
from baza.repozytoria.kody import nastepny_kod
from baza.zaleznosci import opis, tabele_zrodlowe, zaleznosci
from i18n.tlumacz import ma_klucz
from testy.test_baza import BazaTestowa
from wyjatki import BladNornicy

STARA_DATA = "2000-01-01 00:00:00.000"


class TestUsuwania(BazaTestowa):
    def kategoria_id(self, kod):
        return self.db.execute("SELECT id FROM kategoria WHERE kod = ?", (kod,)).fetchone()[0]

    def test_kategoria_z_podkategoriami_zablokowana(self):
        czesci = self.kategoria_id("czesci")
        blokujace, _ = zaleznosci(self.db, "kategoria", czesci)
        self.assertGreater(blokujace[("kategoria", "rodzic_id")], 10)
        self.oczekuj_bledu("blad.klucz_obcy", self.db.execute,
                           "DELETE FROM kategoria WHERE id = ?", (czesci,))

    def test_kategoria_z_modelem_zablokowana(self):
        kat = self.kategoria_id("karty_dzwiekowe")
        self.db.execute("INSERT INTO model (kategoria_id, nazwa) VALUES (?, 'SB16')", (kat,))
        blokujace, _ = zaleznosci(self.db, "kategoria", kat)
        self.assertEqual({("model", "kategoria_id"): 1}, blokujace)
        self.assertEqual("Modele: 1", opis(blokujace, "pl"))

    def test_lokalizacja_z_zawartoscia_zablokowana(self):
        regal = self.lokalizacja("Regał A")
        self.lokalizacja("Półka 1", regal)
        self.egzemplarz(lokalizacja_id=regal)
        blokujace, _ = zaleznosci(self.db, "lokalizacja", regal)
        self.assertEqual({("lokalizacja", "rodzic_id"): 1, ("egzemplarz", "lokalizacja_id"): 1},
                         blokujace)

    def test_komputer_z_czesciami_zablokowany(self):
        pc = self.egzemplarz()
        self.egzemplarz(rodzic_id=pc)
        self.oczekuj_bledu("blad.klucz_obcy", self.db.execute,
                           "DELETE FROM egzemplarz WHERE id = ?", (pc,))

    def test_historia_usuwana_kaskadowo(self):
        e = self.egzemplarz()
        self.db.execute("INSERT INTO zdarzenie (egzemplarz_id, typ) VALUES (?, 'test')", (e,))
        blokujace, kaskadowe = zaleznosci(self.db, "egzemplarz", e)
        self.assertEqual({}, blokujace)
        self.assertEqual({("zdarzenie", "egzemplarz_id"): 1}, kaskadowe)
        self.db.execute("DELETE FROM egzemplarz WHERE id = ?", (e,))

    def test_kazda_tabela_zrodlowa_ma_tlumaczenie(self):
        for tabela in tabele_zrodlowe(self.db):
            with self.subTest(tabela=tabela):
                self.assertTrue(ma_klucz(f"tabela.{tabela}"))

    def test_kazdy_klucz_obcy_ma_jawna_regule(self):
        sql = "\n".join(p.read_text(encoding="utf-8")
                        for p in sorted(KATALOG_SCHEMATU.glob("*.sql")))
        for linia in sql.splitlines():
            if "REFERENCES" in linia:
                with self.subTest(linia=linia.strip()):
                    self.assertIn("ON DELETE", linia)


class TestZnacznikowRelacji(BazaTestowa):
    def postarz(self, tabela, id_):
        self.db.execute(f"UPDATE {tabela} SET zmieniono = ? WHERE id = ?", (STARA_DATA, id_))

    def zmieniono(self, tabela, id_):
        return self.db.execute(f"SELECT zmieniono FROM {tabela} WHERE id = ?", (id_,)).fetchone()[0]

    def nowy_model(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='plyty_glowne'").fetchone()[0]
        return self.db.execute("INSERT INTO model (kategoria_id, nazwa) VALUES (?, 'P5A')",
                               (kat,)).lastrowid

    def test_format_z_milisekundami(self):
        self.assertRegex(self.zmieniono("egzemplarz", self.egzemplarz()),
                         r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}$")

    def test_zlacze_modelu(self):
        m = self.nowy_model()
        zl = self.db.execute("SELECT id FROM zlacze_typ WHERE kod='isa16'").fetchone()[0]
        self.postarz("model", m)
        self.db.execute("INSERT INTO model_zlacze VALUES (?, ?, 'posiada', 3)", (m, zl))
        self.assertNotEqual(STARA_DATA, self.zmieniono("model", m))

    def test_powiazanie_i_edycja_zasobu(self):
        m = self.nowy_model()
        e = self.egzemplarz()
        z = self.db.execute("INSERT INTO zasob (typ, tytul, url) "
                            "VALUES ('sterownik', 'drv', 'https://x.org')").lastrowid
        self.db.execute("INSERT INTO zasob_powiazanie (zasob_id, model_id) VALUES (?, ?)", (z, m))
        self.db.execute("INSERT INTO zasob_powiazanie (zasob_id, egzemplarz_id) VALUES (?, ?)", (z, e))
        self.postarz("model", m)
        self.postarz("egzemplarz", e)
        self.db.execute("UPDATE zasob SET wersja = '4.13' WHERE id = ?", (z,))
        self.assertNotEqual(STARA_DATA, self.zmieniono("model", m))
        self.assertNotEqual(STARA_DATA, self.zmieniono("egzemplarz", e))
        # usunięcie zasobu kaskadowo usuwa powiązania i też podbija znacznik
        self.postarz("model", m)
        self.db.execute("DELETE FROM zasob WHERE id = ?", (z,))
        self.assertNotEqual(STARA_DATA, self.zmieniono("model", m))

    def test_zdarzenie(self):
        e = self.egzemplarz()
        self.postarz("egzemplarz", e)
        self.db.execute("INSERT INTO zdarzenie (egzemplarz_id, typ, wynik) VALUES (?, 'test', 'ok')", (e,))
        self.assertNotEqual(STARA_DATA, self.zmieniono("egzemplarz", e))

    def test_montaz_podbija_oba_komputery(self):
        pc1, pc2 = self.egzemplarz(), self.egzemplarz()
        karta = self.egzemplarz(rodzic_id=pc1)
        self.postarz("egzemplarz", pc1)
        self.postarz("egzemplarz", pc2)
        self.db.execute("UPDATE egzemplarz SET rodzic_id = ? WHERE id = ?", (pc2, karta))
        self.assertNotEqual(STARA_DATA, self.zmieniono("egzemplarz", pc1))
        self.assertNotEqual(STARA_DATA, self.zmieniono("egzemplarz", pc2))


class TestKolacji(BazaTestowa):
    def test_nocase_w_kolumnie(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='karty_dzwiekowe'").fetchone()[0]
        self.db.execute("INSERT INTO model (kategoria_id, nazwa, numer_czesci) "
                        "VALUES (?, 'Sound Blaster 16', 'CT2230')", (kat,))
        self.assertIsNotNone(self.db.execute(
            "SELECT 1 FROM model WHERE nazwa = 'sound blaster 16'").fetchone())
        self.oczekuj_bledu("blad.duplikat", self.db.execute,
                           "INSERT INTO model (kategoria_id, nazwa, numer_czesci) "
                           "VALUES (?, 'SOUND BLASTER 16', 'ct2230')", (kat,))

    def test_sortowanie_polskie(self):
        nazwy = ["Żółty składak", "zebra", "Łódź", "lampa", "Amiga", "ąb", "Ćma", "cyfra", "486DX2"]
        for n in nazwy:
            self.egzemplarz(nazwa_wlasna=n)
        wynik = [w[0] for w in self.db.execute(
            "SELECT nazwa_wlasna FROM egzemplarz ORDER BY nazwa_wlasna COLLATE NORNICA")]
        self.assertEqual(["486DX2", "Amiga", "ąb", "cyfra", "Ćma", "lampa", "Łódź",
                          "zebra", "Żółty składak"], wynik)

    def test_obce_diakrytyki_przy_literze_bazowej(self):
        self.assertLess(klucz_sortowania("Émile"), klucz_sortowania("Fujitsu"))


class TestWidokuLokalizacji(BazaTestowa):
    def test_korzen_bez_lokalizacji_daje_null(self):
        pc = self.egzemplarz()
        karta = self.egzemplarz(rodzic_id=pc)
        wiersz = self.db.execute("SELECT korzen_id, lokalizacja_id FROM v_egzemplarz_lokalizacja "
                                 "WHERE egzemplarz_id = ?", (karta,)).fetchone()
        self.assertEqual((pc, None), tuple(wiersz))


class TestKodow(BazaTestowa):
    def test_kolejne_kody(self):
        with transakcja(self.db):
            self.assertEqual("NOR-000001", nastepny_kod(self.db))
            self.assertEqual("NOR-000002", nastepny_kod(self.db))
            self.assertEqual("LOC-0001", nastepny_kod(self.db, "lokalizacja"))

    def test_numer_nie_wraca_po_usunieciu(self):
        with transakcja(self.db):
            kod = nastepny_kod(self.db)
            e = self.egzemplarz(kod_inwentarzowy=kod)
        self.db.execute("DELETE FROM egzemplarz WHERE id = ?", (e,))
        with transakcja(self.db):
            self.assertEqual("NOR-000002", nastepny_kod(self.db))

    def test_pomija_kod_wpisany_recznie(self):
        self.egzemplarz(kod_inwentarzowy="nor-000001")   # ręcznie, małymi literami
        with transakcja(self.db):
            self.assertEqual("NOR-000002", nastepny_kod(self.db))

    def test_wymaga_transakcji(self):
        with self.assertRaises(RuntimeError):
            nastepny_kod(self.db)

    def test_wycofana_transakcja_nie_zuzywa_numeru(self):
        with self.assertRaises(ZeroDivisionError):
            with transakcja(self.db):
                nastepny_kod(self.db)
                1 / 0
        with transakcja(self.db):
            self.assertEqual("NOR-000001", nastepny_kod(self.db))


class TestStraznikaMigracji(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.schemat = self.tmp / "schemat"
        self.schemat.mkdir()
        self.plik = self.schemat / "001_poczatkowy.sql"
        shutil.copy(KATALOG_SCHEMATU / "001_poczatkowy.sql", self.plik)
        self.db = otworz_baze(":memory:")
        migruj(self.db, katalog=self.schemat)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_zmieniona_migracja_wykryta(self):
        self.plik.write_text(self.plik.read_text(encoding="utf-8") + "\n-- poprawka\n",
                             encoding="utf-8")
        with self.assertRaises(BladNornicy) as kontekst:
            migruj(self.db, katalog=self.schemat)
        self.assertEqual("blad.migracja_zmieniona", kontekst.exception.klucz)

    def test_konwersja_crlf_nie_jest_zmiana(self):
        tresc = self.plik.read_bytes().replace(b"\n", b"\r\n")
        self.plik.write_bytes(tresc)
        self.assertEqual(([], None), migruj(self.db, katalog=self.schemat))


if __name__ == "__main__":
    unittest.main()
