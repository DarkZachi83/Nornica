# SPDX-License-Identifier: GPL-3.0-or-later
"""Tryb wsadowy asystenta: odczyt linii, tworzenie modeli i egzemplarzy, okno."""
import os
import shutil
import tempfile
import threading
from pathlib import Path
from unittest import mock

from asystent import propozycje, wsad
from asystent.propozycje import NAZWA, PRODUCENT, Asystent, Wartosc, Wynik
from asystent.wyszukiwarki import Strona
from baza.repozytoria import slowniki
from i18n.tlumacz import ustaw_jezyk
from testy import test_gui
from testy.test_baza import BazaTestowa
from wyjatki import BladNornicy


class TestLinii(BazaTestowa):
    def test_parsuj_ilosc_komentarze_puste(self):
        pozycje = wsad.parsuj("Toshiba THM321000AS-70\n\n# komentarz\nSamsung KMM5322200AW-6 × 3\n"
                              "OKI MSC23136C-70BS10 x2\nHyundai HYM532100AM-60 *4\nX3 sam\nMODUŁ x 500\n")
        self.assertEqual([("Toshiba THM321000AS-70", 1), ("Samsung KMM5322200AW-6", 3),
                          ("OKI MSC23136C-70BS10", 2), ("Hyundai HYM532100AM-60", 4), ("X3 sam", 1),
                          ("MODUŁ", wsad.MAKS_ILOSC)], [(p.tekst, p.ilosc) for p in pozycje])
        self.assertEqual("KMM5321200AW-6x3", wsad.parsuj("KMM5321200AW-6x3")[0].tekst)   # bez spacji: część numeru

    def test_numery_bez_parametrow(self):
        self.assertEqual(["HY5DU56822BT-D43"],
                         propozycje.numery("256 MB DDR-400 PC3200, Hynix HY5DU56822BT-D43 / ABC DATA)"))
        self.assertEqual(["71.61323.010"], propozycje.numery("Apacer 71.61323.010 512MB 184-pin 60ns PC133 CL3 1998"))
        self.assertEqual("HY5DU56822BT-D43 datasheet",
                         propozycje.zapytanie("", "", "256 MB DDR-400 PC3200, Hynix HY5DU56822BT-D43"))


def _wynik(tekst_zrodla="KMM5322200AW-6 Fast Page Mode 16MB", **wartosci):
    zrodlo = Strona("Karta", "https://d.example/1", tekst_zrodla, True)
    lista = [Wartosc(kod, kod, w, t, zrodlo, c, True) for kod, (w, t, c) in wartosci.items()]
    return Wynik("q", lista, [zrodlo], "", "qwen3:8b")


