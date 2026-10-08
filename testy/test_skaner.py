# SPDX-License-Identifier: GPL-3.0-or-later
"""Testy skanera: rozpoznawanie kodów, karta telefonu (bez danych prywatnych),
certyfikaty (łańcuch sprawdzany jak przez telefon), serwer HTTPS z parowaniem,
pełna droga skanu telefon → most → okno, biblioteka jsQR na prawdziwej etykiecie."""
import datetime as dt
import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from i18n.tlumacz import t, ustaw_jezyk
from testy.test_gui import EKRAN, TestPrzebudowy
from testy.test_uslugi import Kolekcja
from uslugi import certyfikaty, inwentarz, skaner
from uslugi.serwer_mobilny import Most, SerwerMobilny, adresy_lokalne

KORZEN = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


class TestRozpoznawania(Kolekcja):
    def test_kody_bez_wzgledu_na_wielkosc_liter_i_spacje(self):
        self.assertEqual(("egzemplarz", self.pc), (skaner.rozpoznaj(self.db, " nor-000001\n").typ,
                                                    skaner.rozpoznaj(self.db, " nor-000001\n").ident))
        self.assertEqual(("lokalizacja", self.polka), (skaner.rozpoznaj(self.db, "LOC-0002").typ,
                                                        skaner.rozpoznaj(self.db, "LOC-0002").ident))
        self.assertEqual("nieznany", skaner.rozpoznaj(self.db, "XYZ-1").typ)
        self.assertEqual("nieznany", skaner.rozpoznaj(self.db, "   ").typ)

    def test_karta_bez_danych_prywatnych(self):
        e = self.nowy(nazwa_wlasna="Atari 65XE", lokalizacja_id=self.polka, cena_minor=25000, waluta_kod="PLN",
                      zrodlo_nabycia="OLX tajne", data_nabycia="2020-05-23", uwagi="Działa")
        tekst = skaner.json_karty(self.db, self.db.execute(
            "SELECT kod_inwentarzowy FROM egzemplarz WHERE id = ?", (e,)).fetchone()[0], "pl")
        for prywatne in ("250", "OLX tajne", "2020-05-23", "PLN"):
            self.assertNotIn(prywatne, tekst)
        karta = json.loads(tekst)
        self.assertEqual("Atari 65XE", karta["nazwa"])
        self.assertIn({"etykieta": "Miejsce", "wartosc": "Regał A › Półka 2"}, karta["pola"])

    def test_karta_lokalizacji_i_zamontowanych(self):
        karta = skaner.karta_mobilna(self.db, skaner.rozpoznaj(self.db, "LOC-0002"), "pl")
        self.assertEqual("W tym miejscu (1)", karta["lista_tytul"])
        self.assertEqual(["DOS 486"], [p["nazwa"] for p in karta["lista"]])
        pc = skaner.karta_mobilna(self.db, skaner.rozpoznaj(self.db, "NOR-000001"), "pl")
        self.assertEqual(["Płyta VLB"], [p["nazwa"] for p in pc["lista"]])


class TestCertyfikatow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_wymagania_apple_i_lancuch(self):
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID
        pliki = certyfikaty.przygotuj(self.tmp, ["192.168.1.10"])
        ca = x509.load_pem_x509_certificate(pliki["ca"].read_bytes())
        serwer = x509.load_pem_x509_certificate(pliki["cert"].read_bytes())
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertGreaterEqual(serwer.public_key().key_size, 2048)
        self.assertLessEqual((certyfikaty.koniec_waznosci(serwer) - certyfikaty.poczatek_waznosci(serwer)).days, 825)
        self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH,
                      serwer.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
        san = serwer.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual({"192.168.1.10", "127.0.0.1"}, {str(a) for a in san.get_values_for_type(x509.IPAddress)})
        if hasattr(serwer, "verify_directly_issued_by"):  # cryptography ≥ 40
            serwer.verify_directly_issued_by(ca)          # podpisany przez nasz urząd
        if not sys.platform.startswith("win"):
            self.assertEqual(0o600, os.stat(pliki["klucz"]).st_mode & 0o777)

    def test_zmiana_adresu_nowy_certyfikat_ten_sam_urzad(self):
        pierwsze = certyfikaty.przygotuj(self.tmp, ["192.168.1.10"])
        ca_przed = pierwsze["ca"].read_bytes()
        serwer_przed = pierwsze["cert"].read_bytes()
        self.assertEqual(serwer_przed, certyfikaty.przygotuj(self.tmp, ["192.168.1.10"])["cert"].read_bytes())
        drugie = certyfikaty.przygotuj(self.tmp, ["10.0.0.5"])
        self.assertNotEqual(serwer_przed, drugie["cert"].read_bytes())
        self.assertEqual(ca_przed, drugie["ca"].read_bytes())   # telefon nie musi instalować ponownie


