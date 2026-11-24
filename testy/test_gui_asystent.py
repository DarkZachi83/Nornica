# SPDX-License-Identifier: GPL-3.0-or-later
"""Okno asystenta AI w oknie modelu: od propozycji do formularza, bez zapisu do bazy."""
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from asystent.propozycje import PRODUCENT, Asystent
from asystent.wyszukiwarki import Strona
from baza.repozytoria import slowniki, ustawienia
from testy import test_gui
from testy.test_asystent import _Model, _pole, _Wyszukiwarka
from wyjatki import BladNornicy

ODPOWIEDZ = {
    "producent": _pole("Samsung", 1, "Samsung KM44C4100C"),
    "nazwa": _pole("", 0),
    "pola": {"technologia": _pole("FPM", 1, "with Fast Page Mode"),
             "pojemnosc": _pole("16 MB", 1, "SIMM modules of 16MB"),
             "szybkosc": _pole("70 ns", 1, "Access time 70ns"),
             "strony": _pole("QS", 1, "x")},
    "uwagi": "EDO = KM44C4104."}


class TestOknaAsystenta(test_gui.TestPrzebudowy):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        srodowisko = {k: v for k, v in os.environ.items() if k != "OLLAMA_API_KEY"}
        srodowisko["NORNICA_DANE"] = str(self.tmp)            # klucz API nie trafi do prawdziwych danych
        straznik = mock.patch.dict(os.environ, srodowisko, clear=True)
        straznik.start()
        self.addCleanup(straznik.stop)
        super().setUp()
        from gui.okno_modelu import OknoModelu
        self.kat_ram = slowniki.kategoria_po_kodzie(self.db, "pamieci_ram")["id"]
        self.model_okno = OknoModelu(self.okno, None, self.kat_ram)
        self.model_okno.pokaz()
        self.model_okno.producent.set("Samsung")
        self.model_okno.v["nazwa"].set("KMM5321200AW-6")
        self.model_okno.v["numer_czesci"].set("KM44C4100CK-6")

    def asystent(self, odpowiedz=ODPOWIEDZ, lista_modeli=None):
        self.model = _Model(odpowiedz)
        self.wyszukiwarka = _Wyszukiwarka([Strona("Karta", "https://d.example/1", "s")])
        okno = self.model_okno.asystent(
            fabryka=lambda u: Asystent(self.model, self.wyszukiwarka, u["model"]),
            lista_modeli=lista_modeli or (lambda o: ["gemma3:4b", "qwen3:8b"]))
        okno.czekaj_na_wynik()
        return okno

    def test_propozycje_do_formularza_nie_do_bazy(self):
        okno = self.asystent()
        self.assertEqual(["gemma3:4b", "qwen3:8b"], okno.modele)
        self.assertEqual("KM44C4100CK-6", okno.oznaczenia.zapamietaj())     # z numeru części modelu
        okno.uruchom()
        okno.czekaj_na_wynik()
        self.assertIsNone(okno.blad)
        drzewo = okno._drzewo
        self.assertEqual([PRODUCENT, "pojemnosc", "technologia", "szybkosc", "strony"], list(drzewo.get_children()))
        # potwierdzone i różne od formularza — zaznaczone; producent już jest, 70 ns bez cytatu, QS spoza listy
        self.assertEqual({"pojemnosc", "technologia"}, okno.zaznaczone)
        self.assertEqual("☐", drzewo.set(PRODUCENT, "wstaw"))
        self.assertEqual("—", drzewo.set("strony", "wstaw"))
        okno.przelacz("strony")                        # błędna wartość — nie da się zaznaczyć
        okno.przelacz("szybkosc")                      # niepotwierdzona — świadomy wybór użytkownika
        self.assertEqual({"pojemnosc", "technologia", "szybkosc"}, okno.zaznaczone)
        liczba_modeli = self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0]
        okno.zastosuj()
        self.assertFalse(okno.winfo_exists())
        szablon = slowniki.szablon(self.db, self.kat_ram)
        formularz = {o["kod"]: self.model_okno.atrybuty.tekst_pola(o) for o in szablon}
        self.assertEqual("FPM", formularz["technologia"])
        self.assertEqual("70 ns", formularz["szybkosc"])
        self.assertEqual("", formularz["strony"])
        self.assertEqual(16 * 1024 ** 2, self.model_okno.atrybuty.pola["pojemnosc"].bajty())
        self.assertEqual("https://d.example/1", self.model_okno.v["zrodlo_url"].get())
        self.assertIn("qwen3:8b", self.model_okno.opis.zapamietaj())
        self.assertIn("https://d.example/1", self.model_okno.opis.zapamietaj())
        self.assertEqual(liczba_modeli, self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0])
        self.model_okno.zapisz()                       # dopiero „Zapisz” tworzy model
        self.assertEqual(liczba_modeli + 1, self.db.execute("SELECT COUNT(*) FROM model").fetchone()[0])

    def test_ustawienia_zapamietane_klucz_poza_baza(self):
        okno = self.asystent()
        okno.model.set("gemma3:4b")
        okno.klucz.set("klucz-123")
        okno.uruchom()
        okno.czekaj_na_wynik()
        self.assertEqual("gemma3:4b", ustawienia.pobierz(self.db, "asystent_model"))
        self.assertEqual("ollama", ustawienia.pobierz(self.db, "asystent_zrodlo"))
        self.assertEqual("klucz-123", (self.tmp / "ollama_klucz.txt").read_text(encoding="utf-8"))
        zrzut = "\n".join(self.db.iterdump())
        self.assertNotIn("klucz-123", zrzut)            # klucz nie trafia do bazy ani kopii

    def test_stan_przezywa_zmiane_jezyka_i_motywu(self):
        okno = self.asystent()
        okno.uruchom()
        okno.czekaj_na_wynik()
        okno.przelacz("technologia")
        self.okno.przelacz_jezyk("pl")
        self.okno.przelacz_motyw("ciemny")
        self.okno.update()
        self.assertTrue(okno.winfo_exists())
        self.assertEqual({"pojemnosc"}, okno.zaznaczone)
        self.assertEqual("☐", okno._drzewo.set("technologia", "wstaw"))
        self.assertEqual("Szukaj i zaproponuj", str(okno._start.cget("text")))
        self.assertEqual("technologia", okno._wartosc("technologia").kod)

    def test_brak_ollamy_i_blad_w_trakcie(self):
        def bez_ollamy(_o):
            raise BladNornicy("asystent.brak_ollamy", adres="http://127.0.0.1:11434", opis="refused")
        okno = self.asystent(lista_modeli=bez_ollamy)
        self.assertEqual([], okno.modele)
        self.assertIn("ollama pull", str(okno._stan_ollamy.cget("text")))
        okno._fabryka = lambda u: (_ for _ in ()).throw(BladNornicy("asystent.brak_klucza"))
        okno.uruchom()
        okno.czekaj_na_wynik()
        self.assertFalse(okno.pracuje)
        self.assertEqual("asystent.brak_klucza", okno.blad.klucz)
        self.assertIn("ollama.com", str(okno._stan.cget("text")))
        okno.zastosuj()                                 # nic do wstawienia — okno zostaje
        self.assertTrue(okno.winfo_exists())

    def test_bez_kategorii_komunikat(self):
        self.model_okno.kategoria.ustaw(None)
        with mock.patch("tkinter.messagebox.showerror") as komunikat:
            self.assertIsNone(self.model_okno.asystent())
        from i18n.tlumacz import t
        self.assertEqual(t("asystent.wybierz_kategorie"), komunikat.call_args[0][1])
