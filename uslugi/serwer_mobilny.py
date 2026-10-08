# SPDX-License-Identifier: GPL-3.0-or-later
"""Serwer skanera w sieci domowej: telefon jako czytnik kodów, bez instalacji.

Przebieg: program pokazuje kod QR z adresem i kluczem parowania → telefon
otwiera stronę w przeglądarce → strona czyta kody aparatem (na żywo albo
ze zdjęcia) i wysyła je tutaj → program pokazuje egzemplarz, a telefon
dostaje krótką kartę (bez danych prywatnych).

Zasady:
  * Do bazy sięga WYŁĄCZNIE wątek interfejsu. Serwer działa w tle i każde
    zapytanie przekazuje przez Most (kolejkę), czekając na odpowiedź.
  * Klucz parowania (losowy, 192 bity) jest wymagany przy każdym zapytaniu.
    Dwie drogi jego dostarczenia, żeby telefon raz sparowany pozostał
    sparowany: ciasteczko ORAZ nagłówek X-Nornica-Klucz, który strona wysyła
    z pamięci przeglądarki (localStorage). Zgłoszenie z iPhone'a (Chrome):
    komunikat „telefon nie jest sparowany” mimo wcześniejszego parowania —
    samo ciasteczko bywa gubione (np. przy niezaufanym jeszcze certyfikacie
    albo przy stronie przywróconej bez klucza w adresie).
  * Klucz znika z paska adresu zaraz po wejściu (history.replaceState) —
    nie zostaje w historii przeglądarki.
  * Serwer jest domyślnie wyłączony; uruchamia go użytkownik.
  * Statyczne pliki (biblioteka jsQR, certyfikat urzędu) nie są tajne
    i są dostępne bez klucza — telefon musi pobrać certyfikat, zanim zaufa
    połączeniu.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import tempfile
import json
import queue
import secrets
import socket
import ssl
import threading
from html import escape
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from i18n.tlumacz import jezyk_biezacy, t
from wyjatki import BladNornicy

KATALOG_WWW = Path(__file__).resolve().parents[1] / "zasoby" / "www"
PORT_DOMYSLNY = 8765
PROB_PORTOW = 10
MAKS_ZAPYTANIE = 4096
MAKS_ZDJECIE = 30 * 1024 * 1024       # 30 MB — zdjęcie z telefonu w pełnej rozdzielczości
CIASTECZKO = "nornica"
NAGLOWEK_KLUCZA = "X-Nornica-Klucz"
MAGAZYN_KLUCZA = "nornica_klucz"       # nazwa wpisu w localStorage telefonu

# Klucze napisów strony telefonu — wstawiane w chwili wyświetlenia, w języku programu
KLUCZE_STRONY = (
    "aplikacja.nazwa", "mobilny.tytul", "mobilny.wlacz_aparat", "mobilny.wylacz_aparat",
    "mobilny.zrob_zdjecie", "mobilny.wpisz_kod", "mobilny.wyslij", "mobilny.celuj",
    "mobilny.brak_kodu_na_zdjeciu", "mobilny.brak_polaczenia", "mobilny.historia",
    "mobilny.kamera_niedostepna", "mobilny.kamera_wymaga_certyfikatu", "mobilny.instrukcja_tytul",
    "mobilny.instrukcja_iphone", "mobilny.instrukcja_android", "mobilny.pobierz_certyfikat",
    "mobilny.przetwarzanie", "mobilny.kamera_odmowa", "mobilny.brak_parowania",
    "mobilny.dodaj_zdjecie", "mobilny.ustaw_glowne", "mobilny.wysylanie", "mobilny.zdjecie_blad",
    "mobilny.zdjecie_za_duze", "mobilny.zdjecie_zly_typ", "mobilny.zdjecia", "mobilny.zdjecie_dodane",
    "mobilny.zdjecia_dodane", "mobilny.kamera_zajeta", "mobilny.kamera_brak", "mobilny.kamera_uruchamianie",
    "mobilny.przelacz_aparat", "mobilny.tyl_zajety", "mobilny.diagnostyka", "mobilny.diag_kamery",
    "mobilny.diag_proby", "mobilny.diag_biezaca",
)


def wskazowka_zapory(port: int) -> tuple[str, dict]:
    """Klucz tłumaczenia i pola podpowiedzi o zaporze — tylko dla zapory, która
    faktycznie jest zainstalowana. Zgłoszenie z Arch: podpowiedź z poleceniami
    ufw i firewall-cmd, z których żadne nie istniało (Arch domyślnie nie ma zapory)."""
    import shutil
    import sys
    if sys.platform.startswith("win"):
        return "telefon.zapora_windows", {"port": port}
    if sys.platform == "darwin":
        return "telefon.zapora_mac", {"port": port}
    if shutil.which("ufw"):
        return "telefon.zapora_ufw", {"port": port}
    if shutil.which("firewall-cmd"):
        return "telefon.zapora_firewalld", {"port": port}
    return "telefon.zapora_brak", {"port": port}


def generuj_klucz() -> str:
    return secrets.token_urlsafe(24)


def adresy_lokalne() -> list[str]:
    """Adresy IPv4 komputera w sieci; najbardziej prawdopodobny (trasa domyślna) pierwszy.
    Połączenie UDP z adresem testowym 192.0.2.1 nie wysyła żadnego pakietu —
    system tylko wybiera kartę sieciową, przez którą by poszedł."""
    adresy: list[str] = []
    try:
        gniazdo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            gniazdo.connect(("192.0.2.1", 9))
            adresy.append(gniazdo.getsockname()[0])
        finally:
            gniazdo.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            adresy.append(info[4][0])
    except OSError:
        pass
    wynik = []
    for adres in adresy:
        ip = ipaddress.ip_address(adres)
        if not ip.is_loopback and adres not in wynik:
            wynik.append(adres)
    # sieci prywatne (domowe) przed resztą
    return sorted(wynik, key=lambda a: (not ipaddress.ip_address(a).is_private, wynik.index(a))) or ["127.0.0.1"]


class Most:
    """Przekazuje zapytania z wątków serwera do wątku interfejsu i odpowiedzi z powrotem."""

    def __init__(self):
        self._kolejka: queue.Queue = queue.Queue()

    def zapytaj(self, rodzaj: str, dane, limit: float = 8.0):
        """Wołane w wątku serwera. Czeka na odpowiedź wątku interfejsu."""
        odpowiedz: queue.Queue = queue.Queue(maxsize=1)
        self._kolejka.put((rodzaj, dane, odpowiedz))
        return odpowiedz.get(timeout=limit)

    def obsluz_oczekujace(self, obsluga) -> int:
        """Wołane w wątku interfejsu (pętla after). Zwraca liczbę obsłużonych zapytań."""
        liczba = 0
        while True:
            try:
                rodzaj, dane, odpowiedz = self._kolejka.get_nowait()
            except queue.Empty:
                return liczba
            try:
                wynik = obsluga(rodzaj, dane)
            except BladNornicy as blad:
                wynik = {"blad": blad.komunikat()}       # komunikat w języku programu
            except Exception as blad:   # noqa: BLE001 — błąd wraca do telefonu, nie wywraca okna
                wynik = {"blad": str(blad)}
            odpowiedz.put(wynik)
            liczba += 1


class _Obsluga(BaseHTTPRequestHandler):
    server: "_Serwer"
    timeout = 15
    protocol_version = "HTTP/1.1"

    # --- pomocnicze ------------------------------------------------------------
    def setup(self):
        # Uzgadnianie TLS tutaj, w wątku tego połączenia — wolny albo wrogi klient
        # nie zablokuje przyjmowania kolejnych połączeń.
        if isinstance(self.request, ssl.SSLSocket):
            self.request.settimeout(self.timeout)
            self.request.do_handshake()
        super().setup()

    def handle(self):
        try:
            super().handle()
        except (ssl.SSLError, ConnectionError, TimeoutError, OSError):
            pass                          # zerwane połączenie telefonu nie jest błędem programu

    def log_message(self, *_):            # bez zaśmiecania terminala
        pass

    def _klucz_z_ciasteczka(self) -> str | None:
        naglowek = self.headers.get("Cookie")
        if not naglowek:
            return None
        try:
            ciasteczko = cookies.SimpleCookie(naglowek)
        except cookies.CookieError:
            return None
        return ciasteczko[CIASTECZKO].value if CIASTECZKO in ciasteczko else None

    def _poprawny(self, klucz: str | None) -> bool:
        return bool(klucz) and hmac.compare_digest(klucz.encode(), self.server.klucz.encode())

    def _uprawniony(self) -> bool:
        """Ciasteczko albo nagłówek — wystarczy jedno z nich."""
        return (self._poprawny(self._klucz_z_ciasteczka())
                or self._poprawny(self.headers.get(NAGLOWEK_KLUCZA)))

    def _wyslij(self, kod: int, tresc: bytes, typ: str, naglowki: dict | None = None) -> None:
        self.send_response(kod)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(tresc)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for nazwa, wartosc in (naglowki or {}).items():
            self.send_header(nazwa, wartosc)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(tresc)

    def _strona_bledu(self, kod: int, klucz_tekstu: str, skrypt: str = "") -> None:
        tresc = (f'<!DOCTYPE html><html lang="{jezyk_biezacy()}"><meta charset="utf-8">'
                 f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                 f'{skrypt}'
                 f'<body style="font-family:sans-serif;padding:24px;background:#F2F0EA;color:#2A2925">'
                 f'<h2>{escape(t("aplikacja.nazwa"))}</h2><p>{escape(t(klucz_tekstu))}</p></body></html>')
        self._wyslij(kod, tresc.encode("utf-8"), "text/html; charset=utf-8")

    # --- GET -----------------------------------------------------------------------
    def do_GET(self):
        adres = urlsplit(self.path)
        if adres.path == "/":
            klucz = parse_qs(adres.query).get("klucz", [None])[0]
            if klucz is not None:
                if not self._poprawny(klucz):
                    # nieaktualny klucz (np. po „Nowy klucz”): zapomniany także w telefonie
                    return self._strona_bledu(403, "mobilny.zly_klucz",
                                              f"<script>try{{localStorage.removeItem('{MAGAZYN_KLUCZA}')}}"
                                              f"catch(e){{}}</script>")
                # Strona od razu (bez przekierowania) + ciasteczko. Klucz zapisuje
                # skrypt strony w pamięci telefonu i usuwa go z paska adresu.
                bezpieczne = "; Secure" if self.server.https else ""
                return self._wyslij(200, self.server.strona().encode("utf-8"), "text/html; charset=utf-8", {
                    "Set-Cookie": f"{CIASTECZKO}={klucz}; Path=/; HttpOnly; SameSite=Strict; "
                                  f"Max-Age=31536000{bezpieczne}"})
            if not self._uprawniony():
                # Bez ciasteczka: jeśli telefon pamięta klucz, wraca z nim sam; jeśli nie — komunikat.
                return self._strona_bledu(403, "mobilny.brak_parowania",
                                          f"<script>try{{var k=localStorage.getItem('{MAGAZYN_KLUCZA}');"
                                          f"if(k)location.replace('/?klucz='+encodeURIComponent(k))}}"
                                          f"catch(e){{}}</script>")
            return self._wyslij(200, self.server.strona().encode("utf-8"), "text/html; charset=utf-8")
        if adres.path == "/jsQR.js":
            return self._wyslij(200, (KATALOG_WWW / "jsQR.js").read_bytes(), "text/javascript; charset=utf-8",
                                {"Cache-Control": "max-age=86400"})
        if adres.path == "/ca.crt" and self.server.plik_ca is not None:
            return self._wyslij(200, self.server.plik_ca.read_bytes(), "application/x-x509-ca-cert",
                                {"Content-Disposition": 'attachment; filename="nornica-ca.crt"'})
        return self._strona_bledu(404, "mobilny.nie_znaleziono")

    do_HEAD = do_GET

    # --- POST ----------------------------------------------------------------------
    def do_POST(self):
        if urlsplit(self.path).path == "/api/zdjecie":
            return self._przyjmij_zdjecie()
        if urlsplit(self.path).path != "/api/skan":
            return self._strona_bledu(404, "mobilny.nie_znaleziono")
        if not self._uprawniony():
            return self._wyslij(403, b'{"blad":"403"}', "application/json")
        try:
            dlugosc = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            dlugosc = -1
        if not 0 < dlugosc <= MAKS_ZAPYTANIE:
            return self._wyslij(413, b'{"blad":"413"}', "application/json")
        try:
            kod = str(json.loads(self.rfile.read(dlugosc)).get("kod", ""))[:64]
        except (ValueError, AttributeError):
            return self._wyslij(400, b'{"blad":"400"}', "application/json")
        try:
            karta = self.server.most.zapytaj("skan", kod)
        except queue.Empty:
            return self._wyslij(503, b'{"blad":"503"}', "application/json")
        self._wyslij(200, json.dumps(karta, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")


    def _json(self, kod: int, dane: dict) -> None:
        self._wyslij(kod, json.dumps(dane, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _odrzuc_tresc(self, dlugosc: int) -> None:
        """Odbiera i wyrzuca treść zapytania (najwyżej MAKS_ZDJECIE — sprawdzone wcześniej)."""
        while dlugosc > 0:
            blok = self.rfile.read(min(1 << 20, dlugosc))
            if not blok:
                break
            dlugosc -= len(blok)

    def _przyjmij_zdjecie(self) -> None:
        """Zdjęcie z telefonu: sam plik w treści zapytania, kod egzemplarza i opcje
        w nagłówkach. Typ sprawdzany po zawartości. Suma i miniatura liczone TU,
        w wątku serwera; do wątku interfejsu trafia tylko zapis do bazy."""
        from uslugi import pliki
        try:
            dlugosc = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            dlugosc = -1
        if not 0 < dlugosc <= MAKS_ZDJECIE:
            # nie odbieramy treści — połączenie zamykamy, zamiast czytać 100 MB
            self.close_connection = True
            return self._json(413, {"blad": t("mobilny.zdjecie_za_duze", mb=MAKS_ZDJECIE // 2**20)})
        if not self._uprawniony():
            # Treść odebrana i odrzucona PRZED odpowiedzią: inaczej telefon wciąż wysyła
            # zdjęcie, serwer zamyka połączenie i odpowiedź ginie — telefon pokazałby
            # „brak połączenia” zamiast „telefon nie jest sparowany”.
            self._odrzuc_tresc(dlugosc)
            return self._json(403, {"blad": t("mobilny.brak_parowania")})
        kod = unquote(self.headers.get("X-Nornica-Kod", ""))[:64]
        nazwa = unquote(self.headers.get("X-Nornica-Nazwa", ""))[:120]
        glowne = self.headers.get("X-Nornica-Glowne") == "1"
        poczatek = self.rfile.read(min(32, dlugosc))
        rozszerzenie = pliki.typ_obrazu(poczatek)
        if rozszerzenie is None:
            self._odrzuc_tresc(dlugosc - len(poczatek))     # jak wyżej: odpowiedź musi dotrzeć
            return self._json(415, {"blad": t("mobilny.zdjecie_zly_typ")})
        deskryptor, tymczasowy = tempfile.mkstemp(prefix="nornica-", suffix=rozszerzenie)
        try:
            with os.fdopen(deskryptor, "wb") as plik:
                plik.write(poczatek)
                pozostalo = dlugosc - len(poczatek)
                while pozostalo > 0:
                    blok = self.rfile.read(min(1 << 20, pozostalo))
                    if not blok:
                        raise ConnectionError("przerwane wysyłanie")
                    plik.write(blok)
                    pozostalo -= len(blok)
            wstepnie = pliki.przygotuj(tymczasowy)
            karta = self.server.most.zapytaj("zdjecie", {"kod": kod, "sciezka": tymczasowy, "nazwa": nazwa,
                                                         "glowne": glowne, "wstepnie": wstepnie}, limit=60)
        except queue.Empty:
            return self._json(503, {"blad": t("mobilny.zdjecie_blad")})
        finally:
            Path(tymczasowy).unlink(missing_ok=True)     # oryginał jest już w magazynie programu
        self._json(200, karta)


class _Serwer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, adres, most: Most, klucz: str, plik_ca: Path | None, https: bool):
        super().__init__(adres, _Obsluga)
        self.most, self.klucz, self.plik_ca, self.https = most, klucz, plik_ca, https

    def handle_error(self, request, client_address):
        pass      # nieudane uzgadnianie TLS (np. telefon odrzucił certyfikat) — nie zaśmiecamy terminala

    def strona(self) -> str:
        """Strona telefonu z napisami w BIEŻĄCYM języku programu — powstaje przy każdym wejściu."""
        szablon = (KATALOG_WWW / "skaner.html").read_text(encoding="utf-8")
        napisy = {k: t(k) for k in KLUCZE_STRONY}
        return (szablon.replace("{{JEZYK}}", jezyk_biezacy())
                .replace("{{TYTUL}}", escape(t("mobilny.tytul")))
                .replace("{{NAPISY}}", json.dumps(napisy, ensure_ascii=False).replace("</", "<\\/")))


class SerwerMobilny:
    """Serwer w osobnym wątku. Uruchamiany i zatrzymywany przez okno programu."""

    def __init__(self, most: Most, klucz: str):
        self.most = most
        self.klucz = klucz
        self._serwer: _Serwer | None = None
        self._watek: threading.Thread | None = None
        self.port: int | None = None
        self.https = False

    @property
    def dziala(self) -> bool:
        return self._serwer is not None

    def ustaw_klucz(self, klucz: str) -> None:
        """Nowy klucz: telefony sparowane starym muszą zeskanować kod ponownie."""
        self.klucz = klucz
        if self._serwer is not None:
            self._serwer.klucz = klucz

    def uruchom(self, port: int = PORT_DOMYSLNY, certyfikaty: dict | None = None, adres: str = "0.0.0.0") -> int:
        """Zwraca port. certyfikaty=None → zwykłe HTTP (tylko tryb zdjęcia na telefonie).
        Gdy port jest zajęty, próbuje kolejnych. port=0: dowolny wolny (testy)."""
        if self.dziala:
            return self.port
        ostatni_blad = None
        for proba in ([0] if port == 0 else range(port, port + PROB_PORTOW)):
            try:
                serwer = _Serwer((adres, proba), self.most, self.klucz,
                                 certyfikaty["ca"] if certyfikaty else None, certyfikaty is not None)
                break
            except OSError as blad:
                ostatni_blad = blad
        else:
            raise BladNornicy("blad.serwer_port", port=port, szczegoly=str(ostatni_blad))
        if certyfikaty:
            kontekst = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            kontekst.minimum_version = ssl.TLSVersion.TLSv1_2
            kontekst.load_cert_chain(certyfikaty["cert"], certyfikaty["klucz"])
            # uzgadnianie TLS w wątku obsługi połączenia, nie w pętli przyjmującej
            serwer.socket = kontekst.wrap_socket(serwer.socket, server_side=True, do_handshake_on_connect=False)
        self._serwer = serwer
        self.port = serwer.server_address[1]
        self.https = certyfikaty is not None
        self._watek = threading.Thread(target=serwer.serve_forever, name="serwer-skanera", daemon=True)
        self._watek.start()
        return self.port

    def zatrzymaj(self) -> None:
        if self._serwer is None:
            return
        self._serwer.shutdown()
        self._serwer.server_close()
        self._serwer = None
        self._watek = None

    def adres_parowania(self, ip: str) -> str:
        return f"{'https' if self.https else 'http'}://{ip}:{self.port}/?klucz={self.klucz}"

    def adres_certyfikatu(self, ip: str) -> str:
        return f"{'https' if self.https else 'http'}://{ip}:{self.port}/ca.crt"
