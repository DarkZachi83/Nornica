# SPDX-License-Identifier: GPL-3.0-or-later
"""The Retro Web: czytnik na prawdziwych stronach (testy/dane/trw/), dopasowanie
do kategorii, pól i złączy, pobieranie (sieć udawana — testy nie obciążają
serwisu), okno i pełna droga aż do zapisu modelu."""
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from baza import dane_startowe
from baza.migracje import migruj
from baza.polaczenie import otworz_baze
from i18n.tlumacz import t, ustaw_jezyk
from testy.test_gui import EKRAN, TestPrzebudowy
from uslugi import retroweb
from wyjatki import BladNornicy

DANE = Path(__file__).resolve().parent / "dane" / "trw"


def strona(nazwa: str) -> str:
    return (DANE / f"{nazwa}.html").read_text(encoding="utf-8")


class TestCzytnika(unittest.TestCase):
    def test_plyta_glowna(self):
        s = retroweb.parsuj(strona("plyta_zida_4dps"))
        self.assertEqual(("Motherboards", "5805", "Zida", "4DPS 2.x"), (s.dzial, s.id, s.producent, s.nazwa))
        self.assertEqual("https://theretroweb.com/motherboards/s/zida-4dps", s.url)
        self.assertEqual(["128KB", "256KB", "512KB"], s.parametry["Cache"])
        self.assertEqual(["1995"], s.parametry["Release date"])
        self.assertIn(("Expansion slots", 3, "16-bit ISA"), s.zlacza)
        self.assertIn(("I/O ports", 2, "Serial"), s.zlacza)
        self.assertIn("Taken PCI400-4", s.aliasy)
        self.assertEqual(["SiS 85C496 (PCM)", "SiS 85C497 (ATM)"], s.uklady["Chipset part"])

    def test_karta_bez_producenta_i_puste_sekcje(self):
        s = retroweb.parsuj(strona("karta_rage_xl"))
        self.assertEqual((None, "Rage XL 8MB"), (s.producent, s.nazwa))      # „[Unknown]”
        self.assertEqual([("I/O ports", 1, "VGA")], s.zlacza)                  # „Empty” i „DE-15, VGA” pominięte
        self.assertNotIn("Release date", s.parametry)                          # „Empty” = brak wartości

    def test_nie_strona_produktu(self):
        for html in ("<html><body>Strona główna</body></html>", "", "<div class='title'>X</div>"):
            with self.subTest(html=html[:20]), self.assertRaises(BladNornicy) as k:
                retroweb.parsuj(html)
            self.assertEqual("blad.trw_strona", k.exception.klucz)

    def test_pojemnosci(self):
        self.assertEqual(64 * 2 ** 20, retroweb.pojemnosc("64MB"))
        self.assertEqual(500 * 10 ** 9, retroweb.pojemnosc("500GB", dziesietnie=True))   # z naklejki dysku
        self.assertEqual(512 * 1024, retroweb.pojemnosc("512 KB"))
        self.assertIsNone(retroweb.pojemnosc("Empty"))