class TestTworzenia(BazaTestowa):
    def setUp(self):
        super().setUp()
        ustaw_jezyk("pl")
        self.addCleanup(ustaw_jezyk, "en")
        self.kat = slowniki.kategoria_po_kodzie(self.db, "pamieci_ram")["id"]
        slowniki.producent_id(self.db, "Samsung", utworz=True)
        self.pudlo = self.lokalizacja("Pudło 7")
        self.status_ = slowniki.status_id(self.db, "nietestowany")

    def pozycja(self, tekst, ilosc=1, **wartosci):
        p = wsad.Pozycja(tekst, ilosc, _wynik(**wartosci))
        p.zaznaczone = set(wartosci)
        return p

    def test_dane_modelu_z_propozycji_i_linii(self):
        p = self.pozycja("Samsung KMM5322200AW-6",
                         technologia=("FPM", "FPM", "Fast Page Mode"), pojemnosc=(16 * 2 ** 20, "16 MB", "16MB"))
        dane = wsad.dane_modelu(self.db, p, self.kat)
        self.assertEqual(("Samsung", "KMM5322200AW-6"), (dane["producent"], dane["nazwa"]))   # producent z linii
        self.assertEqual({"technologia": "FPM", "pojemnosc": 16 * 2 ** 20}, dane["atrybuty"])
        self.assertEqual("https://d.example/1", dane["zrodlo_url"])
        self.assertIn("qwen3:8b", dane["opis"])
        p.zaznaczone.discard("pojemnosc")
        self.assertEqual({"technologia": "FPM"}, wsad.dane_modelu(self.db, p, self.kat)["atrybuty"])
        nieznany = self.pozycja("ABC 71.61323.010", **{PRODUCENT: ("Apacer", "Apacer", "Apacer"),
                                                       NAZWA: ("71.61323.010", "71.61323.010", "x")})
        dane = wsad.dane_modelu(self.db, nieznany, self.kat)
        self.assertEqual(("Apacer", "71.61323.010", "ABC 71.61323.010"),
                         (dane["producent"], dane["nazwa"], dane["numer_czesci"]))

    def test_utworz_modele_i_egzemplarze_bez_dublowania_modeli(self):
        pozycje = [self.pozycja("Samsung KMM5322200AW-6", 3, technologia=("FPM", "FPM", "x")),
                   self.pozycja("Toshiba THM321000AS-70", 1)]
        wynik = wsad.utworz(self.db, pozycje, self.kat, self.pudlo, self.status_, egzemplarze=True)
        self.assertEqual((2, 0, 4, None), (wynik.modele_nowe, wynik.modele_istniejace, wynik.egzemplarze, wynik.blad))
        w_pudle = self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE lokalizacja_id = ? AND status_id = ?",
                                  (self.pudlo, self.status_)).fetchone()[0]
        self.assertEqual(4, w_pudle)
        wynik = wsad.utworz(self.db, [self.pozycja("samsung kmm5322200aw-6")], self.kat)      # tylko modele
        self.assertEqual((0, 1, 0), (wynik.modele_nowe, wynik.modele_istniejace, wynik.egzemplarze))
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0])

    def test_blad_zatrzymuje_i_mowi_gdzie(self):
        pozycje = [self.pozycja("Samsung KMM5322200AW-6"), self.pozycja("Toshiba THM321000AS-70")]
        wynik = wsad.utworz(self.db, pozycje, self.kat, None, None, egzemplarze=True)   # bez statusu
        self.assertEqual("Samsung KMM5322200AW-6", wynik.nieudana)
        self.assertEqual("blad.wybierz_status", wynik.blad.klucz)
        pominiete = [self.pozycja("Toshiba THM321000AS-70")]
        pominiete[0].utworz = False
        self.assertEqual(0, wsad.utworz(self.db, pominiete, self.kat).modele_nowe)


class _Model:
    """Odpowiedź zależna od strony: wartości z tekstu źródła; „BLAD” w zapytaniu = wyjątek."""

    def czat(self, model, wiadomosci, schemat, anuluj):
        if "BLAD" in wiadomosci[1]["content"]:
            raise BladNornicy("asystent.blad_ollamy", opis="test")
        return {"producent": {"wartosc": "", "zrodlo": 0, "cytat": ""},
                "nazwa": {"wartosc": "", "zrodlo": 0, "cytat": ""},
                "pola": {"technologia": {"wartosc": "FPM", "zrodlo": 1, "cytat": "Fast Page Mode"},
                         "pojemnosc": {"wartosc": "16 MB", "zrodlo": 1, "cytat": "16MB"}},
                "uwagi": ""}


class _Szukarka:
    def __init__(self):
        self.zapytania = []

    def szukaj(self, zapytanie, ile):
        self.zapytania.append(zapytanie)
        numer = zapytanie.split()[0]
        return [Strona(numer, f"https://d.example/{numer}", "")]

    def pobierz(self, strona):
        return Strona(strona.tytul, strona.adres, f"{strona.tytul} Fast Page Mode 16MB", True)


