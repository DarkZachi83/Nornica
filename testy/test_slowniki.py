# SPDX-License-Identifier: GPL-3.0-or-later
"""Edytor słowników: własne kategorie, pola parametrów i statusy.
Wbudowane wpisy nienaruszalne, usuwanie chronione, dane przeżywają restart."""
import json
import unittest
from unittest import mock

from baza import dane_startowe
from baza.repozytoria import slowniki as repo
from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from testy.test_uslugi import Kolekcja
from uslugi import inwentarz
from uslugi import slowniki_edycja as edycja
from wyjatki import BladNornicy


class TestUslugi(Kolekcja):
    def blad(self, funkcja, *argumenty, **opcje):
        with self.assertRaises(BladNornicy) as k:
            funkcja(*argumenty, **opcje)
        return k.exception.klucz

    def test_wlasna_podkategoria_dziedziczy_rodzaj_i_pola(self):
        konsole = self.kat("konsole")
        przenosne = edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Konsole przenośne"}, "rodzic_id": konsole})
        wiersz = repo.kategoria(self.db, przenosne)
        self.assertEqual((None, repo.kategoria(self.db, konsole)["rodzaj"]), (wiersz["kod"], wiersz["rodzaj"]))
        self.assertEqual([p["kod"] for p in repo.szablon(self.db, konsole)],
                         [p["kod"] for p in repo.szablon(self.db, przenosne)])
        self.assertEqual("blad.duplikat", self.blad(edycja.zapisz_kategorie, self.db,
                                                    {"nazwy": {"en": "KONSOLE PRZENOŚNE"}, "rodzic_id": konsole}))

    def test_kategoria_glowna_wymaga_rodzaju_i_brak_cykli(self):
        self.assertEqual("blad.wybierz_rodzaj", self.blad(edycja.zapisz_kategorie, self.db, {"nazwy": {"pl": "Gry"}}))
        gry = edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Gry"}, "rodzaj": "akcesorium"})
        kartridze = edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Kartridże"}, "rodzic_id": gry})
        self.assertEqual("blad.kategoria_cykl", self.blad(edycja.zapisz_kategorie, self.db,
                                                          {"nazwy": {"pl": "Gry"}, "rodzic_id": kartridze}, gry))
        # zmiana rodzaju kategorii głównej obejmuje podkategorie
        edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Gry"}, "rodzaj": "czesc"}, gry)
        self.assertEqual("czesc", repo.kategoria(self.db, kartridze)["rodzaj"])

    def test_wbudowane_nienaruszalne(self):
        kat = self.kat("konsole")
        self.assertEqual("blad.slownik_wbudowany", self.blad(edycja.zapisz_kategorie, self.db, {"nazwy": {"pl": "X"}}, kat))
        self.assertEqual("blad.slownik_wbudowany", self.blad(edycja.usun_kategorie, self.db, kat))
        dziala = repo.status_id(self.db, "dziala")
        self.assertEqual("blad.slownik_wbudowany", self.blad(edycja.zapisz_status, self.db, {"pl": "X"}, dziala))
        self.assertEqual("blad.slownik_wbudowany", self.blad(edycja.usun_status, self.db, dziala))
        self.assertEqual("blad.slownik_wbudowany", self.blad(edycja.usun_pole, self.db, kat, "procesor"))

    def test_usuwanie_kategorii_w_uzyciu(self):
        kat = edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Moja"}, "rodzaj": "czesc"})
        e = self.nowy(nazwa_wlasna="X", kategoria_id=kat)
        self.assertEqual("blad.usuwanie_zablokowane", self.blad(edycja.usun_kategorie, self.db, kat))
        inwentarz.usun_egzemplarz(self.db, e)
        edycja.usun_kategorie(self.db, kat)
        self.assertIsNone(repo.kategoria(self.db, kat))

    def test_status_wlasny(self):
        s = edycja.zapisz_status(self.db, {"pl": "Wypożyczony", "en": "Lent out"})
        self.assertEqual("blad.duplikat", self.blad(edycja.zapisz_status, self.db, {"pl": "działa"}))
        e = self.nowy(nazwa_wlasna="X", kategoria_id=self.kat("akcesoria"), status_id=s)
        self.assertEqual("blad.usuwanie_zablokowane", self.blad(edycja.usun_status, self.db, s))
        inwentarz.usun_egzemplarz(self.db, e)
        edycja.usun_status(self.db, s)

    def test_pole_zycie(self):
        kat = self.kat("komputery_fabryczne")
        kod = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Pamięć ROM"}, "typ": "pojemnosc"})
        self.assertEqual("w_pamiec_rom", kod)
        self.assertEqual("blad.duplikat", self.blad(edycja.dodaj_pole, self.db, kat,
                                                    {"nazwy": {"en": "CPU"}, "typ": "text"}))   # jak wbudowany „Procesor”
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "65XE",
                                             "atrybuty": {kod: 24576, "procesor": "6502C"}})
        self.nowy(model_id=m, kategoria_id=None, atrybuty={kod: 32768})
        self.assertEqual({"model": 1, "egzemplarz": 1}, edycja.uzycie_pola(self.db, kat, kod))
        self.assertEqual("blad.pole_typ_w_uzyciu", self.blad(edycja.zapisz_pole, self.db, kat, kod,
                                                             {"nazwy": {"pl": "ROM"}, "typ": "text"}))
        edycja.zapisz_pole(self.db, kat, kod, {"nazwy": {"pl": "ROM systemu"}, "typ": "pojemnosc"})   # zmiana nazwy
        self.assertEqual(2, edycja.usun_pole(self.db, kat, kod))
        self.assertEqual({"procesor": "6502C"}, json.loads(self.db.execute(
            "SELECT atrybuty FROM model WHERE id = ?", (m,)).fetchone()[0]))
        self.assertNotIn(kod, [p["kod"] for p in repo.szablon(self.db, kat)])

    def test_pole_lista_i_kolejnosc(self):
        kat = self.kat("konsole")
        self.assertEqual("blad.lista_wartosci", self.blad(edycja.dodaj_pole, self.db, kat,
                                                          {"nazwy": {"pl": "Kolor"}, "typ": "enum", "wartosci": [" "]}))
        a = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Kolor"}, "typ": "enum",
                                             "wartosci": ["czarny", "Czarny", "biały", ""]})
        b = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Moc"}, "typ": "int", "jednostka": "W"})
        pola = {p["kod"]: p for p in repo.szablon(self.db, kat)}
        self.assertEqual(["czarny", "biały"], pola[a]["wartosci"])       # bez dubli i pustych
        self.assertEqual("W", pola[b]["jednostka"])
        edycja.przesun_pole(self.db, kat, b, -1)
        kody = [p["kod"] for p in repo.szablon(self.db, kat)]
        self.assertLess(kody.index(b), kody.index(a))

    def test_pole_rodzica_widoczne_w_podkategoriach(self):
        czesci = self.kat("czesci")
        kod = edycja.dodaj_pole(self.db, czesci, {"nazwy": {"pl": "Numer FRU"}, "typ": "text"})
        self.assertIn(kod, [p["kod"] for p in repo.szablon(self.db, self.kat("plyty_glowne"))])
        self.assertEqual("blad.slownik_pole_dziedziczone",
                         self.blad(edycja.usun_pole, self.db, self.kat("plyty_glowne"), kod))

    def test_przezywa_uzupelnianie_danych_startowych(self):
        """Każdy start programu uzupełnia słowniki — własne wpisy muszą zostać."""
        kat = self.kat("komputery_fabryczne")
        kod = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Region"}, "typ": "text"})
        moja = edycja.zapisz_kategorie(self.db, {"nazwy": {"pl": "Moja"}, "rodzaj": "czesc"})
        status = edycja.zapisz_status(self.db, {"pl": "Wypożyczony"})
        dane_startowe.wypelnij(self.db)
        self.assertIn(kod, [p["kod"] for p in repo.szablon(self.db, kat)])
        self.assertIsNotNone(repo.kategoria(self.db, moja))
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM status WHERE id = ?", (status,)).fetchone())


