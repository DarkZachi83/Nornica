# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy etykiet: kody QR (z odczytem dekoderem), formaty naklejek, PDF,
okno etykiet i kod QR na karcie."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from i18n.tlumacz import t
from testy.test_gui import EKRAN, TestPrzebudowy
from testy.test_uslugi import Kolekcja
from uslugi import etykiety
from wyjatki import BladNornicy

try:
    from pyzbar.pyzbar import decode as dekoduj
    from PIL import Image
    DEKODER = True
except ImportError:          # dekoder potrzebny tylko w testach
    DEKODER = False

try:
    import pypdf
    PYPDF = True
except ImportError:
    PYPDF = False

PDFTOPPM = shutil.which("pdftoppm") is not None


def odczytaj_kody_z_pdf(sciezka: Path, f=None, strona: int = 1, dpi: int = 300) -> list[str]:
    """Rasteryzuje stronę PDF jak drukarka i czyta kody QR dekoderem — każdą
    etykietę OSOBNO, tak jak skaner czyta jedną naklejkę. (Dekoder szukający
    24 kodów naraz na całej stronie potrafi część pominąć, choć każdy z nich
    jest poprawny.)"""
    cel = sciezka.with_suffix("")
    subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(strona), "-l", str(strona), "-png",
                    "-singlefile", str(sciezka), str(cel)], check=True)
    obraz = Image.open(f"{cel}.png")
    if f is None or f.rodzaj != "a4":
        return sorted(k.data.decode() for k in dekoduj(obraz))
    px = dpi / 25.4
    kody = []
    for n in range(f.na_stronie):
        x, y = f.etykieta(n)
        wycinek = obraz.crop((int(x * px), int(y * px), int((x + f.szerokosc) * px), int((y + f.wysokosc) * px)))
        kody += [k.data.decode() for k in dekoduj(wycinek)]
    return sorted(kody)


class TestFormatow(unittest.TestCase):
    def test_wszystkie_formaty_mieszcza_sie_na_stronie(self):
        for f in etykiety.FORMATY.values():
            with self.subTest(format=f.kod):
                etykiety.sprawdz_format(f)

    def test_format_wlasny_za_duzy(self):
        with self.assertRaises(BladNornicy):
            etykiety.format_wlasny(80, 40, 3, 8, 0, 0, 0, 0)      # 3 × 80 mm > 210 mm

    def test_pozycje_na_arkuszu(self):
        f = etykiety.FORMATY["avery_l7160"]
        self.assertEqual((7.2, 15.15), f.etykieta(0))
        x, y = f.etykieta(4)                                     # drugi wiersz, środkowa kolumna
        self.assertAlmostEqual(7.2 + 63.5 + 2.5, x)
        self.assertAlmostEqual(15.15 + 38.1, y)

    def test_macierz_qr(self):
        macierz = etykiety.macierz_qr("NOR-000123")
        self.assertEqual(21, len(macierz))                      # wersja 1 wystarcza na krótki kod
        self.assertTrue(all(macierz[0][:7]))                    # wzorzec pozycjonujący w rogu


