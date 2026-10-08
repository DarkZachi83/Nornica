# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy pojemności z jednostką: formatowanie, migracja 005 starej bazy,
migracje w Pythonie (strażnik, wycofanie), formularz (Atari 2600: 128 B)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from baza import dane_startowe
from baza.migracje import KATALOG_SCHEMATU, biezaca_wersja, migruj
from baza.polaczenie import otworz_baze
from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from uslugi.formatowanie import pojemnosc_na_tekst, rozbij_pojemnosc, tekst_na_bajty
from wyjatki import BladNornicy


class TestFormatowania(unittest.TestCase):
    def test_dobor_jednostki(self):
        self.assertEqual("128 B", pojemnosc_na_tekst(128, "pl"))           # Atari 2600
        self.assertEqual("64 KB", pojemnosc_na_tekst(65536, "pl"))          # C64
        self.assertEqual("1,41 MB", pojemnosc_na_tekst(1474560, "pl"))      # dyskietka „1,44”
        self.assertEqual("1.41 MB", pojemnosc_na_tekst(1474560, "en"))
        self.assertEqual("4 GB", pojemnosc_na_tekst(4 * 1024 ** 3, "pl"))
        self.assertEqual("2048 GB", pojemnosc_na_tekst(2 * 1024 ** 4, "pl"))    # bez TB — retro
        self.assertEqual(("", "KB"), rozbij_pojemnosc(None))

    def test_odczyt_wpisu(self):
        self.assertEqual(128, tekst_na_bajty("128", "B"))
        self.assertEqual(65536, tekst_na_bajty("64", "KB"))
        self.assertEqual(524288, tekst_na_bajty("0,5", "MB"))
        for zle in (("abc", "KB"), ("-1", "KB"), ("1", "PB"), ("1", "TB"), ("", "KB")):
            with self.subTest(wpis=zle), self.assertRaises(ValueError):
                tekst_na_bajty(*zle)


