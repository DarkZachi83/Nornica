# SPDX-License-Identifier: GPL-3.0-or-later
"""Inwentaryzacja telefonem: porównanie tego, co stoi na półce, z bazą."""
import unittest

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki
from i18n.tlumacz import t, ustaw_jezyk
from uslugi import inwentarz, inwentaryzacja as inw
from wyjatki import BladNornicy


class TestInwentaryzacji(unittest.TestCase):
    def setUp(self):
        ustaw_jezyk("en")
        self.db = otworz_baze(":memory:")
        self.addCleanup(self.db.close)
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        self.kat = self.db.execute("SELECT id FROM kategoria WHERE kod='skladaki_pc'").fetchone()[0]
        self.st = slowniki.status_id(self.db, "dziala")
        L = lambda n, r=None: inwentarz.zapisz_lokalizacje(self.db, {"nazwa": n, "rodzic_id": r})
        self.regal = L("Rack A")
        self.polka = L("Shelf 1", self.regal)
        self.pudlo = L("Box 7", self.polka)
        self.inny = L("Rack B")
        self.pc = self.egz("DOS 486", lokalizacja_id=self.polka)
        self.karta = self.egz("SB16", rodzic_id=self.pc)               # zamontowana w PC
        self.amiga = self.egz("Amiga 500", lokalizacja_id=self.regal)
        self.mysz = self.egz("Mouse", lokalizacja_id=self.pudlo)
        self.c64 = self.egz("C64", lokalizacja_id=self.inny)            # inny regał
        self.luzem = self.egz("Joystick")                                # bez miejsca

    def egz(self, nazwa, **dane):
        return inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": nazwa, "kategoria_id": self.kat,
                                                     "status_id": self.st, **dane})

    def kod(self, egz_id):
        return self.db.execute("SELECT kod_inwentarzowy FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()[0]

    def kod_lok(self, lok_id):
        return self.db.execute("SELECT kod_etykiety FROM lokalizacja WHERE id = ?", (lok_id,)).fetchone()[0]

    def test_oczekiwane_z_podlokalizacjami_bez_zamontowanych(self):
        self.assertEqual({self.pc, self.amiga, self.mysz}, set(inw.oczekiwane(self.db, self.regal)))
        self.assertEqual({self.pc, self.mysz}, set(inw.oczekiwane(self.db, self.polka)))

    def test_pelny_przebieg(self):
        s = inw.rozpocznij(self.db, self.regal)
        self.assertEqual("na_miejscu", inw.skanuj(self.db, s, self.kod(self.amiga))["wynik"])
        w = inw.skanuj(self.db, s, self.kod(self.mysz).lower() + " ")          # czytnik: małe litery, spacja
        self.assertEqual(("na_miejscu", True), (w["wynik"], w["w_podlokalizacji"]))
        w = inw.skanuj(self.db, s, self.kod(self.c64))
        self.assertEqual(("nie_na_miejscu", "Rack B"), (w["wynik"], w["miejsce"]))
        self.assertEqual(("nie_na_miejscu", None), (inw.skanuj(self.db, s, self.kod(self.luzem))["wynik"], None))
        self.assertEqual("juz", inw.skanuj(self.db, s, self.kod(self.amiga))["wynik"])
        self.assertEqual("nieznany", inw.skanuj(self.db, s, "NOR-999999")["wynik"])
        self.assertTrue(inw.skanuj(self.db, s, self.kod_lok(self.pudlo))["w_zakresie"])
        self.assertFalse(inw.skanuj(self.db, s, self.kod_lok(self.inny))["w_zakresie"])
        st = inw.stan(self.db, s)
        self.assertEqual((3, 2, 2, 1), (st["oczekiwane"], st["znalezione"], st["nie_na_miejscu"], st["brak"]))

        r = inw.zakoncz(self.db, s)
        brak = [p for p in r["pozycje"] if p["wynik"] == "brak"]
        self.assertEqual([self.pc], [p["egzemplarz_id"] for p in brak])
        self.assertEqual("Rack A › Shelf 1", brak[0]["miejsce"])
        self.assertEqual((2, 2, 1), (r["stan"]["na_miejscu"], r["stan"]["nie_na_miejscu"], r["stan"]["brak"]))
        self.assertIsNotNone(r["stan"]["zakonczono"])
        # baza egzemplarzy bez zmian — tylko raport
        self.assertEqual(self.inny, self.db.execute("SELECT lokalizacja_id FROM egzemplarz WHERE id = ?",
                                                    (self.c64,)).fetchone()[0])
        with self.assertRaises(BladNornicy):
            inw.skanuj(self.db, s, self.kod(self.pc))                          # sesja zamknięta

    def test_czesc_zamontowana_oznacza_caly_zestaw(self):
        s = inw.rozpocznij(self.db, self.polka)
        w = inw.skanuj(self.db, s, self.kod(self.karta))
        self.assertEqual(("na_miejscu", self.pc), (w["wynik"], w["zamontowany_w"]))
        r = inw.zakoncz(self.db, s)
        self.assertEqual([self.mysz], [p["egzemplarz_id"] for p in r["pozycje"] if p["wynik"] == "brak"])

    def test_anulowanie_i_usuniecie_lokalizacji(self):
        s = inw.rozpocznij(self.db, self.inny)
        inw.anuluj(self.db, s)
        self.assertEqual([], inw.sesje(self.db))
        s = inw.rozpocznij(self.db, self.inny)
        inw.skanuj(self.db, s, self.kod(self.c64))
        inw.zakoncz(self.db, s)
        inwentarz.usun_egzemplarz(self.db, self.c64)
        inwentarz.usun_lokalizacje(self.db, self.inny)
        sesja = inw.sesje(self.db)[0]
        self.assertEqual(("Rack B", None, 0), (sesja["lokalizacja_nazwa"], sesja["lokalizacja_id"],
                                                sesja["na_miejscu"]))

    def test_telefon(self):
        start = inw.obsluga_telefonu(self.db, {"akcja": "start", "kod": self.kod_lok(self.regal)})
        s = start["sesja"]
        self.assertEqual(t("inw.tel.postep", znalezione=0, oczekiwane=3), start["postep"])
        odp = inw.obsluga_telefonu(self.db, {"akcja": "skan", "sesja": str(s), "kod": self.kod(self.c64)})
        self.assertEqual(t("inw.tel.nie_na_miejscu", miejsce="Rack B"), odp["skan"]["tekst"])
        self.assertEqual("C64", odp["stan"]["pozycje"][0]["nazwa"])
        with self.assertRaises(BladNornicy):
            inw.obsluga_telefonu(self.db, {"akcja": "start", "kod": self.kod(self.pc)})   # nie lokalizacja
        koniec = inw.obsluga_telefonu(self.db, {"akcja": "koniec", "sesja": s})
        self.assertEqual(3, len(koniec["raport"]["grupy"]["brak"]))
        self.assertEqual(1, len(koniec["raport"]["grupy"]["nie_na_miejscu"]))


if __name__ == "__main__":
    unittest.main()


from testy import test_gui   # noqa: E402 — moduł, nie klasa: inaczej jej testy uruchomiłyby się drugi raz


@unittest.skipUnless(test_gui.EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOknaInwentaryzacji(test_gui.TestPrzebudowy):
    def test_wyniki_z_telefonu_na_zywo_i_po_zmianie_jezyka(self):
        from unittest import mock
        okno = self.okno.inwentaryzacje()
        self.assertIs(okno, self.okno.inwentaryzacje())
        self.assertEqual(t("inw.brak_sesji"), okno._podsumowanie.cget("text"))
        kod_regalu = self.db.execute("SELECT kod_etykiety FROM lokalizacja WHERE id = ?", (self.regal,)).fetchone()[0]
        start = self.okno._obsluga_mostu("inwentaryzacja", {"akcja": "start", "kod": kod_regalu})
        self.okno.update()
        self.assertEqual([str(start["sesja"])], list(okno._lista.get_children()))
        kod_karty = self.db.execute("SELECT kod_inwentarzowy FROM egzemplarz WHERE id = ?", (self.karta,)).fetchone()[0]
        self.okno._obsluga_mostu("inwentaryzacja", {"akcja": "skan", "sesja": start["sesja"], "kod": kod_karty})
        self.okno.update()
        self.assertEqual(("na_miejscu",), okno._raport.get_children())
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertIn(t("inw.grupa.na_miejscu"), okno._raport.item("na_miejscu", "text"))
        okno._raport.selection_set(f"na_miejscu:{self.karta}")
        okno.update()
        okno.pokaz_egzemplarz()
        self.assertEqual((f"E{self.karta}",), self.drzewo().selection())
        self.okno._obsluga_mostu("inwentaryzacja", {"akcja": "koniec", "sesja": start["sesja"]})
        self.okno.update()
        self.assertIsNotNone(okno.sesje[0]["zakonczono"])
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            okno.usun_sesje()
        self.assertEqual([], list(okno._lista.get_children()))
