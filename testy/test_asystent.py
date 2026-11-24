# SPDX-License-Identifier: GPL-3.0-or-later
"""Asystent AI bez prawdziwej Ollamy i bez internetu: klient Ollamy i wyszukiwarki
rozmawiają z podstawionymi serwerami HTTP na 127.0.0.1, model i wyszukiwarka
w teście całości są zamiennikami."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from asystent import ollama, propozycje, wyszukiwarki
from asystent.ollama import Ollama, Przerwano
from asystent.propozycje import NAZWA, PRODUCENT, Asystent, konwertuj, potwierdzony
from asystent.wyszukiwarki import OllamaWeb, SearXNG, Strona
from i18n.tlumacz import ustaw_jezyk
from wyjatki import BladNornicy


class _Serwer:
    """Serwer HTTP na losowym porcie; obsluga(handler) decyduje o odpowiedzi."""

    def __init__(self, obsluga):
        self.zapytania: list[dict] = []
        serwer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _obsluz(self):
                dlugosc = int(self.headers.get("Content-Length") or 0)
                tresc = self.rfile.read(dlugosc) if dlugosc else b""
                serwer.zapytania.append({"sciezka": self.path, "naglowki": dict(self.headers),
                                         "tresc": json.loads(tresc) if tresc else None})
                obsluga(self, serwer.zapytania[-1])

            do_GET = do_POST = _obsluz

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.adres = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def zamknij(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _json(handler, dane, kod=200, typ="application/json"):
    tresc = dane if isinstance(dane, bytes) else json.dumps(dane).encode("utf-8")
    handler.send_response(kod)
    handler.send_header("Content-Type", typ)
    handler.send_header("Content-Length", str(len(tresc)))
    handler.end_headers()
    handler.wfile.write(tresc)


def _strumien(handler, kawalki, przerwa=0.0):
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson")
    handler.end_headers()
    try:
        for kawalek in kawalki:
            handler.wfile.write((json.dumps(kawalek) + "\n").encode("utf-8"))
            handler.wfile.flush()
            time.sleep(przerwa)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _odpowiedz_modelu(tekst):
    """Tekst rozbity na kawałki jak w strumieniu Ollamy."""
    kawalki = [{"message": {"content": tekst[i:i + 7]}, "done": False} for i in range(0, len(tekst), 7)]
    return kawalki + [{"message": {"content": ""}, "done": True}]


class TestOllamy(unittest.TestCase):
    def serwer(self, obsluga):
        s = _Serwer(obsluga)
        self.addCleanup(s.zamknij)
        return s

    def test_tylko_ten_komputer(self):
        for dobry in ("http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434", None):
            self.assertTrue(ollama.sprawdz_adres(dobry).startswith("http"))
        for zly in ("http://192.168.1.5:11434", "https://ollama.com", "ftp://127.0.0.1", "127.0.0.1:11434"):
            with self.subTest(adres=zly), self.assertRaises(BladNornicy) as blad:
                Ollama(zly)
            self.assertEqual("asystent.blad_adres_ollamy", blad.exception.klucz)

    def test_lista_modeli(self):
        s = self.serwer(lambda h, z: _json(h, {"models": [{"name": "qwen3:8b"}, {"name": "gemma3:4b"}]}))
        self.assertEqual(["gemma3:4b", "qwen3:8b"], Ollama(s.adres).modele())
        self.assertEqual("/api/tags", s.zapytania[0]["sciezka"])

    def test_brak_ollamy_to_czytelny_blad(self):
        s = _Serwer(lambda h, z: None)
        adres = s.adres
        s.zamknij()                          # port wolny — nikt nie słucha
        with self.assertRaises(BladNornicy) as blad:
            Ollama(adres, czas=2).modele()
        self.assertEqual("asystent.brak_ollamy", blad.exception.klucz)

    def test_czat_ze_schematem_i_strumieniem(self):
        s = self.serwer(lambda h, z: _strumien(h, _odpowiedz_modelu('{"a": "Fast Page Mode", "b": 1}')))
        wynik = Ollama(s.adres).czat("qwen3:8b", [{"role": "user", "content": "x"}], {"type": "object"})
        self.assertEqual({"a": "Fast Page Mode", "b": 1}, wynik)
        tresc = s.zapytania[0]["tresc"]
        self.assertEqual({"type": "object"}, tresc["format"])
        self.assertIs(False, tresc["think"])
        self.assertEqual(0, tresc["options"]["temperature"])
        self.assertTrue(tresc["stream"])

    def test_model_bez_myslenia_dostaje_zapytanie_bez_think(self):
        def obsluga(h, z):
            if "think" in z["tresc"]:
                _json(h, {"error": '"gemma3:4b" does not support thinking'}, 400)
            else:
                _strumien(h, _odpowiedz_modelu('{"ok": true}'))
        s = self.serwer(obsluga)
        self.assertEqual({"ok": True}, Ollama(s.adres).czat("gemma3:4b", [], {}))
        self.assertEqual(2, len(s.zapytania))

    def test_blad_modelu_i_zla_odpowiedz(self):
        s = self.serwer(lambda h, z: _json(h, {"error": "model 'x' not found"}, 404))
        with self.assertRaises(BladNornicy) as blad:
            Ollama(s.adres).czat("x", [], {})
        self.assertEqual("asystent.blad_ollamy", blad.exception.klucz)
        self.assertIn("not found", blad.exception.pola["opis"])
        s2 = self.serwer(lambda h, z: _strumien(h, _odpowiedz_modelu("to nie jest JSON")))
        with self.assertRaises(BladNornicy) as blad:
            Ollama(s2.adres).czat("x", [], {})
        self.assertEqual("asystent.blad_odpowiedzi", blad.exception.klucz)

    def test_przerwanie_w_trakcie_generowania(self):
        s = self.serwer(lambda h, z: _strumien(h, _odpowiedz_modelu("x" * 400), przerwa=0.05))
        anuluj = threading.Event()
        threading.Timer(0.3, anuluj.set).start()
        start = time.monotonic()
        with self.assertRaises(Przerwano):
            Ollama(s.adres).czat("qwen3:8b", [], {}, anuluj)
        self.assertLess(time.monotonic() - start, 2.5)      # bez czekania na koniec (≈3 s)


class TestWyszukiwarek(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        srodowisko = {k: v for k, v in os.environ.items() if k != "OLLAMA_API_KEY"}
        srodowisko["NORNICA_DANE"] = str(self.tmp)
        straznik = mock.patch.dict(os.environ, srodowisko, clear=True)
        straznik.start()
        self.addCleanup(straznik.stop)

    def serwer(self, obsluga):
        s = _Serwer(obsluga)
        self.addCleanup(s.zamknij)
        return s

    def test_html_na_tekst(self):
        html = ("<html><head><title>T</title><style>x{}</style></head><body><script>alert(1)</script>"
                "<h1>KM44C4100</h1><table><tr><td>Mode</td><td>Fast&nbsp;Page</td></tr></table><p>a\n\n b</p></body></html>")
        self.assertEqual("KM44C4100\nMode | Fast Page\na\nb", wyszukiwarki.html_na_tekst(html))

    def test_klucz_api_plik_tylko_dla_wlasciciela_i_zmienna(self):
        self.assertEqual("", wyszukiwarki.klucz_api())
        wyszukiwarki.zapisz_klucz("  tajny  ")
        self.assertEqual("tajny", wyszukiwarki.klucz_api())
        plik = self.tmp / wyszukiwarki.PLIK_KLUCZA
        if sys.platform != "win32":
            self.assertEqual(0o600, plik.stat().st_mode & 0o777)
        with mock.patch.dict(os.environ, {"OLLAMA_API_KEY": "zmienna"}):
            self.assertEqual("zmienna", wyszukiwarki.klucz_api())
        wyszukiwarki.zapisz_klucz("")
        self.assertFalse(plik.exists())

    def test_ollama_web(self):
        def obsluga(h, z):
            if z["naglowki"].get("Authorization") != "Bearer k1":
                return _json(h, {"error": "unauthorized"}, 401)
            if z["sciezka"] == "/api/web_search":
                return _json(h, {"results": [{"title": "KM44", "url": "https://a.example/1", "content": "snip"},
                                             {"title": "bez adresu"}]})
            return _json(h, {"title": "Pełny", "content": "Fast Page Mode DRAM", "links": []})
        s = self.serwer(obsluga)
        web = OllamaWeb("k1", s.adres)
        strony = web.szukaj("KM44 datasheet", 3)
        self.assertEqual([Strona("KM44", "https://a.example/1", "snip")], strony)
        self.assertEqual({"query": "KM44 datasheet", "max_results": 3}, s.zapytania[0]["tresc"])
        pelna = web.pobierz(strony[0])
        self.assertEqual(("Pełny", "Fast Page Mode DRAM", True), (pelna.tytul, pelna.tekst, pelna.pelna))
        with self.assertRaises(BladNornicy) as blad:
            OllamaWeb("zly", s.adres).szukaj("x")
        self.assertEqual("asystent.blad_klucza", blad.exception.klucz)
        with self.assertRaises(BladNornicy) as blad:
            OllamaWeb()                      # brak klucza w zmiennej i w pliku
        self.assertEqual("asystent.brak_klucza", blad.exception.klucz)

    def test_limit_konta_z_wyjasnieniem_serwera(self):
        s = self.serwer(lambda h, z: _json(h, {"error": "weekly web search limit reached"}, 402))
        with self.assertRaises(BladNornicy) as blad:
            OllamaWeb("k1", s.adres).szukaj("x")
        self.assertEqual("asystent.limit_wyszukiwania", blad.exception.klucz)
        self.assertEqual("HTTP 402: weekly web search limit reached", blad.exception.pola["opis"])
        s2 = self.serwer(lambda h, z: _json(h, b"<html>error</html>", 500, "text/html"))
        with self.assertRaises(BladNornicy) as blad:
            OllamaWeb("k1", s2.adres).szukaj("x")
        self.assertEqual(("asystent.blad_sieci", "HTTP 500"), (blad.exception.klucz, blad.exception.pola["opis"]))
        with self.assertRaises(BladNornicy) as blad:
            OllamaWeb()
        self.assertEqual("asystent.brak_klucza", blad.exception.klucz)

    def test_searxng_i_pobieranie_stron(self):
        def obsluga(h, z):
            if z["sciezka"].startswith("/search"):
                return _json(h, {"results": [{"title": "Strona", "url": f"{s.adres}/strona", "content": "s1"},
                                             {"title": "PDF", "url": f"{s.adres}/plik.pdf", "content": "s2"}]})
            if z["sciezka"] == "/strona":
                return _json(h, b"<html><body><p>Extended Data Out</p></body></html>", typ="text/html; charset=utf-8")
            return _json(h, b"%PDF-1.4", typ="application/pdf")
        s = self.serwer(obsluga)
        szukarka = SearXNG(s.adres + "/")
        strony = szukarka.szukaj("KM44C4104 datasheet")
        self.assertIn("format=json", s.zapytania[0]["sciezka"])
        self.assertEqual(["Strona", "PDF"], [x.tytul for x in strony])
        self.assertEqual(("Extended Data Out", True), (szukarka.pobierz(strony[0]).tekst, szukarka.pobierz(strony[0]).pelna))
        self.assertEqual(strony[1], szukarka.pobierz(strony[1]))      # PDF: zostaje fragment z wyników

    def test_searxng_bez_formatu_json(self):
        s = self.serwer(lambda h, z: _json(h, b"Forbidden", 403, "text/plain"))
        with self.assertRaises(BladNornicy) as blad:
            SearXNG(s.adres).szukaj("x")
        self.assertEqual("asystent.searxng_bez_json", blad.exception.klucz)
        with self.assertRaises(BladNornicy):
            SearXNG("")


RAM = [
    {"kod": "pojemnosc", "typ": "pojemnosc", "nazwy": {"en": "Capacity", "pl": "Pojemność"}},
    {"kod": "technologia", "typ": "enum", "nazwy": {"en": "Technology", "pl": "Technologia"},
     "wartosci": ["DRAM", "FPM", "EDO", "SDRAM"]},
    {"kod": "szybkosc", "typ": "text", "nazwy": {"en": "Speed", "pl": "Szybkość"}},
    {"kod": "napiecie", "typ": "zakres", "jednostka": "V", "nazwy": {"en": "Voltage", "pl": "Napięcie"}},
    {"kod": "piny", "typ": "int", "nazwy": {"en": "Pins", "pl": "Piny"}},
    {"kod": "buforowana", "typ": "bool", "nazwy": {"en": "Buffered", "pl": "Buforowana"}},
]
TEKST = ("Samsung KM44C4100C — 4M x 4 bit CMOS dynamic RAM with Fast Page Mode. "
         "Access time 60ns. Supply 4.5–5.5 V. Used on 72-pin SIMM modules of 16MB.")


class _Wyszukiwarka:
    def __init__(self, strony):
        self.strony, self.pobrane = strony, []

    def szukaj(self, zapytanie, ile):
        self.zapytanie = zapytanie
        return self.strony[:ile]

    def pobierz(self, strona):
        self.pobrane.append(strona.adres)
        return Strona(strona.tytul, strona.adres, TEKST if strona.adres.endswith("/1") else "inna strona", True)


class _Model:
    def __init__(self, odpowiedz):
        self.odpowiedz, self.wiadomosci = odpowiedz, None

    def czat(self, model, wiadomosci, schemat, anuluj):
        self.wiadomosci, self.schemat = wiadomosci, schemat
        return self.odpowiedz


def _pole(wartosc, zrodlo=1, cytat=""):
    return {"wartosc": wartosc, "zrodlo": zrodlo, "cytat": cytat}


class TestPropozycji(unittest.TestCase):
    def setUp(self):
        ustaw_jezyk("pl")
        self.addCleanup(ustaw_jezyk, "en")

    def test_zapytanie(self):
        self.assertEqual("Samsung KMM5321200AW-6 KM44C4100CK-6 datasheet",
                         propozycje.zapytanie("Samsung", "KMM5321200AW-6", "KM44C4100CK-6 (8 kości)\nSEC 9512"))
        self.assertEqual("TC514400AJ-70 M514400B-60 datasheet",
                         propozycje.zapytanie("", "", "Toshiba TC514400AJ-70, OKI M514400B-60"))
        self.assertEqual("OKI datasheet", propozycje.zapytanie("OKI", "oki", ""))
        self.assertEqual("", propozycje.zapytanie())

    def test_konwersja_wartosci(self):
        opisy = {o["kod"]: o for o in RAM}
        self.assertEqual(16 * 1024 ** 2, konwertuj(opisy["pojemnosc"], "16 MB"))
        self.assertEqual(16 * 1024 ** 2, konwertuj(opisy["pojemnosc"], "16MiB"))
        self.assertEqual("EDO", konwertuj(opisy["technologia"], "edo"))
        self.assertEqual([4.5, 5.5], konwertuj(opisy["napiecie"], "4.5–5.5 V"))
        self.assertEqual(5.0, konwertuj(opisy["napiecie"], "5V"))
        self.assertEqual(72, konwertuj(opisy["piny"], "72"))
        self.assertIs(True, konwertuj(opisy["buforowana"], "Yes"))
        self.assertEqual("60 ns", konwertuj(opisy["szybkosc"], " 60 ns "))
        for kod, zle in (("technologia", "EDO DRAM"), ("pojemnosc", "duża"), ("piny", "72 piny"),
                         ("buforowana", "chyba"), ("napiecie", "5 do 6")):
            with self.subTest(kod=kod), self.assertRaises(ValueError):
                konwertuj(opisy[kod], zle)

    def test_cytat_musi_byc_w_zrodle(self):
        zrodlo = Strona("t", "https://x", TEKST)
        self.assertTrue(potwierdzony("with  FAST page mode", zrodlo))
        self.assertTrue(potwierdzony("Supply 4.5-5.5 V", zrodlo))        # myślnik ujednolicony
        self.assertFalse(potwierdzony("Access time 70ns", zrodlo))
        self.assertFalse(potwierdzony("ns", zrodlo))                     # za krótki
        self.assertFalse(potwierdzony("Fast Page Mode", None))

    def test_schemat_wymusza_liste_wyboru(self):
        schemat = propozycje.schemat(RAM)
        pola = schemat["properties"]["pola"]
        self.assertEqual([o["kod"] for o in RAM], pola["required"])
        self.assertEqual(["DRAM", "FPM", "EDO", "SDRAM", ""],
                         pola["properties"]["technologia"]["properties"]["wartosc"]["enum"])
        self.assertEqual({"wartosc", "zrodlo", "cytat"}, set(pola["properties"]["pojemnosc"]["required"]))

    def test_wycinek_zaczyna_sie_przy_przedmiocie(self):
        tekst = "menu " * 2000 + "KM44C4100 Fast Page Mode" + " stopka" * 500
        wycinek = propozycje.wycinek(tekst, ["km44c4100"], 1000)
        self.assertIn("KM44C4100 Fast Page Mode", wycinek)
        self.assertEqual(1000, len(wycinek))

    def test_caly_przebieg_fpm(self):
        strony = [Strona(f"Wynik {i}", f"https://d.example/{i}", "fragment") for i in range(1, 6)]
        wyszukiwarka = _Wyszukiwarka(strony)
        model = _Model({
            "producent": _pole("Samsung", 1, "Samsung KM44C4100C"),
            "nazwa": _pole("", 0),
            "pola": {"technologia": _pole("FPM", 1, "dynamic RAM with Fast Page Mode"),
                     "pojemnosc": _pole("16 MB", 1, "SIMM modules of 16MB"),
                     "szybkosc": _pole("70 ns", 1, "Access time 70ns"),           # zmyślone
                     "napiecie": _pole("4.5-5.5", 2, "Supply 4.5–5.5 V"),        # zły numer źródła
                     "piny": _pole("72-pin", 1, "72-pin SIMM"),                  # nie liczba
                     "buforowana": _pole("", 0)},
            "uwagi": "Wersja EDO ma oznaczenie KM44C4104."})
        kroki = []
        wynik = Asystent(model, wyszukiwarka, "qwen3:8b").zaproponuj(
            RAM, {"kategoria": "Pamięci RAM", "producent": "Samsung", "nazwa": "", "oznaczenia": "KM44C4100CK-6"},
            postep=lambda klucz, **p: kroki.append(klucz))
        self.assertEqual("Samsung KM44C4100CK-6 datasheet", wyszukiwarka.zapytanie)
        self.assertEqual(3, len(wyszukiwarka.pobrane))                     # tylko pierwsze trzy strony
        self.assertEqual(["asystent.krok_szukam", "asystent.krok_pobieram", "asystent.krok_pobieram",
                          "asystent.krok_pobieram", "asystent.krok_mysle", "asystent.krok_sprawdzam"], kroki)
        w = {x.kod: x for x in wynik.wartosci}
        self.assertEqual([PRODUCENT, "pojemnosc", "technologia", "szybkosc", "napiecie", "piny"], list(w))
        self.assertTrue(w["technologia"].potwierdzona)
        self.assertEqual(16 * 1024 ** 2, w["pojemnosc"].wartosc)
        self.assertEqual("16 MB", w["pojemnosc"].tekst)
        self.assertFalse(w["szybkosc"].potwierdzona)
        self.assertFalse(w["napiecie"].potwierdzona)                       # cytat nie z tej strony
        self.assertEqual("asystent.wartosc_niezgodna", w["piny"].blad)
        self.assertFalse(w["piny"].mozna_wstawic)
        self.assertEqual({"technologia": "FPM", "pojemnosc": 16 * 1024 ** 2},
                         wynik.atrybuty({"technologia", "pojemnosc", "piny", PRODUCENT}))
        self.assertEqual(("qwen3:8b", "Wersja EDO ma oznaczenie KM44C4104."), (wynik.model, wynik.uwagi))
        polecenie = model.wiadomosci[1]["content"]
        self.assertIn("allowed: DRAM, FPM, EDO, SDRAM", polecenie)
        self.assertIn("[1] Wynik 1\nhttps://d.example/1", polecenie)
        self.assertIn("Polish", model.wiadomosci[0]["content"])

    def test_bez_wynikow_i_przerwanie(self):
        with self.assertRaises(BladNornicy) as blad:
            Asystent(_Model({}), _Wyszukiwarka([]), "m").zaproponuj(RAM, {"nazwa": "XYZ123"})
        self.assertEqual("asystent.brak_wynikow", blad.exception.klucz)
        with self.assertRaises(BladNornicy) as blad:
            Asystent(_Model({}), _Wyszukiwarka([]), "m").zaproponuj(RAM, {})
        self.assertEqual("asystent.brak_opisu", blad.exception.klucz)
        anuluj = threading.Event()
        anuluj.set()
        with self.assertRaises(Przerwano):
            Asystent(_Model({}), _Wyszukiwarka([Strona("a", "https://a/1", "")]), "m").zaproponuj(
                RAM, {"nazwa": "X1"}, anuluj=anuluj)

    def test_dziwna_odpowiedz_modelu_nie_wywraca_programu(self):
        for odpowiedz in ([], {"pola": "x"}, {"pola": {"technologia": "FPM"}}, {"producent": None}):
            with self.subTest(odpowiedz=odpowiedz):
                self.assertEqual([], propozycje.opracuj(odpowiedz, RAM, []))
        w = propozycje.opracuj({"nazwa": _pole("KMM5321200AW", 9, "x")}, RAM, [])
        self.assertEqual((NAZWA, None, False), (w[0].kod, w[0].zrodlo, w[0].potwierdzona))


if __name__ == "__main__":
    unittest.main()