class TestOknaWsadowego(test_gui.TestPrzebudowy):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        srodowisko = {k: v for k, v in os.environ.items() if k != "OLLAMA_API_KEY"}
        srodowisko["NORNICA_DANE"] = str(self.tmp)
        straznik = mock.patch.dict(os.environ, srodowisko, clear=True)
        straznik.start()
        self.addCleanup(straznik.stop)
        super().setUp()

    def okno_wsadowe(self, fabryka=None):
        self.szukarka = _Szukarka()
        okno = self.okno.asystent_ai(fabryka=fabryka or (lambda u: Asystent(_Model(), self.szukarka, u["model"])),
                                     lista_modeli=lambda u: ["qwen3:8b"])
        okno.czekaj_na_wynik()
        return okno

    def test_z_menu_jedno_okno_i_caly_przebieg(self):
        slowniki.producent_id(self.db, "Samsung", utworz=True)     # znany producent — z linii do modelu
        okno = self.okno_wsadowe()
        self.assertIs(okno, self.okno.asystent_ai())
        okno.linie.ustaw("Samsung KMM5322200AW-6 × 3\nToshiba THM321000AS-70\nBLAD123 x2")
        okno.tryb.set("egzemplarze")
        okno.lokalizacja.ustaw(self.polka)
        okno.uruchom()
        okno.czekaj_na_wynik()
        self.assertFalse(okno.pracuje)
        self.assertEqual(["KMM5322200AW-6 datasheet", "THM321000AS-70 datasheet", "BLAD123 datasheet"],
                         self.szukarka.zapytania)
        p1, p2, p3 = okno.pozycje
        self.assertEqual({"technologia", "pojemnosc"}, p1.zaznaczone)
        self.assertEqual(("asystent.blad_ollamy", False), (p3.blad.klucz, p3.utworz))   # błąd jednej pozycji
        drzewo = okno._drzewo
        self.assertEqual(["p0:pojemnosc", "p0:technologia"], list(drzewo.get_children("p0")))
        okno.przelacz("p1")                      # Toshiba — nie tworzyć
        okno.przelacz("p0:pojemnosc")            # bez pojemności w modelu Samsunga
        self.assertEqual("☐", drzewo.set("p1", "wstaw"))
        modele_przed = self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0]
        with mock.patch("tkinter.messagebox.askyesno", return_value=True) as pytanie:
            okno.utworz()
        self.assertIn("3", pytanie.call_args[0][1])                    # liczba sztuk w pytaniu
        self.assertEqual(modele_przed + 1, self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0])
        model = self.db.execute("SELECT m.*, p.nazwa AS producent FROM model m LEFT JOIN producent p "
                                "ON p.id = m.producent_id ORDER BY m.id DESC").fetchone()
        self.assertEqual("KMM5322200AW-6", model["nazwa"])
        self.assertIn('"technologia": "FPM"', model["atrybuty"])
        self.assertNotIn("pojemnosc", model["atrybuty"])
        self.assertEqual(3, self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE model_id = ? AND lokalizacja_id = ?",
                                            (model["id"], self.polka)).fetchone()[0])
        with mock.patch("tkinter.messagebox.askyesno", return_value=True):
            okno.utworz()                        # drugie kliknięcie nie dubluje
        self.assertEqual(3, self.db.execute("SELECT COUNT(*) FROM egzemplarz WHERE model_id = ?",
                                            (model["id"],)).fetchone()[0])
        self.assertIn("1", str(okno._stan.cget("text")))

    def test_rezygnacja_nic_nie_zapisuje_i_stan_przezywa_przebudowe(self):
        okno = self.okno_wsadowe()
        okno.linie.ustaw("Samsung KMM5322200AW-6")
        okno.uruchom()
        okno.czekaj_na_wynik()
        okno.przelacz("p0:technologia")
        modele_przed = self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0]
        with mock.patch("tkinter.messagebox.askyesno", return_value=False):
            okno.utworz()
        self.assertEqual(modele_przed, self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0])
        self.okno.przelacz_jezyk("pl")
        self.okno.przelacz_motyw("ciemny")
        self.okno.update()
        self.assertEqual({"pojemnosc"}, okno.pozycje[0].zaznaczone)
        self.assertEqual("Samsung KMM5322200AW-6", okno.linie.zapamietaj().strip())
        self.assertEqual("☐", okno._drzewo.set("p0:technologia", "wstaw"))

    def test_przerwanie_i_bledy_wejscia(self):
        okno = self.okno_wsadowe()
        okno.uruchom()                           # puste pole
        self.assertEqual("wsad.brak_linii", okno.blad.klucz)
        okno.linie.ustaw("\n".join(f"KM44C{n:04d}" for n in range(wsad.MAKS_POZYCJI + 1)))
        okno.uruchom()
        self.assertEqual("wsad.za_duzo", okno.blad.klucz)
        czeka = threading.Event()

        class Wolna(_Szukarka):
            def szukaj(self, zapytanie, ile):
                czeka.wait(2)
                return super().szukaj(zapytanie, ile)

        okno._fabryka = lambda u: Asystent(_Model(), Wolna(), "m")
        okno.linie.ustaw("KM44C4100\nKM44C4104")
        okno.uruchom()
        okno.przerwij()
        czeka.set()
        okno.czekaj_na_wynik()
        self.assertFalse(okno.pracuje)
        self.assertEqual("asystent.przerwano", okno.blad.klucz)