class TestSerwera(Kolekcja):
    """Telefon symulowany w osobnym wątku; most obsługiwany w wątku głównym — jak w programie."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.most = Most()
        self.serwer = SerwerMobilny(self.most, "klucz-testowy-123")
        self.pliki = certyfikaty.przygotuj(self.tmp, ["127.0.0.1"])
        self.port = self.serwer.uruchom(0, self.pliki, "127.0.0.1")
        self.addCleanup(self.serwer.zatrzymaj)
        # klient ufa WYŁĄCZNIE naszemu urzędowi — jak telefon po instalacji certyfikatu
        self.ssl = ssl.create_default_context(cafile=str(self.pliki["ca"]))

    def zadanie(self, metoda, sciezka, cialo=None, ciasteczko=None):
        """Zapytanie z osobnego wątku, przy obsłudze mostu w wątku głównym."""
        wynik = {}

        def klient():
            try:
                polaczenie = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.ssl, timeout=10)
                naglowki = {"Content-Type": "application/json"}
                if ciasteczko:
                    naglowki["Cookie"] = ciasteczko
                polaczenie.request(metoda, sciezka, body=cialo, headers=naglowki)
                odp = polaczenie.getresponse()
                wynik.update(status=odp.status, naglowki=dict(odp.getheaders()), tresc=odp.read())
                polaczenie.close()
            except Exception as blad:   # noqa: BLE001 — przekazany do wątku testu
                wynik["wyjatek"] = blad

        watek = threading.Thread(target=klient)
        watek.start()
        while watek.is_alive():
            self.most.obsluz_oczekujace(lambda rodzaj, kod: skaner.karta_mobilna(
                self.db, skaner.rozpoznaj(self.db, kod), "pl"))
            watek.join(0.02)
        if "wyjatek" in wynik:
            raise wynik["wyjatek"]
        return wynik

    def test_parowanie_ciasteczko_i_pamiec_telefonu(self):
        odp = self.zadanie("GET", "/?klucz=klucz-testowy-123")
        self.assertEqual(200, odp["status"])                     # strona od razu, bez przekierowania
        ciasteczko = odp["naglowki"]["Set-Cookie"]
        for atrybut in ("HttpOnly", "SameSite=Strict", "Secure"):
            self.assertIn(atrybut, ciasteczko)
        html = odp["tresc"].decode()
        self.assertNotIn("klucz-testowy-123", html)              # klucz nie jest wpisany w stronę
        self.assertIn("localStorage.setItem", html)              # strona zapamiętuje klucz w telefonie
        self.assertIn("history.replaceState", html)              # i usuwa go z paska adresu
        self.assertIn("playsinline", html)                       # wymóg Safari na iPhonie
        self.assertEqual(200, self.zadanie("GET", "/", ciasteczko=ciasteczko.split(";")[0])["status"])

    def test_skan_z_kluczem_w_naglowku_bez_ciasteczka(self):
        """Regresja (iPhone, Chrome): ciasteczko zgubione — klucz z pamięci strony wystarcza."""
        wynik = {}

        def klient():
            polaczenie = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.ssl, timeout=10)
            polaczenie.request("POST", "/api/skan", body=json.dumps({"kod": "NOR-000001"}),
                               headers={"Content-Type": "application/json", "X-Nornica-Klucz": "klucz-testowy-123"})
            odp = polaczenie.getresponse()
            wynik.update(status=odp.status, tresc=odp.read())

        watek = threading.Thread(target=klient)
        watek.start()
        while watek.is_alive():
            self.most.obsluz_oczekujace(lambda r, kod: skaner.karta_mobilna(self.db, skaner.rozpoznaj(self.db, kod)))
            watek.join(0.02)
        self.assertEqual(200, wynik["status"])
        self.assertEqual("DOS 486", json.loads(wynik["tresc"])["nazwa"])

    def test_strona_bez_parowania_wraca_z_kluczem_z_pamieci(self):
        odp = self.zadanie("GET", "/")
        self.assertEqual(403, odp["status"])
        html = odp["tresc"].decode()
        self.assertIn("localStorage.getItem('nornica_klucz')", html)
        self.assertIn("location.replace('/?klucz='", html)

    def test_nieaktualny_klucz_zapominany_w_telefonie(self):
        odp = self.zadanie("GET", "/?klucz=stary")
        self.assertEqual(403, odp["status"])
        self.assertIn("localStorage.removeItem('nornica_klucz')", odp["tresc"].decode())

    def test_bez_klucza_brak_dostepu(self):
        self.assertEqual(403, self.zadanie("GET", "/")["status"])
        self.assertEqual(403, self.zadanie("GET", "/?klucz=zly")["status"])
        self.assertEqual(403, self.zadanie("POST", "/api/skan", json.dumps({"kod": "NOR-000001"}))["status"])
        self.assertEqual(403, self.zadanie("POST", "/api/skan", json.dumps({"kod": "NOR-000001"}),
                                           "nornica=zly")["status"])

    def test_skan_przez_most(self):
        odp = self.zadanie("POST", "/api/skan", json.dumps({"kod": "nor-000001"}), "nornica=klucz-testowy-123")
        self.assertEqual(200, odp["status"])
        karta = json.loads(odp["tresc"])
        self.assertEqual(("egzemplarz", "DOS 486"), (karta["typ"], karta["nazwa"]))

    def test_zbyt_duze_zapytanie(self):
        odp = self.zadanie("POST", "/api/skan", "x" * 10000, "nornica=klucz-testowy-123")
        self.assertEqual(413, odp["status"])

    def test_pliki_statyczne_bez_klucza(self):
        js = self.zadanie("GET", "/jsQR.js")
        self.assertEqual(200, js["status"])
        self.assertIn(b"jsQR", js["tresc"][:20000])
        ca = self.zadanie("GET", "/ca.crt")
        self.assertEqual("application/x-x509-ca-cert", ca["naglowki"]["Content-Type"])
        self.assertTrue(ca["tresc"].startswith(b"-----BEGIN CERTIFICATE-----"))

    def test_nowy_klucz_odlacza_telefony(self):
        self.serwer.ustaw_klucz("nowy-klucz")
        self.assertEqual(403, self.zadanie("POST", "/api/skan", json.dumps({"kod": "NOR-000001"}),
                                           "nornica=klucz-testowy-123")["status"])

    def test_klient_bez_zaufania_odrzucony(self):
        """Telefon bez zainstalowanego urzędu dostaje ostrzeżenie (tu: błąd weryfikacji),
        a serwer działa dalej dla pozostałych."""
        obcy = ssl.create_default_context()
        polaczenie = http.client.HTTPSConnection("127.0.0.1", self.port, context=obcy, timeout=5)
        with self.assertRaises(ssl.SSLError):
            polaczenie.request("GET", "/")
        self.assertEqual(403, self.zadanie("GET", "/")["status"])

    def test_wskazowka_zapory_tylko_dla_zainstalowanej(self):
        from uslugi.serwer_mobilny import wskazowka_zapory
        with mock.patch("sys.platform", "linux"):
            with mock.patch("shutil.which", return_value=None):
                self.assertEqual("telefon.zapora_brak", wskazowka_zapory(8765)[0])   # jak na Arch
            with mock.patch("shutil.which", side_effect=lambda n: "/usr/bin/ufw" if n == "ufw" else None):
                self.assertEqual("telefon.zapora_ufw", wskazowka_zapory(8765)[0])
            with mock.patch("shutil.which", side_effect=lambda n: "/usr/bin/firewall-cmd" if n == "firewall-cmd" else None):
                self.assertEqual("telefon.zapora_firewalld", wskazowka_zapory(8765)[0])
        with mock.patch("sys.platform", "win32"):
            self.assertEqual(("telefon.zapora_windows", {"port": 8765}), wskazowka_zapory(8765))

    def test_adresy_lokalne(self):
        adresy = adresy_lokalne()
        self.assertTrue(adresy)
        self.assertNotIn("127.0.0.1", adresy[:-1])


class TestStronyTelefonu(unittest.TestCase):
    @unittest.skipUnless(NODE, "brak Node.js")
    def test_skrypt_strony_bez_bledow_skladni(self):
        html = (KORZEN / "zasoby" / "www" / "skaner.html").read_text(encoding="utf-8")
        skrypt = re.findall(r"<script>(.*?)</script>", html, re.S)[0].replace("{{NAPISY}}", "{}")
        plik = Path(tempfile.mkdtemp()) / "strona.js"
        plik.write_text(skrypt, encoding="utf-8")
        wynik = subprocess.run([NODE, "--check", str(plik)], capture_output=True, text=True)
        self.assertEqual(0, wynik.returncode, wynik.stderr)

    @unittest.skipUnless(NODE, "brak Node.js")
    def test_jsqr_czyta_etykiete_programu(self):
        """Dołączona biblioteka jsQR odczytuje kod z etykiety wygenerowanej przez program —
        także po zmniejszeniu obrazu, jak robi to strona przy zdjęciu z iPhone'a."""
        from PIL import Image
        from uslugi import etykiety
        tmp = Path(tempfile.mkdtemp())
        pliki = etykiety.generuj(tmp / "e.png", [etykiety.Etykieta("NOR-000123", "Atari 65XE")],
                                 etykiety.FORMATY["brother_dk11209"], tryb="png")
        for szerokosc in (732, 400):
            obraz = Image.open(pliki[0]).convert("RGBA")
            obraz = obraz.resize((szerokosc, round(obraz.height * szerokosc / obraz.width)))
            (tmp / "obraz.raw").write_bytes(obraz.tobytes())
            skrypt = (f"const jsQR=require({json.dumps(str(KORZEN / 'zasoby' / 'www' / 'jsQR.js'))});"
                      f"const d=require('fs').readFileSync({json.dumps(str(tmp / 'obraz.raw'))});"
                      f"const w=jsQR(new Uint8ClampedArray(d),{obraz.width},{obraz.height},"
                      f"{{inversionAttempts:'attemptBoth'}});process.stdout.write(w?w.data:'BRAK');")
            wynik = subprocess.run([NODE, "-e", skrypt], capture_output=True, text=True, timeout=60)
            with self.subTest(szerokosc=szerokosc):
                self.assertEqual("NOR-000123", wynik.stdout, wynik.stderr)


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestSkaneraWOknie(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp)})
        straznik.start()
        self.addCleanup(straznik.stop)

    def stopka(self):
        return self.okno._widzety["skan_info"].cget("text")

    def test_pole_skanuj(self):
        self.okno.filtr_var.set("zzz")                       # filtr ukrywałby wynik
        self.okno._zastosuj_filtr()
        self.okno.skan_var.set("nor-000002\n")
        self.okno._skan_z_pola()
        self.assertEqual((f"E{self.karta}",), self.okno._widzety["drzewo"].selection())
        self.assertEqual("", self.okno.filtr_var.get())
        self.assertEqual("", self.okno.skan_var.get())
        self.assertIn("NOR-000002", self.stopka())

    def test_lokalizacja_rozwinieta(self):
        self.okno.obsluz_skan("LOC-0001", "klawiatura")
        drzewo = self.okno._widzety["drzewo"]
        self.assertEqual(("L1",), drzewo.selection())
        self.assertTrue(drzewo.item("L1", "open"))

    def test_nieznany_kod_bez_okna_modalnego(self):
        with mock.patch.object(self.okno, "bell") as dzwonek:
            self.okno.obsluz_skan("ABC-999", "klawiatura")
        dzwonek.assert_called_once()
        self.assertEqual(t("skaner.nieznany", kod="ABC-999"), self.stopka())

    def test_telefon_od_poczatku_do_konca(self):
        """Okno telefonu uruchamia serwer HTTPS; „telefon” skanuje; okno programu
        zaznacza egzemplarz; stopka w bieżącym języku także po przełączeniu."""
        okno = self.okno.telefon()
        with mock.patch("uslugi.serwer_mobilny.PORT_DOMYSLNY", 0):
            okno.uruchom(port=0)
        serwer = self.okno.serwer
        self.assertTrue(serwer.dziala and serwer.https)
        self.assertIn("klucz=", serwer.adres_parowania("127.0.0.1"))
        kontekst = ssl.create_default_context(cafile=str(self.tmp / "certyfikat" / "ca.crt"))
        klucz = serwer.klucz
        wynik = {}

        def telefon():
            polaczenie = http.client.HTTPSConnection("127.0.0.1", serwer.port, context=kontekst, timeout=10)
            polaczenie.request("POST", "/api/skan", body=json.dumps({"kod": "NOR-000002"}),
                               headers={"Cookie": f"nornica={klucz}", "Content-Type": "application/json"})
            wynik["karta"] = json.loads(polaczenie.getresponse().read())

        watek = threading.Thread(target=telefon)
        watek.start()
        while watek.is_alive():
            self.okno.update()                               # pompa mostu działa w pętli okna
            watek.join(0.02)
        self.okno.update()
        self.assertEqual("SB16", wynik["karta"]["nazwa"])
        self.assertEqual((f"E{self.karta}",), self.okno._widzety["drzewo"].selection())
        self.assertIn(t("skaner.ostatni_telefon", kod="NOR-000002"), self.stopka())
        self.okno.przelacz_jezyk("pl")
        self.okno.update()
        self.assertIn("Zeskanowano telefonem: NOR-000002", self.stopka())
        self.assertIn("Skaner w telefonie: włączony", self.stopka())
        # okno telefonu przeżywa przebudowę z kodem QR na płótnie
        plotna = [w for w in okno.winfo_children()[0].winfo_children()[0].winfo_children()
                  if w.winfo_class() == "Canvas"]
        self.assertTrue(plotna and plotna[0].find_withtag("modul"))
        okno.zamknij()
        self.assertTrue(serwer.dziala)                       # zamknięcie okna nie zatrzymuje serwera
        self.okno.destroy()
        self.assertFalse(serwer.dziala)                      # zamknięcie programu — zatrzymuje
        from gui.okno_glowne import OknoGlowne
        self.okno = OknoGlowne(self.db, pokaz_powitanie=False)   # dla tearDown

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