class TestPropozycji(unittest.TestCase):
    def setUp(self):
        ustaw_jezyk("pl")
        self.addCleanup(ustaw_jezyk, "en")
        self.db = otworz_baze(":memory:")
        migruj(self.db)
        dane_startowe.wypelnij(self.db)

    def typ(self, kod):
        return self.db.execute("SELECT id FROM zlacze_typ WHERE kod = ?", (kod,)).fetchone()[0]

    def propozycja(self, nazwa):
        return retroweb.propozycja(self.db, retroweb.parsuj(strona(nazwa)))

    def test_plyta(self):
        p = self.propozycja("plyta_zida_4dps")
        self.assertEqual(("plyty_glowne", 1995), (p.kategoria_kod, p.rok_od))
        self.assertEqual({"chipset": "SiS 85C496/497 (486-VIP 486 Green PC VESA/ISA/PCI Chipset)",
                          "format": "Baby AT", "max_ram": 64 * 2 ** 20, "cache": 512 * 1024}, p.atrybuty)
        self.assertEqual(3, p.zlacza[(self.typ("isa16"), "posiada")])
        self.assertEqual(3, p.zlacza[(self.typ("pci"), "posiada")])
        self.assertEqual(2, p.zlacza[(self.typ("simm72"), "posiada")])          # bez podwójnego liczenia
        self.assertEqual(1, p.zlacza[(self.typ("socket3"), "posiada")])
        self.assertEqual([], p.nieprzypisane)
        self.assertTrue(p.opis.startswith("Źródło: The Retro Web — https://theretroweb.com/motherboards/s/zida-4dps"))
        self.assertIn("CC BY-SA 4.0", p.opis)
        self.assertIn("FSB speeds: 20MHz, 25MHz, 33MHz, 40MHz, 50MHz", p.opis)   # nic nie ginie

    def test_karta_wymaga_slotu_posiada_port(self):
        p = self.propozycja("karta_rage_xl")
        self.assertEqual("karty_graficzne", p.kategoria_kod)
        self.assertEqual({"chipset": "ATI Rage XL (Mach64 GM)", "pamiec": 8 * 2 ** 20}, p.atrybuty)
        self.assertEqual({(self.typ("pci"), "wymaga"): 1, (self.typ("vga_de15"), "posiada"): 1}, p.zlacza)

    def test_dysk_zasilanie_to_nie_dane(self):
        """„SATA Power (15-pin)” to złącze zasilania, a nie drugie złącze danych SATA."""
        p = self.propozycja("dysk_seagate_st3500413as")
        self.assertEqual("dyski_twarde", p.kategoria_kod)
        self.assertEqual({"pojemnosc": 500 * 10 ** 9, "format_cali": '3.5"'}, p.atrybuty)
        self.assertEqual({(self.typ("sata"), "wymaga"): 1, (self.typ("zasilanie_sata"), "wymaga"): 1}, p.zlacza)