class TestMigracji005(unittest.TestCase):
    """Baza sprzed zmiany: migracje 001–004 i stare pola (KB, MB) z danymi."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stare = self.tmp / "stare"
        self.stare.mkdir()
        for plik in sorted(KATALOG_SCHEMATU.glob("00[1-4]_*.sql")):
            shutil.copy(plik, self.stare)
        self.db = otworz_baze(":memory:")
        migruj(self.db, katalog=self.stare)
        self.assertEqual(4, biezaca_wersja(self.db))
        # szablony i dane w starym kształcie
        stare_pole = {"kod": "pamiec_kb", "typ": "int", "jednostka": "KB", "nazwy": {"en": "RAM", "pl": "Pamięć RAM"}}
        self.db.execute("INSERT INTO kategoria (kod, rodzaj, nazwy, szablon_atrybutow) VALUES "
                        "('komputery_fabryczne', 'komputer_fabryczny', '{\"pl\": \"K\"}', ?)",
                        (json.dumps([{"kod": "procesor", "typ": "text", "nazwy": {"pl": "Procesor"}}, stare_pole]),))
        self.db.execute("INSERT INTO kategoria (kod, rodzaj, nazwy, szablon_atrybutow) VALUES "
                        "('pamieci_ram', 'czesc', '{\"pl\": \"R\"}', ?)",
                        (json.dumps([{"kod": "pojemnosc_mb", "typ": "real", "jednostka": "MB",
                                      "nazwy": {"pl": "Pojemność"}}]),))
        self.db.execute("INSERT INTO status (kod, nazwy) VALUES ('dziala', '{\"pl\": \"Działa\"}')")
        self.db.execute("INSERT INTO model (kategoria_id, nazwa, atrybuty) VALUES (1, 'C64', ?)",
                        (json.dumps({"procesor": "6510", "pamiec_kb": 64}),))
        self.db.execute("INSERT INTO model (kategoria_id, nazwa, atrybuty) VALUES (2, 'SIMM', ?)",
                        (json.dumps({"pojemnosc_mb": 0.5}),))
        self.db.execute("INSERT INTO egzemplarz (model_id, status_id, atrybuty) VALUES (1, 1, ?)",
                        (json.dumps({"pamiec_kb": 320}),))

    def atrybuty(self, tabela, id_):
        return json.loads(self.db.execute(f"SELECT atrybuty FROM {tabela} WHERE id = ?", (id_,)).fetchone()[0])

    def test_przeliczenie_wartosci_i_szablonow(self):
        self.assertEqual(5, migruj(self.db)[0][0])          # 005 jako pierwsza z oczekujących
        self.assertEqual({"procesor": "6510", "pamiec": 65536}, self.atrybuty("model", 1))
        self.assertEqual({"pojemnosc": 524288}, self.atrybuty("model", 2))
        self.assertEqual({"pamiec": 327680}, self.atrybuty("egzemplarz", 1))
        szablon = json.loads(self.db.execute("SELECT szablon_atrybutow FROM kategoria WHERE id = 1").fetchone()[0])
        self.assertEqual({"kod": "pamiec", "typ": "pojemnosc", "nazwy": {"en": "RAM", "pl": "Pamięć RAM"}}, szablon[1])

    def test_uzupelnienie_szablonow_bez_duplikatow(self):
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        szablon = json.loads(self.db.execute(
            "SELECT szablon_atrybutow FROM kategoria WHERE kod = 'komputery_fabryczne'").fetchone()[0])
        kody = [p["kod"] for p in szablon]
        self.assertEqual(1, kody.count("pamiec"))
        self.assertNotIn("pamiec_kb", kody)
        self.assertEqual(([], None), migruj(self.db))                  # drugi raz: nic do zrobienia

    def test_migracja_python_wycofywana_w_calosci(self):
        katalog = self.tmp / "zle"
        shutil.copytree(self.stare, katalog)
        (katalog / "005_zla.py").write_text(
            "def migruj(db):\n"
            "    db.execute(\"UPDATE model SET nazwa = 'ZMIENIONE' WHERE id = 1\")\n"
            "    raise RuntimeError('błąd w połowie')\n", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            migruj(self.db, katalog=katalog)
        self.assertEqual(4, biezaca_wersja(self.db))
        self.assertEqual("C64", self.db.execute("SELECT nazwa FROM model WHERE id = 1").fetchone()[0])

    def test_straznik_obejmuje_migracje_python(self):
        katalog = self.tmp / "kopia"
        shutil.copytree(self.stare, katalog)
        shutil.copy(KATALOG_SCHEMATU / "005_pojemnosc_w_bajtach.py", katalog)
        migruj(self.db, katalog=katalog)
        plik = katalog / "005_pojemnosc_w_bajtach.py"
        plik.write_text(plik.read_text(encoding="utf-8") + "\n# zmiana po zastosowaniu\n", encoding="utf-8")
        with self.assertRaises(BladNornicy) as k:
            migruj(self.db, katalog=katalog)
        self.assertEqual("blad.migracja_zmieniona", k.exception.klucz)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestPolaPojemnosci(TestPrzebudowy):
    def test_atari_2600_128_bajtow(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = 'konsole'").fetchone()[0]
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self.okno, None, kategoria_id=kat)
        okno.pokaz()
        okno.v["nazwa"].set("2600 Jr.")
        okno._notatnik.select(1)
        pole = okno.atrybuty._pole(next(p for p in okno.atrybuty._opisy.values() if p["kod"] == "pamiec"))
        pole.liczba.set("128")
        pole.jednostka.ustaw("B")
        self.okno.przelacz_jezyk("pl")                       # wybór jednostki przeżywa przebudowę
        self.okno.update()
        self.assertEqual("B", pole.jednostka.widzet.get())
        okno.zapisz()
        atrybuty = json.loads(self.db.execute("SELECT atrybuty FROM model WHERE nazwa = '2600 Jr.'").fetchone()[0])
        self.assertEqual(128, atrybuty["pamiec"])
        from raporty.dane import opis_parametrow
        self.assertIn("Pamięć RAM: 128 B", opis_parametrow(self.db, kat, atrybuty, {}, "pl"))

    def test_zla_liczba_komunikat(self):
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = 'konsole'").fetchone()[0]
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self.okno, None, kategoria_id=kat)
        okno.pokaz()
        okno.v["nazwa"].set("X")
        pole = okno.atrybuty._pole(next(p for p in okno.atrybuty._opisy.values() if p["kod"] == "pamiec"))
        pole.liczba.set("sto")
        with mock.patch("tkinter.messagebox.showerror") as komunikat:
            okno.zapisz()
        from i18n.tlumacz import nazwa
        etykieta = nazwa(okno.atrybuty._opisy["pamiec"]["nazwy"])       # w bieżącym języku
        self.assertEqual(t("blad.wartosc_liczbowa", pole=etykieta), komunikat.call_args[0][1])

    def test_egzemplarz_dziedziczy_pojemnosc_w_dowolnej_jednostce(self):
        """Model: 64 KB. W egzemplarzu wpisane „65536 B” to ta sama wartość — nic nie zapisuje."""
        from uslugi import inwentarz
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod = 'komputery_fabryczne'").fetchone()[0]
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "C64", "atrybuty": {"pamiec": 65536}})
        okno = self.okno.nowy_egzemplarz()
        okno.kategoria.ustaw(kat)
        okno._kategoria_zmieniona(kat)
        okno.model.ustaw(m)
        okno._model_zmieniony(m)
        pole = okno.atrybuty.pola["pamiec"]
        self.assertEqual("64 KB", pole.tekst())                           # wypełnione z modelu
        pole.liczba.set("65536")
        pole.jednostka.ustaw("B")
        okno.zapisz()
        wiersz = self.db.execute("SELECT atrybuty FROM egzemplarz WHERE model_id = ?", (m,)).fetchone()[0]
        self.assertIsNone(wiersz)                                         # równe modelowi: brak nadpisania

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