if __name__ == "__main__":
    unittest.main()


class TestTypuObrazu(unittest.TestCase):
    def test_rozpoznanie_po_zawartosci(self):
        from uslugi.pliki import typ_obrazu
        self.assertEqual(".jpg", typ_obrazu(b"\xff\xd8\xff\xe0\x00\x10JFIF"))
        self.assertEqual(".png", typ_obrazu(b"\x89PNG\r\n\x1a\n\x00\x00"))
        self.assertEqual(".heic", typ_obrazu(b"\x00\x00\x00\x18ftypheic\x00\x00"))
        self.assertEqual(".webp", typ_obrazu(b"RIFF\x00\x00\x00\x00WEBPVP8 "))
        self.assertEqual(".gif", typ_obrazu(b"GIF89a"))
        self.assertIsNone(typ_obrazu(b"%PDF-1.4"))                 # PDF udający zdjęcie
        self.assertIsNone(typ_obrazu(b"MZ\x90\x00"))                 # plik wykonywalny


@unittest.skipUnless(EKRAN, "brak ekranu (uruchom przez xvfb-run)")
class TestZdjecZTelefonu(TestPrzebudowy):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        straznik = mock.patch.dict(os.environ, {"NORNICA_DANE": str(self.tmp)})
        straznik.start()
        self.addCleanup(straznik.stop)
        okno = self.okno.telefon()
        okno.uruchom(port=0)
        self.serwer = self.okno.serwer
        self.ssl = ssl.create_default_context(cafile=str(self.tmp / "certyfikat" / "ca.crt"))

    def jpeg(self, szer=2000, wys=1500, kolor=(180, 40, 40)):
        from PIL import Image
        import io
        bufor = io.BytesIO()
        Image.new("RGB", (szer, wys), kolor).save(bufor, format="JPEG", quality=90)
        return bufor.getvalue()

    def wyslij(self, tresc: bytes, kod="NOR-000001", glowne="1", nazwa="image.jpg", naglowki=None):
        wynik = {}

        def telefon():
            polaczenie = http.client.HTTPSConnection("127.0.0.1", self.serwer.port, context=self.ssl, timeout=20)
            n = {"X-Nornica-Klucz": self.serwer.klucz, "X-Nornica-Kod": kod, "X-Nornica-Nazwa": nazwa,
                 "X-Nornica-Glowne": glowne, "Content-Type": "image/jpeg", **(naglowki or {})}
            polaczenie.request("POST", "/api/zdjecie", body=tresc, headers=n)
            odp = polaczenie.getresponse()
            wynik.update(status=odp.status, karta=json.loads(odp.read() or b"{}"))

        watek = threading.Thread(target=telefon)
        watek.start()
        while watek.is_alive():
            self.okno.update()
            watek.join(0.02)
        self.okno.update()
        return wynik

    def test_zdjecie_trafia_do_egzemplarza_i_zostaje_glownym(self):
        from uslugi import pliki
        przed = set(Path(tempfile.gettempdir()).glob("nornica-*"))
        odp = self.wyslij(self.jpeg())
        self.assertEqual(200, odp["status"])
        self.assertEqual(t("mobilny.zdjecie_dodane"), odp["karta"]["komunikat"])
        self.assertEqual(1, odp["karta"]["zdjec"])
        self.assertIsNotNone(odp["karta"]["zdjecie"])                 # miniatura głównego na karcie
        glowne = pliki.zdjecie_glowne(self.db, self.pc)
        self.assertIsNotNone(glowne)
        # „image.jpg” z iPhone'a: tytuł z datą, w języku programu
        self.assertTrue(glowne["tytul"].startswith(t("mobilny.tytul_zdjecia", data="")))
        self.assertTrue(pliki.sciezka_pliku(self.db, glowne["plik_sciezka"]).exists())
        self.assertEqual(przed, set(Path(tempfile.gettempdir()).glob("nornica-*")))   # bez śmieci w /tmp
        self.assertEqual((f"E{self.pc}",), self.okno._widzety["drzewo"].selection())
        self.assertIn("NOR-000001", self.okno._widzety["skan_info"].cget("text"))

    def test_bez_zaznaczenia_nie_zmienia_glownego(self):
        from uslugi import pliki
        self.wyslij(self.jpeg(kolor=(1, 2, 3)))
        pierwsze = pliki.zdjecie_glowne(self.db, self.pc)["id"]
        odp = self.wyslij(self.jpeg(kolor=(200, 200, 10)), glowne="0", nazwa="IMG_2041.JPG")
        self.assertEqual(2, odp["karta"]["zdjec"])
        self.assertEqual(pierwsze, pliki.zdjecie_glowne(self.db, self.pc)["id"])
        tytuly = {z["tytul"] for z in pliki.zdjecia_egzemplarza(self.db, self.pc)}
        self.assertIn("IMG_2041", tytuly)                              # nazwa z Androida zostaje

    def test_miniatura_liczona_w_watku_serwera(self):
        from uslugi import pliki
        watki = []
        oryginal = pliki.przygotuj

        def sledz(*argumenty, **opcje):
            watki.append(threading.current_thread() is threading.main_thread())
            return oryginal(*argumenty, **opcje)

        with mock.patch.object(pliki, "przygotuj", side_effect=sledz):
            self.assertEqual(200, self.wyslij(self.jpeg())["status"])
        self.assertEqual([False], watki)                               # nie w wątku interfejsu

    def test_odmowy(self):
        self.assertEqual(415, self.wyslij(b"%PDF-1.4 to nie jest zdjecie")["status"])
        self.assertEqual(413, self.wyslij(b"", naglowki={"Content-Length": str(40 * 2**20)})["status"])
        lokalizacja = self.wyslij(self.jpeg(), kod="LOC-0001")
        self.assertEqual(t("mobilny.zdjecie_tylko_egzemplarz"), lokalizacja["karta"]["blad"])
        bez_klucza = self.wyslij(self.jpeg(), naglowki={"X-Nornica-Klucz": "zly"})
        self.assertEqual(403, bez_klucza["status"])

    test_stan_przezywa_przelaczenie_tam_i_z_powrotem = None
    test_po_przebudowie_nic_nie_siega_po_zniszczone_widzety = None
    test_otwarte_okno_przezywa_przebudowe_z_danymi = None
    test_dodanie_egzemplarza_przez_okno = None
    test_blad_walidacji_nie_zamyka_okna = None