class TestWartosciWlasnych(Kolekcja):
    def test_secam_w_normie_tv(self):
        kat = self.kat("komputery_fabryczne")
        zapisane = edycja.ustaw_wartosci_wlasne(self.db, kat, "norma_tv", ["SECAM", "pal", " ", "SECAM"])
        self.assertEqual(["SECAM"], zapisane)                              # bez dubli, także z wbudowanymi
        lista = next(p for p in repo.szablon(self.db, kat) if p["kod"] == "norma_tv")["wartosci"]
        self.assertEqual("SECAM", lista[-1])
        surowe = next(p for p in json.loads(repo.kategoria(self.db, kat)["szablon_atrybutow"]) if p["kod"] == "norma_tv")
        self.assertNotIn("SECAM", surowe["wartosci"])                      # lista wbudowana nietknięta
        dane_startowe.wypelnij(self.db)                                     # restart programu
        self.assertIn("SECAM", next(p for p in repo.szablon(self.db, kat) if p["kod"] == "norma_tv")["wartosci"])

    def test_wartosc_w_uzyciu_chroniona(self):
        kat = self.kat("komputery_fabryczne")
        edycja.ustaw_wartosci_wlasne(self.db, kat, "norma_tv", ["SECAM", "PAL-N"])
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "MK 90", "atrybuty": {"norma_tv": "SECAM"}})
        with self.assertRaises(BladNornicy) as k:
            edycja.ustaw_wartosci_wlasne(self.db, kat, "norma_tv", [])
        self.assertEqual(("blad.wartosc_w_uzyciu", "SECAM"), (k.exception.klucz, k.exception.pola["lista"]))
        self.assertEqual(["SECAM"], edycja.ustaw_wartosci_wlasne(self.db, kat, "norma_tv", ["SECAM"]))  # PAL-N wolna
        inwentarz.usun_model(self.db, m)
        edycja.ustaw_wartosci_wlasne(self.db, kat, "norma_tv", [])
        surowe = next(p for p in json.loads(repo.kategoria(self.db, kat)["szablon_atrybutow"]) if p["kod"] == "norma_tv")
        self.assertNotIn("wartosci_wlasne", surowe)

    def test_pojemnosc_i_tekst_to_nie_lista(self):
        kat = self.kat("komputery_fabryczne")
        for kod in ("procesor", "pamiec"):
            with self.subTest(kod=kod), self.assertRaises(BladNornicy) as k:
                edycja.ustaw_wartosci_wlasne(self.db, kat, kod, ["x"])
            self.assertEqual("blad.wartosci_nie_lista", k.exception.klucz)

    def test_wlasne_pole_cala_lista(self):
        """Kolor obudowy: szara, czarna — i edycja limitowana dopisana później."""
        kat = self.kat("konsole")
        kod = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Kolor obudowy"}, "typ": "enum",
                                               "wartosci": ["szara", "czarna"]})
        dane = edycja.wartosci_listy(self.db, kat, kod)
        self.assertEqual(([], ["szara", "czarna"], True), (dane["wbudowane"], dane["edytowalne"], dane["wlasne_pole"]))
        edycja.ustaw_wartosci_wlasne(self.db, kat, kod, ["szara", "czarna", "EDYCJA LIMITOWANA STAR WARS"])
        m = inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "PS4",
                                             "atrybuty": {kod: "EDYCJA LIMITOWANA STAR WARS"}})
        with self.assertRaises(BladNornicy) as k:
            edycja.ustaw_wartosci_wlasne(self.db, kat, kod, ["szara"])
        self.assertEqual("EDYCJA LIMITOWANA STAR WARS", k.exception.pola["lista"])
        self.assertTrue(m)
        puste = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Pudełko"}, "typ": "enum", "wartosci": ["tak"]})
        self.assertEqual("blad.lista_wartosci", self.blad(edycja.ustaw_wartosci_wlasne, self.db, kat, puste, []))

    def blad(self, funkcja, *argumenty):
        with self.assertRaises(BladNornicy) as k:
            funkcja(*argumenty)
        return k.exception.klucz

    def test_pole_odziedziczone_zmiana_w_kategorii_nadrzednej(self):
        czesci = self.kat("czesci")
        kod = edycja.dodaj_pole(self.db, czesci, {"nazwy": {"pl": "Stan pinów"}, "typ": "enum", "wartosci": ["proste"]})
        plyty = self.kat("plyty_glowne")
        self.assertEqual(czesci, edycja.wartosci_listy(self.db, plyty, kod)["kategoria"])
        edycja.ustaw_wartosci_wlasne(self.db, plyty, kod, ["proste", "zgięte"])
        for k in (czesci, plyty, self.kat("procesory")):
            self.assertIn("zgięte", next(p for p in repo.szablon(self.db, k) if p["kod"] == kod)["wartosci"])

    def test_tekst_na_liste_zachowuje_dane(self):
        kat = self.kat("konsole")
        kod = edycja.dodaj_pole(self.db, kat, {"nazwy": {"pl": "Kolor obudowy"}, "typ": "text"})
        inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "PS4", "atrybuty": {kod: "czarna"}})
        inwentarz.zapisz_model(self.db, {"kategoria_id": kat, "nazwa": "PS4 SW", "atrybuty": {kod: "Star Wars"}})
        edycja.zapisz_pole(self.db, kat, kod, {"nazwy": {"pl": "Kolor obudowy"}, "typ": "enum", "wartosci": ["szara"]})
        pole = next(p for p in repo.szablon(self.db, kat) if p["kod"] == kod)
        self.assertEqual(("enum", ["szara", "czarna", "Star Wars"]), (pole["typ"], pole["wartosci"]))
        # inna zmiana typu pola z danymi nadal zablokowana
        self.assertEqual("blad.pole_typ_w_uzyciu", self.blad(edycja.zapisz_pole, self.db, kat, kod,
                                                             {"nazwy": {"pl": "Kolor obudowy"}, "typ": "int"}))


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOkna(TestPrzebudowy):
    def kat(self, kod):
        return self.db.execute("SELECT id FROM kategoria WHERE kod = ?", (kod,)).fetchone()[0]

    def test_pole_od_razu_w_otwartym_formularzu(self):
        from gui.okno_modelu import OknoModelu
        kat = self.kat("komputery_fabryczne")
        model = OknoModelu(self.okno, None, kategoria_id=kat)
        model.pokaz()
        slowniki = self.okno.slowniki()
        self.okno.update()
        slowniki.kat_id = kat
        slowniki._wypelnij()
        okno = slowniki.dodaj_pole()
        okno.nazwy["pl"].set("Region")
        okno.typ.ustaw("enum")
        okno.wartosci.ustaw("PAL\nNTSC")
        okno.zapisz()
        self.okno.update()
        model._zbuduj_parametry()
        self.assertIn("w_region", model.atrybuty.pola)
        self.assertTrue(slowniki._pola.exists("w_region"))
        self.assertEqual("w_region", slowniki.pole_kod)                  # nowe pole zaznaczone

    def test_przyciski_i_przebudowa(self):
        slowniki = self.okno.slowniki()
        self.okno.update()
        slowniki._drzewo.selection_set(str(self.kat("konsole")))
        self.okno.update()
        self.assertEqual("disabled", str(slowniki._przyciski["kat_usun"].cget("state")))   # wbudowana
        self.assertEqual("normal", str(slowniki._przyciski["pole_nowe"].cget("state")))
        slowniki._pola.selection_set("procesor")
        self.okno.update()
        self.assertEqual("disabled", str(slowniki._przyciski["pole_usun"].cget("state")))
        self.assertEqual(t("slowniki.pole_tylko_odczyt"), slowniki._podpowiedz.cget("text"))
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertEqual((str(self.kat("konsole")),), slowniki._drzewo.selection())   # wybór przeżywa przebudowę
        self.assertEqual(("procesor",), slowniki._pola.selection())
        self.assertIs(slowniki, self.okno.slowniki())                    # jedno okno

    def test_nowa_podkategoria_i_status_przez_okna(self):
        slowniki = self.okno.slowniki()
        slowniki.kat_id = self.kat("konsole")
        okno = slowniki.nowa_kategoria(slowniki.kat_id)
        okno.nazwy["pl"].set("Konsole przenośne")
        okno.zapisz()
        self.okno.update()
        nowa = self.db.execute("SELECT id FROM kategoria WHERE kod IS NULL").fetchone()[0]
        self.assertEqual(nowa, slowniki.kat_id)
        self.assertTrue(slowniki._drzewo.exists(str(nowa)))
        okno = slowniki.status(None)
        okno.nazwy["pl"].set("Wypożyczony")
        okno.zapisz()
        self.okno.update()
        self.assertTrue(slowniki._statusy.exists(str(slowniki.status_id)))
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            slowniki.usun_status()
        self.okno.update()
        self.assertIsNone(slowniki.status_id)

    def test_wlasne_wartosci_przez_okno_i_w_formularzu(self):
        from gui.okno_modelu import OknoModelu
        kat = self.kat("komputery_fabryczne")
        model = OknoModelu(self.okno, None, kategoria_id=kat)
        model.pokaz()
        self.okno.update()
        slowniki = self.okno.slowniki()
        slowniki.kat_id = kat
        slowniki._wypelnij()
        slowniki._pola.selection_set("norma_tv")
        self.okno.update()
        self.assertEqual("normal", str(slowniki._przyciski["pole_wartosci"].cget("state")))
        self.assertEqual(t("slowniki.lista_wbudowana"), slowniki._podpowiedz.cget("text"))
        okno = slowniki.wartosci_pola()
        okno.wartosci.ustaw("SECAM")
        self.okno.przelacz_jezyk("pl")                                   # wpis przeżywa przebudowę
        self.okno.update()
        okno.zapisz()
        self.okno.update()
        self.assertIn("SECAM", slowniki._pola.item("norma_tv", "values")[1])
        model._zbuduj_parametry()                                       # otwarty formularz: nowa opcja
        self.assertIn("SECAM", model.atrybuty.pola["norma_tv"].widzet.cget("values"))
        slowniki._pola.selection_set("procesor")
        self.okno.update()
        self.assertEqual("disabled", str(slowniki._przyciski["pole_wartosci"].cget("state")))

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