class TestPdf(Kolekcja):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def strony(self, sciezka):
        return len(pypdf.PdfReader(str(sciezka)).pages)

    @unittest.skipUnless(PYPDF, "brak pypdf")
    def test_liczba_stron_i_start(self):
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", f"Egzemplarz {i}") for i in range(30)]
        f = etykiety.FORMATY["avery_3474"]                        # 24 na arkuszu
        self.assertEqual(2, etykiety.generuj_pdf(self.tmp / "a.pdf", lista, f))
        self.assertEqual(2, self.strony(self.tmp / "a.pdf"))
        # napoczęty arkusz: od 20. naklejki zostaje 5 miejsc, reszta na 2 kolejnych
        self.assertEqual(3, etykiety.generuj_pdf(self.tmp / "b.pdf", lista, f, start=20))
        # drukarka etykiet: strona = etykieta
        rolka = etykiety.FORMATY["brother_dk11209"]
        self.assertEqual(30, etykiety.generuj_pdf(self.tmp / "c.pdf", lista, rolka))
        wymiary = pypdf.PdfReader(str(self.tmp / "c.pdf")).pages[0].mediabox
        self.assertAlmostEqual(62, float(wymiary.width) / etykiety.MM, places=1)

    @unittest.skipUnless(PYPDF, "brak pypdf")
    def test_polskie_litery_w_pdf(self):
        etykiety.generuj_pdf(self.tmp / "pl.pdf", [etykiety.Etykieta("LOC-0001", "Półka żółta, łączówki")],
                             etykiety.FORMATY["avery_l7160"], tryb="wektor")     # tekst do odczytu tylko w wektorze
        tekst = pypdf.PdfReader(str(self.tmp / "pl.pdf")).pages[0].extract_text()
        self.assertEqual("Półka żółta, łączówki", " ".join(tekst.split()[1:]))   # zawinięte, bez ucięcia

    @unittest.skipUnless(DEKODER and PDFTOPPM, "brak dekodera QR lub pdftoppm")
    def test_kody_daja_sie_odczytac_po_wydruku(self):
        """Kod, który się drukuje, ale nie skanuje, jest bezużyteczny — w każdym trybie.
        (Ten test wyłapał białe linie w trybie wektorowym przy złej regule wypełniania.)"""
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", "Atari 65XE") for i in range(1, 25)]
        f = etykiety.FORMATY["avery_3474"]
        for tryb in etykiety.TRYBY:
            with self.subTest(tryb=tryb):
                etykiety.generuj_pdf(self.tmp / f"skan_{tryb}.pdf", lista, f, tryb=tryb)
                self.assertEqual([e.kod for e in lista], odczytaj_kody_z_pdf(self.tmp / f"skan_{tryb}.pdf", f))

    @unittest.skipUnless(DEKODER and PDFTOPPM, "brak dekodera QR lub pdftoppm")
    def test_najmniejsza_etykieta_skanowalna(self):
        """Brother DK-11204: 17 mm wysokości, drukarka 300 dpi — w każdym trybie."""
        for tryb in etykiety.TRYBY:
            with self.subTest(tryb=tryb):
                etykiety.generuj_pdf(self.tmp / f"mala_{tryb}.pdf", [etykiety.Etykieta("NOR-000123", "Amiga 1200")],
                                     etykiety.FORMATY["brother_dk11204"], tryb=tryb)
                self.assertEqual(["NOR-000123"], odczytaj_kody_z_pdf(self.tmp / f"mala_{tryb}.pdf"))

    @unittest.skipUnless(PYPDF, "brak pypdf")
    def test_tryb_obrazu_najprostszy_pdf(self):
        """Tryb obrazu: PDF 1.4, na stronie jeden obraz JPEG, JEDEN filtr (bez łańcuchów
        filtrów, na których zatrzymywał się interpreter drukarki), zero czcionek,
        zero ścieżek wektorowych."""
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", "Półka żółta") for i in range(1, 30)]
        etykiety.generuj_pdf(self.tmp / "obraz.pdf", lista, etykiety.FORMATY["avery_3474"], tryb="obraz")
        surowe = (self.tmp / "obraz.pdf").read_bytes()
        self.assertTrue(surowe.startswith(b"%PDF-1.4"))
        self.assertNotIn(b"/Font", surowe)
        self.assertNotIn(b"ASCII85", surowe)
        self.assertNotIn(b"/Filter [", surowe)
        self.assertEqual(2, surowe.count(b"/Filter /DCTDecode"))
        czytnik = pypdf.PdfReader(str(self.tmp / "obraz.pdf"))
        self.assertEqual(2, len(czytnik.pages))
        for strona in czytnik.pages:
            obrazy = [o for o in strona["/Resources"]["/XObject"].values()
                      if o.get_object()["/Subtype"] == "/Image"]
            self.assertEqual(1, len(obrazy))
            self.assertEqual(2480, obrazy[0].get_object()["/Width"])        # A4 przy 300 dpi
            self.assertEqual(0, strona.get_contents().get_data().count(b" re"))

    @unittest.skipUnless(shutil.which("qpdf"), "brak qpdf")
    def test_wlasny_zapis_pdf_poprawny_strukturalnie(self):
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", "A") for i in range(1, 50)]
        etykiety.generuj_pdf(self.tmp / "q.pdf", lista, etykiety.FORMATY["avery_l7160"], tryb="obraz")
        wynik = subprocess.run(["qpdf", "--check", str(self.tmp / "q.pdf")], capture_output=True, text=True)
        self.assertEqual(0, wynik.returncode, wynik.stdout + wynik.stderr)
        self.assertIn("No syntax or stream encoding errors", wynik.stdout)

    def test_tryb_obrazu_nie_wymaga_reportlab(self):
        import builtins
        oryginalny = builtins.__import__

        def bez_reportlab(nazwa, *argumenty, **opcje):
            if nazwa.startswith("reportlab"):
                raise ImportError(nazwa)
            return oryginalny(nazwa, *argumenty, **opcje)

        with mock.patch("builtins.__import__", side_effect=bez_reportlab):
            pliki = etykiety.generuj(self.tmp / "bez.pdf", [etykiety.Etykieta("NOR-000001", "A")],
                                     etykiety.FORMATY["brother_dk11209"], tryb="obraz")
        self.assertTrue(pliki[0].exists())

    @unittest.skipUnless(DEKODER, "brak dekodera QR")
    def test_pliki_png(self):
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", "Atari 65XE") for i in range(1, 30)]
        f = etykiety.FORMATY["avery_3474"]
        pliki = etykiety.generuj(self.tmp / "etykiety.png", lista, f, tryb="png")
        self.assertEqual(["etykiety_01.png", "etykiety_02.png"], [p.name for p in pliki])
        obraz = Image.open(pliki[0])
        self.assertEqual((2480, 3508), obraz.size)                       # A4 przy 300 dpi
        self.assertAlmostEqual(300, obraz.info["dpi"][0], places=1)      # rzeczywisty rozmiar przy druku
        px = 300 / 25.4
        kody = []
        for n in range(f.na_stronie):
            x, y = f.etykieta(n)
            kody += [k.data.decode() for k in dekoduj(obraz.crop(
                (int(x * px), int(y * px), int((x + f.szerokosc) * px), int((y + f.wysokosc) * px))))]
        self.assertEqual([e.kod for e in lista[:24]], sorted(kody))
        jedna = etykiety.generuj(self.tmp / "jedna.png", lista[:1], etykiety.FORMATY["brother_dk11209"], tryb="png")
        self.assertEqual(["jedna.png"], [p.name for p in jedna])           # jedna strona: bez numeru

    @unittest.skipUnless(PYPDF, "brak pypdf")
    def test_tryb_wektorowy_jedna_sciezka_na_kod(self):
        etykiety.generuj_pdf(self.tmp / "w.pdf", [etykiety.Etykieta("NOR-000001", "A")],
                             etykiety.FORMATY["avery_3474"], tryb="wektor")
        tresc = pypdf.PdfReader(str(self.tmp / "w.pdf")).pages[0].get_contents().get_data()
        self.assertEqual(1, tresc.count(b"\nf\n") + tresc.count(b" f\n"))    # jedno wypełnienie, reguła niezerowa
        self.assertNotIn(b"f*", tresc)

    @unittest.skipUnless(shutil.which("gs"), "brak Ghostscript")
    def test_sciezka_druku_ghostscript(self):
        """Te same urządzenia, których używają filtry CUPS: raster IPP, PCL XL, PCL5, PostScript."""
        lista = [etykiety.Etykieta(f"NOR-{i:06d}", "Atari 65XE") for i in range(1, 25)]
        for tryb in ("obraz", "obraz600", "wektor"):
            sciezka = self.tmp / f"gs_{tryb}.pdf"
            etykiety.generuj_pdf(sciezka, lista, etykiety.FORMATY["avery_l7160"], tryb=tryb)
            for urzadzenie in ("pwgraster", "pxlmono", "ljet4", "ps2write"):
                with self.subTest(tryb=tryb, urzadzenie=urzadzenie):
                    wynik = subprocess.run(["gs", "-q", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-r300",
                                            f"-sDEVICE={urzadzenie}", f"-sOutputFile={self.tmp}/gs.out",
                                            str(sciezka)], capture_output=True, text=True)
                    self.assertEqual(0, wynik.returncode, wynik.stderr)
                    self.assertNotIn("rror", wynik.stdout + wynik.stderr)

    def test_zakres_lokalizacji_z_czesciami(self):
        lista = etykiety.zakres(self.db, self.regal, z_lokalizacjami=True)
        kody = [e.kod for e in lista]
        # regał i półka, potem PC z płytą i procesorem (zamontowane — przez efektywną lokalizację)
        self.assertEqual(["LOC-0001", "LOC-0002", "NOR-000001", "NOR-000002", "NOR-000003"], kody)
        self.assertEqual("Regał A", next(e for e in lista if e.kod == "LOC-0002").dopisek)

    @unittest.skipUnless(PYPDF, "brak pypdf")
    def test_kod_nigdy_nie_jest_ucinany(self):
        for kod_formatu in ("avery_l7651", "avery_l7160", "brother_dk11204", "dymo_11355"):
            with self.subTest(format=kod_formatu):
                sciezka = self.tmp / f"{kod_formatu}.pdf"
                etykiety.generuj_pdf(sciezka, [etykiety.Etykieta("NOR-000123", "Bardzo długa nazwa egzemplarza")],
                                     etykiety.FORMATY[kod_formatu], tryb="wektor")
                self.assertIn("NOR-000123", pypdf.PdfReader(str(sciezka)).pages[0].extract_text())

    def test_pusty_zakres(self):
        with self.assertRaises(BladNornicy) as k:
            etykiety.generuj_pdf(self.tmp / "x.pdf", [], etykiety.FORMATY["avery_3474"])
        self.assertEqual("blad.brak_etykiet", k.exception.klucz)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestGuiEtykiet(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def plotno_qr(self):
        import tkinter as tk
        karta = self.okno._widzety["szczegoly"].karty[0]
        return next((w for w in karta.winfo_children() if isinstance(w, tk.Canvas)), None)

    def test_kod_qr_na_karcie_egzemplarza_i_lokalizacji(self):
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        self.okno.update()
        plotno = self.plotno_qr()
        self.assertGreater(len(plotno.find_withtag("modul")), 50)
        kod = self.db.execute("SELECT kod_inwentarzowy FROM egzemplarz WHERE id = ?", (self.pc,)).fetchone()[0]
        self.assertEqual(kod, plotno.itemcget(plotno.find_withtag("podpis")[0], "text"))
        self.okno.odswiez(zaznacz=f"L{self.regal}")
        self.okno.update()
        plotno = self.plotno_qr()
        self.assertEqual("LOC-0001", plotno.itemcget(plotno.find_withtag("podpis")[0], "text"))

    @unittest.skipUnless(DEKODER, "brak dekodera QR")
    def test_kod_na_ekranie_skanowalny(self):
        """Kod z karty da się zeskanować także z ekranu (telefonem)."""
        import subprocess
        self.okno.geometry("1400x800+0+0")
        self.okno.odswiez(zaznacz=f"E{self.pc}")
        for _ in range(4):
            self.okno.update()
        plotno = self.plotno_qr()
        zrzut = self.tmp / "ekran.png"
        subprocess.run(["import", "-window", "root", str(zrzut)], check=True)
        x, y = plotno.winfo_rootx(), plotno.winfo_rooty()
        wycinek = Image.open(zrzut).crop((x - 10, y - 10, x + plotno.winfo_width() + 10,
                                          y + plotno.winfo_height() + 10))
        self.assertIn("NOR-000001", [k.data.decode() for k in dekoduj(wycinek)])

    def test_okno_etykiet_przezywa_przebudowe_i_zapisuje_pdf(self):
        self.okno.odswiez(zaznacz=f"L{self.regal}")
        okno = self.okno.drukuj_etykiety()
        self.okno.update()
        okno.zakres.set("lokalizacja")
        okno.format.ustaw("avery_l7160")
        okno.start.set("5")
        okno.przesuniecie["x"].set("0,5")
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertEqual(t("etykiety.podsumowanie", liczba=4, strony=1), okno._podsumowanie.cget("text"))
        okno.otworz_po.set(False)
        sciezka = okno.zapisz(str(self.tmp / "regal.pdf"))
        self.assertTrue(Path(sciezka).exists())
        # zapamiętane ustawienia drukarki
        from baza.repozytoria import ustawienia
        self.assertEqual("avery_l7160", ustawienia.pobierz(self.db, "etykiety_format"))
        self.assertEqual("obraz", ustawienia.pobierz(self.db, "etykiety_tryb"))     # domyślny tryb zgodny
        self.assertEqual("0,5", ustawienia.pobierz(self.db, "etykiety_przesuniecie_x"))

    def test_format_wlasny_bledny(self):
        okno = self.okno.drukuj_etykiety()
        okno.format.ustaw("wlasny")
        okno.wlasne["kolumny"].set("9")
        okno._zmiana()
        self.assertEqual(t("blad.zly_format_etykiet"), okno._podsumowanie.cget("text"))
        with mock.patch("tkinter.messagebox.showerror") as komunikat:
            self.assertIsNone(okno.zapisz(str(self.tmp / "x.pdf")))
        self.assertEqual(t("blad.zly_format_etykiet"), komunikat.call_args[0][1])

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()
