# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy architektury: pilnują podziału na warstwy i rozmiaru modułów.

  baza/      — SQL, migracje, repozytoria (odczyt i zapis wierszy),
  uslugi/    — reguły programu, bez interfejsu,
  gui/       — okna; dane czyta przez repozytoria, zmienia przez usługi.

Limity rozmiaru nie są celem samym w sobie: plik albo funkcja, która je
przekracza, zwykle robi kilka rzeczy naraz. Wtedy dzielimy ją, zamiast
podnosić limit.
"""
import ast
import re
import unittest
from pathlib import Path

KORZEN = Path(__file__).resolve().parents[1]
MAKS_LINII_PLIKU = 600
MAKS_LINII_FUNKCJI = 90
# tkinter poza gui/: punkt startowy i samosprawdzenie wersji .exe (czy biblioteka jest w paczce)
TKINTER_POZA_GUI = {"nornica.py", "uslugi/autotest.py"}


def _pliki_programu():
    for plik in sorted(KORZEN.rglob("*.py")):
        sciezka = plik.relative_to(KORZEN)
        if sciezka.parts[0] in ("testy", ".git", "build", "dist") or "schemat" in sciezka.parts:
            continue
        yield sciezka.as_posix(), plik.read_text(encoding="utf-8")


def _importy(tekst: str) -> set[str]:
    wynik = set()
    for wezel in ast.walk(ast.parse(tekst)):
        if isinstance(wezel, ast.Import):
            wynik |= {a.name.split(".")[0] for a in wezel.names}
        elif isinstance(wezel, ast.ImportFrom) and wezel.module and not wezel.level:
            wynik.add(wezel.module.split(".")[0])
    return wynik


class TestWarstw(unittest.TestCase):
    def test_gui_nie_wykonuje_zapytan_sql(self):
        """Okna czytają przez baza/repozytoria i zmieniają przez uslugi/."""
        z_sql = [sciezka for sciezka, tekst in _pliki_programu()
                 if sciezka.startswith("gui/") and re.search(r"\.execute(many|script)?\(", tekst)]
        self.assertEqual([], z_sql)

    def test_baza_i_uslugi_nie_zaleza_od_interfejsu(self):
        bledne = []
        for sciezka, tekst in _pliki_programu():
            if not sciezka.startswith(("baza/", "uslugi/", "raporty/")):
                continue
            importy = _importy(tekst)
            if "gui" in importy or ("tkinter" in importy and sciezka not in TKINTER_POZA_GUI):
                bledne.append(sciezka)
        self.assertEqual([], bledne)

    def test_tkinter_tylko_w_interfejsie(self):
        poza = {sciezka for sciezka, tekst in _pliki_programu()
                if not sciezka.startswith("gui/") and "tkinter" in _importy(tekst)}
        self.assertEqual(set(), poza - TKINTER_POZA_GUI)


class TestRozmiaru(unittest.TestCase):
    def test_pliki_nie_rosna_ponad_limit(self):
        za_duze = {sciezka: tekst.count("\n") for sciezka, tekst in _pliki_programu()
                   if tekst.count("\n") > MAKS_LINII_PLIKU}
        self.assertEqual({}, za_duze, f"podziel moduł (limit {MAKS_LINII_PLIKU} linii)")

    def test_funkcje_nie_rosna_ponad_limit(self):
        za_dlugie = {}
        for sciezka, tekst in _pliki_programu():
            for wezel in ast.walk(ast.parse(tekst)):
                if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    dlugosc = wezel.end_lineno - wezel.lineno + 1
                    if dlugosc > MAKS_LINII_FUNKCJI:
                        za_dlugie[f"{sciezka}:{wezel.name}"] = dlugosc
        self.assertEqual({}, za_dlugie, f"podziel funkcję (limit {MAKS_LINII_FUNKCJI} linii)")


if __name__ == "__main__":
    unittest.main()
