# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy interfejsu. Wymagają ekranu — na serwerze: xvfb-run python -m unittest ...
Bez ekranu są pomijane.

Najważniejszy jest test przebudowy (lekcja z Jaźwca): przełączenie języka
tam i z powrotem nie może zgubić stanu okna ani danych wpisanych w otwartym
oknie dialogowym, a po przebudowie nic nie może sięgać po zniszczone widżety.
"""
import tkinter as tk
import unittest

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import slowniki
from i18n.tlumacz import t, ustaw_jezyk
from uslugi import inwentarz

try:
    _proba = tk.Tk()
    _proba.destroy()
    EKRAN = True
except tk.TclError:
    EKRAN = False


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestPrzebudowy(unittest.TestCase):
    def setUp(self):
        from gui.okno_glowne import OknoGlowne
        ustaw_jezyk("en")
        self.db = otworz_baze(":memory:")
        migruj(self.db)
        dane_startowe.wypelnij(self.db)
        kat = self.db.execute("SELECT id FROM kategoria WHERE kod='skladaki_pc'").fetchone()[0]
        st = slowniki.status_id(self.db, "dziala")
        self.regal = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Regał A", "typ": "regal"})
        self.polka = inwentarz.zapisz_lokalizacje(self.db, {"nazwa": "Półka 2", "rodzic_id": self.regal})
        self.pc = inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "DOS 486", "kategoria_id": kat,
                                                         "status_id": st, "lokalizacja_id": self.polka})
        self.karta = inwentarz.zapisz_egzemplarz(self.db, {"nazwa_wlasna": "SB16", "kategoria_id": kat,
                                                            "status_id": st, "rodzic_id": self.pc})
        self.kat_skladaki = kat
        # Modalny komunikat zawiesiłby test w oczekiwaniu na kliknięcie.
        # Nieoczekiwany komunikat ma przerwać test z czytelnym opisem.
        from unittest import mock
        def nieoczekiwany(*argumenty, **_):
            raise AssertionError(f"Nieoczekiwany komunikat: {argumenty}")
        for nazwa in ("showerror", "showwarning", "askyesno"):
            straznik = mock.patch(f"tkinter.messagebox.{nazwa}", side_effect=nieoczekiwany)
            straznik.start()
            self.addCleanup(straznik.stop)
        self.okno = OknoGlowne(self.db, pokaz_powitanie=False)
        self.okno.update()

    def tearDown(self):
        self.okno.destroy()
        # Sprzątanie pamięci TERAZ, w wątku głównym. Inaczej Python sprząta zmienne
        # tkintera z zamkniętych okien w losowym momencie — także w wątku serwera
        # telefonu w innym teście. Tkinter pozwala na wywołania tylko z wątku głównego,
        # więc wątek serwera czekał ~1 s na każdą zmienną i klient po 10 s rezygnował
        # (test serwera padał wyłącznie w pełnym zestawie testów).
        import gc
        gc.collect()
        self.db.close()
        ustaw_jezyk("en")

    def drzewo(self):
        return self.okno._widzety["drzewo"]

    def test_stan_przezywa_przelaczenie_tam_i_z_powrotem(self):
        drzewo = self.drzewo()
        for iid in ("L1", "L2", f"E{self.pc}"):
            drzewo.item(iid, open=True)
        drzewo.selection_set(f"E{self.karta}")
        self.okno.update()
        self.okno._widzety["szczegoly"].notatnik.select(1)
        self.okno.update()

        for jezyk, tytul, status in (("pl", "NORNICA", "Działa"), ("en", "VOLE", "Working"),
                                     ("pl", "NORNICA", "Działa")):
            self.okno.przelacz_jezyk(jezyk)
            self.okno.update()
            drzewo = self.drzewo()
            self.assertEqual(tytul, self.okno.title())
            self.assertEqual((f"E{self.karta}",), drzewo.selection())
            self.assertTrue(all(drzewo.item(i, "open") for i in ("L1", "L2", f"E{self.pc}")))
            self.assertEqual(1, self.okno._widzety["szczegoly"].zakladka())
            self.assertEqual(status, drzewo.item(f"E{self.karta}", "values")[1])
            self.assertEqual(t("kolumna.nazwa"), drzewo.heading("#0", "text"))

    def test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety(self):
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        # odświeżenie, filtr i zmiana trybu działają na nowych widżetach
        self.okno.odswiez()
        self.okno.filtr_var.set("SB16")
        self.okno._zastosuj_filtr()
        self.assertTrue(self.drzewo().exists(f"E{self.karta}"))
        self.okno.tryb_var.set("montaz")
        self.okno._tryb_zmieniony()
        self.assertFalse(self.drzewo().exists("L1"))

    def test_otwarte_okno_przezywa_przebudowe_z_danymi(self):
        okno = self.okno.edytuj_egzemplarz(self.pc)
        okno.v["numer_seryjny"].set("SN-12345")
        okno.uwagi.widzet.insert("end", "Wymienione kondensatory")
        okno.status.ustaw(slowniki.status_id(self.db, "w_naprawie"))
        okno._notatnik.select(2)
        self.okno.update()

        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertTrue(okno.winfo_exists())
        self.assertEqual(t("okno.egzemplarz_edycja"), okno.title())
        self.assertEqual("SN-12345", okno.v["numer_seryjny"].get())
        self.assertIn("Wymienione kondensatory", okno.uwagi.widzet.get("1.0", "end"))
        self.assertEqual("W naprawie", okno.status.widzet.get())
        self.assertEqual(2, okno._notatnik.index("current"))

        okno.zapisz()
        self.okno.update()
        self.assertFalse(okno.winfo_exists())
        wiersz = self.db.execute("SELECT numer_seryjny, uwagi FROM egzemplarz WHERE id = ?",
                                 (self.pc,)).fetchone()
        self.assertEqual("SN-12345", wiersz[0])
        self.assertIn("Wymienione kondensatory", wiersz[1])

    def test_dodanie_egzemplarza_przez_okno(self):
        okno = self.okno.nowy_egzemplarz(lokalizacja_id=self.regal)
        okno.v["nazwa_wlasna"].set("Amiga 1200")
        okno.kategoria.ustaw(self.kat_skladaki)
        okno.zapisz()
        self.okno.update()
        nowy = self.db.execute("SELECT id, lokalizacja_id, kod_inwentarzowy FROM egzemplarz "
                               "WHERE nazwa_wlasna = 'Amiga 1200'").fetchone()
        self.assertEqual(self.regal, nowy[1])
        self.assertEqual((f"E{nowy[0]}",), self.drzewo().selection())

    def test_blad_walidacji_nie_zamyka_okna(self):
        from unittest import mock
        okno = self.okno.nowy_egzemplarz()
        okno.kategoria.ustaw(None)
        with mock.patch("tkinter.messagebox.showerror") as komunikat:
            okno.zapisz()
        self.assertTrue(okno.winfo_exists())
        self.assertEqual(t("blad.wybierz_kategorie"), komunikat.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