class TestPobierania(unittest.TestCase):
    def setUp(self):
        retroweb._roboty = None
        self.addCleanup(setattr, retroweb, "_roboty", None)

    def odpowiedz(self, tresc: str):
        o = mock.MagicMock()
        o.__enter__.return_value = o
        o.read.side_effect = lambda n=-1: tresc.encode("utf-8")[:n if n > 0 else None]
        o.headers.get_content_charset.return_value = "utf-8"
        return o

    def test_adresy(self):
        dobre = "https://theretroweb.com/motherboards/s/zida-4dps"
        self.assertEqual(dobre, retroweb.sprawdz_adres(f"  {dobre} "))
        for zly in ("http://theretroweb.com/motherboards/s/x", "https://theretroweb.com/", "https://zly.pl/motherboards/s/x",
                    "https://theretroweb.com.zly.pl/motherboards/s/x", "file:///etc/passwd", ""):
            with self.subTest(adres=zly), self.assertRaises(BladNornicy):
                retroweb.sprawdz_adres(zly)

    def test_pobranie_z_naglowkiem_programu_i_robots(self):
        zapytania = []

        def urlopen(zapytanie, timeout):
            zapytania.append(zapytanie)
            return self.odpowiedz("User-agent: *\nDisallow: /admin\n" if zapytanie.full_url.endswith("robots.txt")
                                  else strona("plyta_zida_4dps"))

        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            html = retroweb.pobierz("https://theretroweb.com/motherboards/s/zida-4dps")
        self.assertIn("4DPS", html)
        self.assertEqual(["https://theretroweb.com/robots.txt", "https://theretroweb.com/motherboards/s/zida-4dps"],
                         [z.full_url for z in zapytania])
        self.assertTrue(zapytania[1].get_header("User-agent").startswith("NORNICA-VOLE/"))

    def test_robots_zabrania(self):
        def urlopen(zapytanie, timeout):
            return self.odpowiedz("User-agent: *\nDisallow: /motherboards/\n")
        with mock.patch("urllib.request.urlopen", side_effect=urlopen) as siec, self.assertRaises(BladNornicy) as k:
            retroweb.pobierz("https://theretroweb.com/motherboards/s/zida-4dps")
        self.assertEqual("blad.trw_robots", k.exception.klucz)
        self.assertEqual(1, siec.call_count)                                 # sama strona nie została pobrana

    def test_bledy_sieci(self):
        for wyjatek, opis in ((urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO()), "HTTP 404"),
                              (urllib.error.URLError("brak sieci"), "brak sieci")):
            retroweb._roboty = None

            def urlopen(zapytanie, timeout, w=wyjatek):
                if zapytanie.full_url.endswith("robots.txt"):
                    return self.odpowiedz("")
                raise w
            with self.subTest(opis=opis), mock.patch("urllib.request.urlopen", side_effect=urlopen), \
                    self.assertRaises(BladNornicy) as k:
                retroweb.pobierz("https://theretroweb.com/harddrives/s/x")
            self.assertEqual(("blad.trw_siec", opis), (k.exception.klucz, k.exception.pola["opis"]))


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestOkna(TestPrzebudowy):
    def nowy_model(self):
        from gui.okno_modelu import OknoModelu
        okno = OknoModelu(self.okno, None)
        okno.pokaz()
        self.okno.update()
        return okno

    def test_z_pliku_do_zapisanego_modelu(self):
        model = self.nowy_model()
        okno = model.retroweb()
        okno.z_pliku(str(DANE / "plyta_zida_4dps.html"))
        self.okno.update()
        self.assertIn("Socket 3", okno._podglad.get("1.0", "end"))
        self.okno.przelacz_jezyk("pl")                                     # podgląd przeżywa zmianę języka
        self.okno.update()
        self.assertIn("Posiada: 3× ISA 16-bit", okno._podglad.get("1.0", "end"))
        okno.zastosuj()
        self.okno.update()
        self.assertEqual("Zida", model.producent.get())
        self.assertEqual("1995", model.v["rok_od"].get())
        model.zapisz()
        wiersz = self.db.execute("SELECT id, atrybuty, opis, zrodlo_url, kategoria_id FROM model "
                                 "WHERE nazwa = '4DPS 2.x'").fetchone()
        self.assertEqual("https://theretroweb.com/motherboards/s/zida-4dps", wiersz["zrodlo_url"])
        self.assertEqual("Baby AT", json.loads(wiersz["atrybuty"])["format"])
        self.assertIn("CC BY-SA 4.0", wiersz["opis"])
        self.assertEqual("plyty_glowne", self.db.execute("SELECT kod FROM kategoria WHERE id = ?",
                                                          (wiersz["kategoria_id"],)).fetchone()[0])
        from baza.repozytoria import zlacza
        isa = self.db.execute("SELECT id FROM zlacze_typ WHERE kod = 'isa16'").fetchone()[0]
        self.assertEqual(3, zlacza.modelu(self.db, wiersz["id"])[(isa, "posiada")])

    def test_wypelnione_pola_zostaja_a_opis_bez_dubli(self):
        model = self.nowy_model()
        model.v["nazwa"].set("Moja nazwa")
        p = retroweb.propozycja(self.db, retroweb.parsuj(strona("plyta_zida_4dps")))
        model.zastosuj_retroweb(p)
        model.atrybuty.pola["chipset"].set("SiS 496 (sprawdzony)")
        model.zastosuj_retroweb(p)                                          # drugi raz
        self.assertEqual("Moja nazwa", model.v["nazwa"].get())
        self.assertEqual("SiS 496 (sprawdzony)", model.atrybuty.pola["chipset"].get())
        self.assertEqual(1, model.opis.zapamietaj().count("The Retro Web"))
        model.zastosuj_retroweb(p, nadpisz=True)
        self.assertEqual("4DPS 2.x", model.v["nazwa"].get())

    def test_bledny_adres_w_podgladzie(self):
        okno = self.nowy_model().retroweb()
        okno.adres.set("https://example.com/x")
        okno.pobierz()
        self.okno.update()
        self.assertIn(t("blad.trw_adres")[:30], okno._podglad.get("1.0", "end"))
        self.assertEqual("disabled", str(okno._przyciski["zastosuj"].cget("state")))

    def test_pobieranie_w_tle(self):
        import threading
        watki = []

        def pobierz(adres):
            watki.append(threading.current_thread() is threading.main_thread())
            return strona("karta_rage_xl")

        okno = self.nowy_model().retroweb()
        okno.adres.set("https://theretroweb.com/expansioncards/s/unknown-rage-xl-8mb")
        with mock.patch("uslugi.retroweb.pobierz", side_effect=pobierz):
            okno.pobierz()
            for _ in range(50):
                self.okno.update()
                if okno.strona is not None:
                    break
                self.okno.after(20)
        self.assertEqual([False], watki)                                    # sieć poza wątkiem interfejsu
        self.assertEqual("Rage XL 8MB", okno.strona.nazwa)
        self.assertEqual("https://theretroweb.com/expansioncards/s/unknown-rage-xl-8mb", okno.strona.url)

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