class TestUruchamianiaKamery(unittest.TestCase):
    """Logika włączania kamery ze strony telefonu, uruchamiana w Node.js
    z udawaną przeglądarką. Zgłoszenie z Androida: „Aparat jest niedostępny”."""

    def scenariusz(self, bledy: list) -> dict:
        """bledy: kolejne odpowiedzi getUserMedia — nazwa błędu albo None (sukces)."""
        html = (KORZEN / "zasoby" / "www" / "skaner.html").read_text(encoding="utf-8")
        kod = html.split("// === uruchomKamere: początek")[1].split("// === uruchomKamere: koniec ===")[0]
        kod = kod.split("\n", 1)[1]
        skrypt = kod + f"""
const odpowiedzi = {json.dumps(bledy)};
const wywolania = [], przerwy = [];
const pobierz = async (u) => {{
  wywolania.push(JSON.stringify(u.video));
  const b = odpowiedzi.shift();
  if (b === undefined || b === null) return "STRUMIEN";
  const e = new Error("opis"); e.name = b; throw e;
}};
uruchomKamere(pobierz, async (ms) => {{ przerwy.push(ms); }}).then((w) => {{
  process.stdout.write(JSON.stringify({{ strumien: w.strumien, blad: w.blad && w.blad.name,
    klucz: w.blad ? kluczBleduKamery(w.blad) : null, wywolania, przerwy,
    dziennik: w.dziennik, tylnaZajeta: tylnaZajeta(w.dziennik) }}));
}});
"""
        wynik = subprocess.run([NODE, "-e", skrypt], capture_output=True, text=True, timeout=30)
        self.assertEqual("", wynik.stderr)
        return json.loads(wynik.stdout)

    def setUp(self):
        if not NODE:
            self.skipTest("brak Node.js")

    def test_od_razu(self):
        w = self.scenariusz([None])
        self.assertEqual(("STRUMIEN", 1), (w["strumien"], len(w["wywolania"])))

    def test_najpierw_scisle_tylna(self):
        """Zgłoszenie (Samsung Internet): przy samym „preferowanym” przeglądarka
        oddawała przednią kamerę — pierwsze żądanie jest ścisłe."""
        w = self.scenariusz([None])
        self.assertEqual('{"facingMode":{"exact":"environment"},"width":{"ideal":1280}}', w["wywolania"][0])

    def test_telefon_odrzuca_ustawienia_prostsze_dzialaja(self):
        w = self.scenariusz(["OverconstrainedError", None])
        self.assertEqual("STRUMIEN", w["strumien"])
        self.assertEqual('{"facingMode":{"ideal":"environment"},"width":{"ideal":1280}}', w["wywolania"][1])

    def test_kamera_chwilowo_zajeta_ponowienie_po_chwili(self):
        """Aparat systemowy nie zwolnił jeszcze kamery — druga próba po 800 ms się udaje."""
        w = self.scenariusz(["NotReadableError", None])
        self.assertEqual("STRUMIEN", w["strumien"])
        self.assertEqual([800], w["przerwy"])
        self.assertEqual(w["wywolania"][0], w["wywolania"][1])   # te same ustawienia

    def test_jakakolwiek_kamera_na_koniec(self):
        w = self.scenariusz(["NotFoundError"] * 3 + [None])
        self.assertEqual("STRUMIEN", w["strumien"])
        self.assertEqual("true", w["wywolania"][3])

    def test_kamera_zajeta_na_stale(self):
        w = self.scenariusz(["NotReadableError"] * 8)
        self.assertEqual((None, "mobilny.kamera_zajeta"), (w["strumien"], w["klucz"]))
        self.assertEqual(8, len(w["wywolania"]))                 # 4 ustawienia × 2 próby

    def test_odmowa_bez_ponawiania(self):
        w = self.scenariusz(["NotAllowedError"])
        self.assertEqual(("mobilny.kamera_odmowa", 1), (w["klucz"], len(w["wywolania"])))

    def test_brak_kamery(self):
        w = self.scenariusz(["NotFoundError"] * 4)
        self.assertEqual("mobilny.kamera_brak", w["klucz"])

    def wyrazenie(self, js: str):
        html = (KORZEN / "zasoby" / "www" / "skaner.html").read_text(encoding="utf-8")
        kod = html.split("// === uruchomKamere: początek")[1].split("// === uruchomKamere: koniec ===")[0]
        kod = kod.split("\n", 1)[1]
        wynik = subprocess.run([NODE, "-e", kod + f"\nprocess.stdout.write(JSON.stringify({js}));"],
                               capture_output=True, text=True, timeout=30)
        self.assertEqual("", wynik.stderr)
        return json.loads(wynik.stdout)

    SAMSUNG = [  # tak nazywa kamery Samsung Internet / Chrome na Galaxy z kilkoma obiektywami
        {"kind": "audioinput", "deviceId": "m", "label": "Mikrofon"},
        {"kind": "videoinput", "deviceId": "p", "label": "camera2 1, facing front"},
        {"kind": "videoinput", "deviceId": "t0", "label": "camera2 0, facing back"},
        {"kind": "videoinput", "deviceId": "t2", "label": "camera2 2, facing back"},
    ]

    def test_rozpoznanie_przedniej(self):
        self.assertTrue(self.wyrazenie('czyPrzednia("user", "")'))
        self.assertFalse(self.wyrazenie('czyPrzednia("environment", "")'))
        self.assertTrue(self.wyrazenie('czyPrzednia(null, "camera2 1, facing front")'))
        self.assertFalse(self.wyrazenie('czyPrzednia(null, "camera2 0, facing back")'))
        self.assertTrue(self.wyrazenie('czyPrzednia(null, "Przedni aparat")'))       # iPhone po polsku
        self.assertFalse(self.wyrazenie('czyPrzednia(null, "")'))                    # brak danych: nie przełączamy

    def test_wybor_tylnej_glownej(self):
        wynik = self.wyrazenie(f"wybierzTylnaKamere({json.dumps(self.SAMSUNG)})")
        self.assertEqual("t0", wynik["deviceId"])                   # pierwsza tylna = obiektyw główny
        iphone = [{"kind": "videoinput", "deviceId": "a", "label": "Przedni aparat"},
                  {"kind": "videoinput", "deviceId": "b", "label": "Tylny aparat"}]
        self.assertEqual("b", self.wyrazenie(f"wybierzTylnaKamere({json.dumps(iphone)})")["deviceId"])
        bez_nazw = [{"kind": "videoinput", "deviceId": "x", "label": ""}]
        self.assertIsNone(self.wyrazenie(f"wybierzTylnaKamere({json.dumps(bez_nazw)})"))

    def test_glowna_tylna_wg_numeru_nie_kolejnosci(self):
        """Lista z diagnostyki Samsunga (Android 10, Samsung Internet 30): kolejność 1, 3, 2, 0.
        Główna tylna to „camera 0”, choć na liście jest ostatnia."""
        z_telefonu = [{"kind": "videoinput", "deviceId": "10e77871", "label": "camera 1, facing front"},
                      {"kind": "videoinput", "deviceId": "a581f146", "label": "camera 3, facing front"},
                      {"kind": "videoinput", "deviceId": "4eeeaac0", "label": "camera 2, facing back"},
                      {"kind": "videoinput", "deviceId": "baa5dd3c", "label": "camera 0, facing back"}]
        self.assertEqual("baa5dd3c", self.wyrazenie(f"wybierzTylnaKamere({json.dumps(z_telefonu)})")["deviceId"])
        iphone = [{"kind": "videoinput", "deviceId": "u", "label": "Tylny aparat ultraszerokokątny"},
                  {"kind": "videoinput", "deviceId": "g", "label": "Tylny aparat"},
                  {"kind": "videoinput", "deviceId": "p", "label": "Przedni aparat"}]
        self.assertEqual("g", self.wyrazenie(f"wybierzTylnaKamere({json.dumps(iphone)})")["deviceId"])

    def test_zapamietywane_tylko_tylne(self):
        self.assertFalse(self.wyrazenie('czyZapamietac({label: "camera 1, facing front"})'))
        self.assertTrue(self.wyrazenie('czyZapamietac({label: "camera 0, facing back"})'))
        self.assertTrue(self.wyrazenie('czyZapamietac({label: "Tylny aparat"})'))

    def test_przelaczanie_po_kolei(self):
        lista = json.dumps(self.SAMSUNG)
        self.assertEqual("t0", self.wyrazenie(f'nastepnaKamera({lista}, "p")')["deviceId"])
        self.assertEqual("t2", self.wyrazenie(f'nastepnaKamera({lista}, "t0")')["deviceId"])
        self.assertEqual("p", self.wyrazenie(f'nastepnaKamera({lista}, "t2")')["deviceId"])   # w kółko
        jedna = json.dumps(self.SAMSUNG[:2])
        self.assertIsNone(self.wyrazenie(f'nastepnaKamera({jedna}, "p")'))      # jedna kamera: brak przycisku

    def test_samsung_tylna_zajeta_dziala_przednia(self):
        """Odtworzenie zgłoszenia: każda próba tylnej kończy się „zajętością”,
        „dowolna kamera” daje przednią. Strona ma to powiedzieć wprost
        i zapisać każdą próbę w diagnostyce."""
        w = self.scenariusz(["NotReadableError"] * 6 + [None])
        self.assertEqual("STRUMIEN", w["strumien"])
        self.assertTrue(w["tylnaZajeta"])
        self.assertEqual(7, len(w["dziennik"]))
        self.assertEqual({"ustawienia": "facingMode exact environment 1280",
                          "wynik": "NotReadableError: opis"}, w["dziennik"][0])
        self.assertEqual({"ustawienia": "dowolna kamera", "wynik": "OK"}, w["dziennik"][-1])

    def test_tylna_odrzucona_ustawieniami_to_nie_zajetosc(self):
        w = self.scenariusz(["OverconstrainedError", None])
        self.assertFalse(w["tylnaZajeta"])

    def test_nieznany_blad(self):
        w = self.scenariusz(["TypeError"] * 4)
        self.assertEqual("mobilny.kamera_niedostepna", w["klucz"])


class TestNapisowStronyTelefonu(unittest.TestCase):
    def test_kazdy_napis_strony_wysylany_przez_serwer(self):
        """Napis użyty na stronie, a pominięty w KLUCZE_STRONY, pokazałby się
        na telefonie jako „undefined”."""
        from uslugi.serwer_mobilny import KLUCZE_STRONY
        from i18n.tlumacz import ma_klucz
        html = (KORZEN / "zasoby" / "www" / "skaner.html").read_text(encoding="utf-8")
        uzyte = set(re.findall(r'"((?:mobilny|aplikacja|inw\.tel)\.[a-z_]+)"', html))
        self.assertTrue(uzyte)
        self.assertEqual(set(), uzyte - set(KLUCZE_STRONY))
        self.assertEqual([], [k for k in KLUCZE_STRONY if not ma_klucz(k)])
