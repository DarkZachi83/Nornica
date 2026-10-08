# SPDX-License-Identifier: GPL-3.0-or-later
"""Przeniesienie do innej kategorii. Zgłoszenie: Atari 2600 wpisane jako komputer
fabryczny; zmiana kategorii na konsolę odłączała model i parametry znikały."""
import json
import unittest
from unittest import mock

from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from testy.test_uslugi import Kolekcja
from uslugi import inwentarz, przeniesienie
from wyjatki import BladNornicy


def atari_2600(test):
    test.komputery = test.kat("komputery_fabryczne")
    test.konsole = test.kat("konsole")
    test.atari = inwentarz.zapisz_model(test.db, {
        "kategoria_id": test.komputery, "producent": "Atari", "nazwa": "2600",
        "atrybuty": {"procesor": "MOS 6507", "taktowanie_mhz": 1.19, "pamiec": 128, "norma_tv": "PAL",
                     "zasilacz_oryginalny": True, "wlasny_parametr": "spoza szablonu"}})
    test.egz = test.nowy(model_id=test.atari, kategoria_id=None, atrybuty={"pamiec": 256})


class TestUslugi(Kolekcja):
    def setUp(self):
        super().setUp()
        atari_2600(self)

    def atrybuty(self, tabela, id_):
        tekst = self.db.execute(f"SELECT atrybuty FROM {tabela} WHERE id = ?", (id_,)).fetchone()[0]
        return json.loads(tekst) if tekst else {}

    def test_podglad(self):
        p = przeniesienie.podglad(self.db, self.konsole, model_id=self.atari, jezyk="pl")
        self.assertEqual(1, p["egzemplarzy"])
        zachowane = {z["etykieta"]: z["wartosci"] for z in p["zachowane"]}
        self.assertEqual("MOS 6507", zachowane["Procesor"])
        self.assertEqual("128 B, 256 B", zachowane["Pamięć RAM"])       # model i egzemplarz
        self.assertEqual("Tak", zachowane["Oryginalny zasilacz"])
        self.assertEqual([{"etykieta": "Norma TV", "wartosci": "PAL"}], p["usuwane"])

    def test_przeniesienie_modelu_z_egzemplarzami(self):
        przeniesienie.przenies(self.db, self.konsole, model_id=self.atari)
        self.assertEqual(self.konsole, self.db.execute(
            "SELECT kategoria_id FROM model WHERE id = ?", (self.atari,)).fetchone()[0])
        model = self.atrybuty("model", self.atari)
        self.assertNotIn("norma_tv", model)                              # brak odpowiednika
        self.assertEqual("MOS 6507", model["procesor"])
        self.assertEqual("spoza szablonu", model["wlasny_parametr"])     # spoza szablonu — nietknięty
        self.assertEqual({"pamiec": 256}, self.atrybuty("egzemplarz", self.egz))
        kategoria = self.db.execute("SELECT kategoria_id FROM v_egzemplarz_kategoria WHERE egzemplarz_id = ?",
                                    (self.egz,)).fetchone()[0]
        self.assertEqual(self.konsole, kategoria)                         # egzemplarz poszedł z modelem

    def test_ta_sama_kategoria_bez_zmian(self):
        self.assertEqual(0, przeniesienie.przenies(self.db, self.komputery, model_id=self.atari))
        self.assertIn("norma_tv", self.atrybuty("model", self.atari))

    def test_egzemplarz_z_modelem_przenosi_sie_przez_model(self):
        with self.assertRaises(BladNornicy) as k:
            przeniesienie.przenies(self.db, self.konsole, egz_id=self.egz)
        self.assertEqual("blad.przenies_model", k.exception.klucz)

    def test_egzemplarz_bez_modelu(self):
        e = self.nowy(nazwa_wlasna="Klon 2600", kategoria_id=self.komputery,
                      atrybuty={"procesor": "6507", "norma_tv": "NTSC"})
        przeniesienie.przenies(self.db, self.konsole, egz_id=e)
        self.assertEqual({"procesor": "6507"}, self.atrybuty("egzemplarz", e))

    def test_wartosc_spoza_nowej_listy_do_sprawdzenia(self):
        akcesoria = self.kat("akcesoria")
        szablon = json.loads(self.db.execute("SELECT szablon_atrybutow FROM kategoria WHERE id = ?",
                                             (akcesoria,)).fetchone()[0] or "[]")
        szablon.append({"kod": "norma_tv", "typ": "enum", "wartosci": ["NTSC"], "nazwy": {"pl": "Norma TV"}})
        self.db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?", (json.dumps(szablon), akcesoria))
        p = przeniesienie.podglad(self.db, akcesoria, model_id=self.atari, jezyk="pl")
        self.assertEqual(["Norma TV"], [x["etykieta"] for x in p["do_sprawdzenia"]])

    def test_zmiana_kategorii_w_formularzu_modelu_porzadkuje_egzemplarze(self):
        self.db.execute("UPDATE egzemplarz SET atrybuty = ? WHERE id = ?",
                        (json.dumps({"pamiec": 256, "norma_tv": "NTSC"}), self.egz))
        inwentarz.zapisz_model(self.db, {"kategoria_id": self.konsole, "producent": "Atari", "nazwa": "2600",
                                         "atrybuty": {"procesor": "MOS 6507"}}, self.atari)
        self.assertEqual({"pamiec": 256}, self.atrybuty("egzemplarz", self.egz))


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOkien(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.kat = lambda kod: self.db.execute("SELECT id FROM kategoria WHERE kod = ?", (kod,)).fetchone()[0]
        self.nowy = lambda **d: inwentarz.zapisz_egzemplarz(self.db, {
            "status_id": self.db.execute("SELECT id FROM status WHERE kod = 'dziala'").fetchone()[0], **d})
        atari_2600(self)
        self.okno.odswiez()

    def test_odmowa_nie_odlacza_modelu(self):
        """Dokładnie scenariusz ze zgłoszenia — ale model zostaje."""
        formularz = self.okno.edytuj_egzemplarz(self.egz)
        self.okno.update()
        formularz.kategoria.ustaw(self.konsole)
        with mock.patch("tkinter.messagebox.askyesno", return_value=False) as pytanie:
            formularz._kategoria_zmieniona(self.konsole)
        self.assertIn("2600", pytanie.call_args[0][1])
        self.assertEqual(self.komputery, formularz.kategoria.wartosc)     # kategoria cofnięta
        self.assertEqual(self.atari, formularz.model.wartosc)            # model NIE odłączony

    def test_przeniesienie_z_formularza(self):
        from gui.okno_przeniesienia import OknoPrzeniesienia
        formularz = self.okno.edytuj_egzemplarz(self.egz)
        self.okno.update()
        formularz.kategoria.ustaw(self.konsole)
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            formularz._kategoria_zmieniona(self.konsole)
        okno = next(d for d in self.okno._dialogi if isinstance(d, OknoPrzeniesienia))
        self.okno.update()
        self.assertEqual(self.konsole, okno.cel.wartosc)
        from baza.repozytoria import slowniki
        from i18n.tlumacz import nazwa
        norma = nazwa(next(p for p in slowniki.szablon(self.db, self.komputery) if p["kod"] == "norma_tv")["nazwy"])
        self.assertIn(f"{norma}: PAL", okno._podglad.get("1.0", "end"))   # podgląd przed zmianą
        okno.przenies()
        self.okno.update()
        self.assertEqual(self.konsole, formularz.kategoria.wartosc)
        self.assertEqual(self.atari, formularz.model.wartosc)            # ten sam model, nowa kategoria

    def test_menu_kontekstowe_drzewa(self):
        okno = self.okno.przenies_kategorie(self.egz)
        self.assertEqual(self.atari, okno.model_id)                      # egzemplarz z modelem: przenosi model
        self.okno.update()
        self.assertEqual("disabled", str(okno._przycisk.cget("state")))  # bez wyboru — nie da się przenieść
        okno.cel.ustaw(self.konsole)
        okno._odswiez_podglad()
        self.assertEqual("normal", str(okno._przycisk.cget("state")))

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
