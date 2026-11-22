# SPDX-License-Identifier: GPL-3.0-or-later
"""Szybkie wyszukiwanie złączy po fragmencie nazwy (edytor złączy)."""
import unittest

from baza import dane_startowe
from uslugi import wyszukiwanie as w


class TestWyszukiwania(unittest.TestCase):
    POZYCJE = [(1, "Port: Port szeregowy COM (DB9)"), (2, "Port: VGA (DE15)"), (3, "Port: DVI-I (Single-Link)"),
               (4, "Port: DVI-I (Dual-Link)"), (5, "Port: S-Video (mini-DIN 4)"), (6, "Slot: Złącze klapki A1200"),
               (7, "Port: Karta SVGA")]

    def wartosci(self, zapytanie, dodatkowe=None):
        return [p[0] for p in w.filtruj(zapytanie, self.POZYCJE, dodatkowe)]

    def test_bez_wielkosci_liter_myslnikow_i_polskich_znakow(self):
        for zapytanie in ("s-video", "SVIDEO", "s video", "Svid"):
            self.assertEqual([5], self.wartosci(zapytanie), zapytanie)
        self.assertEqual([6], self.wartosci("zlacze"))
        self.assertEqual([6], self.wartosci("złącze"))

    def test_kilka_slow_w_dowolnej_kolejnosci(self):
        self.assertEqual([4], self.wartosci("dvi dual"))
        self.assertEqual([4], self.wartosci("dual dvi-i"))
        self.assertEqual([3, 4], self.wartosci("dvi-i"))

    def test_trafienia_od_poczatku_nazwy_pierwsze(self):
        self.assertEqual([2, 7], self.wartosci("vga"))
        # trafienie w nazwie przed trafieniem dopiero w synonimach
        self.assertEqual([7, 2], self.wartosci("karta", {2: "karta graficzna"}.get))

    def test_synonimy_slowo_po_slowie(self):
        # „graphics video” nie może dać „s-vid” przez sklejenie słów
        self.assertEqual([5], self.wartosci("s-vid", {1: "graphics video"}.get))

    def test_wszystkie_wbudowane_zlacza(self):
        from baza.dane_startowe import SYNONIMY_ZLACZY, ZLACZA
        pozycje = [(z[0], z[3]) for z in ZLACZA]
        dodatkowe = lambda kod: f"{kod} {SYNONIMY_ZLACZY.get(kod, '')}"  # noqa: E731
        for zapytanie, oczekiwane in (("d-sub 15", "vga_de15"), ("dvi dual", "dvi_i_dl"),
                                      ("s-video", "svideo"), ("tv-out", "svideo"), ("rs232", "com_db9"),
                                      ("centronics", "lpt_db25"), ("pc133", "dimm168"), ("athlon", "slot_a")):
            self.assertEqual(oczekiwane, w.filtruj(zapytanie, pozycje, dodatkowe)[0][0], zapytanie)

    def test_synonimy(self):
        slowa = {2: "D-Sub DB-15 HD-15", 5: "TV-Out Y/C"}.get
        self.assertEqual([2], self.wartosci("d-sub 15", slowa))
        self.assertEqual([5], self.wartosci("tv-out", slowa))

    def test_puste_zapytanie_daje_wszystko(self):
        self.assertEqual([p[0] for p in self.POZYCJE], self.wartosci("  "))

    def test_synonimy_dotycza_istniejacych_zlaczy(self):
        kody = {z[0] for z in dane_startowe.ZLACZA}
        self.assertEqual(set(), set(dane_startowe.SYNONIMY_ZLACZY) - kody)


from testy import test_gui   # noqa: E402 — moduł, nie klasa: inaczej jej testy uruchomiłyby się drugi raz


@unittest.skipUnless(test_gui.EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestEdytoraZlaczy(test_gui.TestPrzebudowy):
    def edytor(self):
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self.okno, None)
        okno.pokaz()
        okno._notatnik.select(2)
        self.okno.update()
        return okno, okno.zlacza

    def wpisz(self, edytor, tekst):
        pole = edytor.nowy_typ.widzet
        pole.focus_force()                       # zdarzenia klawiatury trafiają do pola z fokusem
        self.okno.update()
        pole.delete(0, "end")
        pole.insert(0, tekst)
        pole.event_generate("<KeyRelease>", keysym="a")
        self.okno.update()

    def enter(self, edytor):
        edytor.nowy_typ.widzet.focus_force()
        self.okno.update()
        edytor.nowy_typ.widzet.event_generate("<Return>")

    def nazwy(self, edytor):
        return {edytor._typy[typ]["kod"]: ilosc for (typ, _rola), ilosc in edytor.wynik().items()}

    def test_szybkie_dodawanie_kart_graficznej(self):
        from i18n.tlumacz import t
        okno, ed = self.edytor()
        self.wpisz(ed, "d-sub 15")
        self.assertIn("VGA (DE15)", ed._podpowiedz_szukania.cget("text"))
        self.enter(ed)
        self.okno.update()
        self.assertEqual("Port: VGA (DE15)", ed.nowy_typ.widzet.get())
        self.assertTrue(ed.nowy_typ.widzet.selection_present())        # pisanie zastąpi nazwę
        self.wpisz(ed, "dvi dual")
        ed.dodaj()                                                    # przycisk „Dodaj” działa tak samo
        self.wpisz(ed, "tv-out")
        ed.nowa_ilosc.set("2")
        self.enter(ed)
        self.okno.update()
        self.assertEqual({"vga_de15": 1, "dvi_i_dl": 1, "svideo": 2}, self.nazwy(ed))
        self.assertEqual("1", ed.nowa_ilosc.get())
        self.wpisz(ed, "xyzzy")
        self.assertEqual(t("zlacza.szukaj_brak", tekst="xyzzy"), ed._podpowiedz_szukania.cget("text"))
        self.enter(ed)                 # nic nie pasuje: nic nie dodaje
        self.okno.update()
        self.assertEqual(3, len(ed.wynik()))

    def test_wybor_z_przefiltrowanej_listy_i_zmiana_jezyka(self):
        okno, ed = self.edytor()
        self.wpisz(ed, "dvi")
        lista = ed.nowy_typ.widzet.cget("values")
        self.assertEqual(3, len(lista))
        ed.nowy_typ.widzet.current(1)                                  # druga z przefiltrowanych
        ed.nowy_typ.widzet.event_generate("<<ComboboxSelected>>")
        self.okno.update()
        wybrany = ed.nowy_typ.wartosc
        self.assertEqual(lista[1], ed.nowy_typ.widzet.get())
        self.wpisz(ed, "s-vid")                                        # wpisane, niezatwierdzone
        self.okno.przelacz_jezyk("en")
        self.okno.update()
        self.assertEqual("s-vid", okno.zlacza.nowy_typ.widzet.get())   # przeżywa przebudowę
        self.assertEqual(1, len(okno.zlacza.nowy_typ.widzet.cget("values")))
        self.assertIsNotNone(wybrany)
