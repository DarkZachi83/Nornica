# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy warstwy tłumaczeń.

Dwa pierwsze to lekcje z Jaźwca: te same klucze i te same pola formatowania
w obu słownikach. Kolejne pilnują, żeby każdy klucz użyty w kodzie, w SQL
i w wyliczeniach naprawdę istniał.
"""
import json
import re
import string
import unittest
from pathlib import Path

from baza.enumy import ENUMY
from baza import dane_startowe
from i18n import tlumacz
from i18n.tlumacz import JEZYKI, nazwa, t, ustaw_jezyk

KORZEN = Path(__file__).resolve().parents[1]
KATALOG_SCHEMATU = KORZEN / "baza" / "schemat"


def _caly_schemat():
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(KATALOG_SCHEMATU.glob("*.sql")))


def _slownik(jezyk):
    return json.loads((KORZEN / "i18n" / f"{jezyk}.json").read_text(encoding="utf-8"))


def _pola(tekst):
    return {pole for _, pole, _, _ in string.Formatter().parse(tekst) if pole is not None}


class TestSlownikow(unittest.TestCase):
    def setUp(self):
        self.slowniki = {jezyk: _slownik(jezyk) for jezyk in JEZYKI}
        self.wzorzec = self.slowniki[tlumacz.JEZYK_DOMYSLNY]

    def test_te_same_klucze(self):
        for jezyk, slownik in self.slowniki.items():
            with self.subTest(jezyk=jezyk):
                self.assertEqual(set(), set(self.wzorzec) - set(slownik), "brakujące klucze")
                self.assertEqual(set(), set(slownik) - set(self.wzorzec), "nadmiarowe klucze")

    def test_te_same_pola_formatowania(self):
        for jezyk, slownik in self.slowniki.items():
            for klucz, tekst in self.wzorzec.items():
                with self.subTest(jezyk=jezyk, klucz=klucz):
                    self.assertEqual(_pola(tekst), _pola(slownik.get(klucz, "")))

    def test_brak_pustych_tekstow(self):
        for jezyk, slownik in self.slowniki.items():
            for klucz, tekst in slownik.items():
                with self.subTest(jezyk=jezyk, klucz=klucz):
                    self.assertTrue(tekst.strip())

    def test_klucze_uzyte_w_kodzie_istnieja(self):
        # t("klucz"...) oraz BladNornicy("klucz"...) z pełnym literałem tekstowym.
        # Klucze składane dynamicznie (np. 'tabela.' + nazwa) mają osobne testy.
        wzor = re.compile(r"""(?:\bt|BladNornicy)\(\s*["']([\w.]+)["']\s*[,)]""")
        brakujace = []
        for plik in KORZEN.rglob("*.py"):
            if "testy" in plik.parts:
                continue
            for klucz in wzor.findall(plik.read_text(encoding="utf-8")):
                if klucz not in self.wzorzec:
                    brakujace.append(f"{plik.name}: {klucz}")
        self.assertEqual([], brakujace)

    def test_wszystkie_literaly_kluczy_istnieja(self):
        """Klucze przekazywane pośrednio — w krotkach, przez funkcje pomocnicze
        (np. etykieta("pole.kategoria", ...)) — omija test wywołań t().
        Ten test sprawdza każdy literał w postaci przedrostek.reszta, którego
        przedrostek występuje w słowniku. Identyfikatory pól wyliczeniowych
        ("zasob.typ" itp.) nie są kluczami i są pomijane."""
        przedrostki = {k.split(".")[0] for k in self.wzorzec}
        nie_klucze = set(ENUMY) | {p for p, _ in ENUMY.values()}
        wzor = re.compile(r"""["']([a-z_]+\.[a-z_][a-z0-9_.]*)["']""")
        brakujace = []
        for plik in KORZEN.rglob("*.py"):
            if "testy" in plik.parts or plik.name == "enumy.py":
                continue
            for klucz in wzor.findall(plik.read_text(encoding="utf-8")):
                nazwa_pliku = klucz.rsplit(".", 1)[-1] in {"html", "js", "png", "json", "crt", "key",
                                                           "pdf", "csv", "sql", "ico", "txt", "jpeg"}
                if (klucz.split(".")[0] in przedrostki and klucz not in nie_klucze and not nazwa_pliku
                        and not klucz.endswith(".") and klucz not in self.wzorzec):
                    brakujace.append(f"{plik.relative_to(KORZEN)}: {klucz}")
        self.assertEqual([], sorted(set(brakujace)))

    def test_klucze_z_sql_istnieja(self):
        sql = _caly_schemat()
        klucze = set(re.findall(r"RAISE\(ABORT,\s*'([\w.]+)'\)", sql))
        klucze |= {f"blad.{n}" for n in re.findall(r"CONSTRAINT\s+(\w+)\s+CHECK", sql)}
        self.assertTrue(klucze)
        self.assertEqual(set(), klucze - set(self.wzorzec))

    def test_enumy_maja_tlumaczenia(self):
        for pole, (przedrostek, wartosci) in ENUMY.items():
            for wartosc in wartosci:
                with self.subTest(pole=pole, wartosc=wartosc):
                    self.assertIn(f"{przedrostek}.{wartosc}", self.wzorzec)

    def test_enumy_zgodne_ze_schematem(self):
        sql = _caly_schemat()
        znalezione = {}
        for blok in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", sql, re.S):
            tabela, tresc = blok.groups()
            for kolumna, lista in re.findall(r"CHECK \((\w+) IN\s*\(([^)]*)\)\)", tresc):
                wartosci = tuple(re.findall(r"'(\w+)'", lista))
                if wartosci:
                    znalezione[f"{tabela}.{kolumna}"] = wartosci
        oczekiwane = {pole: wartosci for pole, (_, wartosci) in ENUMY.items()}
        self.assertEqual(oczekiwane, znalezione)

    def test_dane_startowe_dwujezyczne(self):
        def sprawdz(nazwy, opis):
            for jezyk in JEZYKI:
                self.assertTrue(nazwy.get(jezyk), f"{opis}: brak '{jezyk}'")
        for kod, nazwy in dane_startowe.STATUSY:
            sprawdz(nazwy, kod)
        for kod, nazwy, _, _ in dane_startowe.WALUTY:
            sprawdz(nazwy, kod)
        for kod, _, en, pl in dane_startowe.ZLACZA:
            self.assertTrue(en and pl, kod)
        for kat in dane_startowe.KATEGORIE:
            sprawdz(kat["nazwy"], kat["kod"])
            for pole in kat["szablon"]:
                sprawdz(pole["nazwy"], f"{kat['kod']}.{pole['kod']}")


class TestZabezpieczen(unittest.TestCase):
    def tearDown(self):
        ustaw_jezyk(tlumacz.JEZYK_DOMYSLNY)

    def test_nieznany_jezyk_spada_do_domyslnego(self):
        self.assertEqual("VOLE", t("aplikacja.nazwa", "xx"))
        self.assertEqual("en", ustaw_jezyk("klingon"))

    def test_brakujacy_klucz_zwraca_klucz(self):
        self.assertEqual("nie.ma.takiego", t("nie.ma.takiego"))

    def test_zle_pola_nie_wywracaja(self):
        with self.assertLogs("i18n.tlumacz", level="WARNING"):
            tekst = t("blad.baza_ogolny", inne_pole=1)
        self.assertIn("{szczegoly}", tekst)

    def test_przelaczanie_tam_i_z_powrotem(self):
        ustaw_jezyk("pl")
        self.assertEqual("NORNICA", t("aplikacja.nazwa"))
        ustaw_jezyk("en")
        self.assertEqual("VOLE", t("aplikacja.nazwa"))

    def test_nazwa_z_json(self):
        self.assertEqual("Karty", nazwa('{"en": "Cards", "pl": "Karty"}', "pl"))
        self.assertEqual("Cards", nazwa({"en": "Cards"}, "pl"))
        self.assertEqual("Własne", nazwa({"pl": "Własne"}, "en"))
        self.assertEqual("", nazwa(None))


if __name__ == "__main__":
    unittest.main()
