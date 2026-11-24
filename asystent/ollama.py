# SPDX-License-Identifier: GPL-3.0-or-later
"""Lokalny model językowy przez Ollamę (https://ollama.com).

Tylko ten komputer: adres musi wskazywać pętlę zwrotną (127.0.0.1, localhost,
::1). Dane kolekcji nie wychodzą do żadnego serwera modeli. Połączenie idzie
z pominięciem serwera pośredniczącego (proxy) — inaczej zmienna HTTPS_PROXY
mogłaby skierować „lokalne” zapytanie gdzie indziej.

Odpowiedź modelu jest wymuszona schematem JSON (structured outputs), więc
nie trzeba wyłuskiwać danych z prozy. Generowanie da się przerwać: drugi wątek
zamyka połączenie, a Ollama przestaje liczyć, gdy klient się rozłączy.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from wyjatki import BladNornicy

ADRES_DOMYSLNY = "http://127.0.0.1:11434"
LOKALNE = {"127.0.0.1", "localhost", "::1"}
CZAS_OCZEKIWANIA = 300          # s na jedną operację sieci: wczytanie modelu bywa długie
KONTEKST = 12288                # tokenów: 3 strony źródeł + szablon; mieści się w 8 GB VRAM z modelem 8B


class Przerwano(Exception):
    """Użytkownik przerwał pracę asystenta."""


def sprawdz_adres(adres: str | None) -> str:
    """Adres Ollamy albo BladNornicy, gdy nie wskazuje tego komputera."""
    adres = (adres or ADRES_DOMYSLNY).strip().rstrip("/")
    czesci = urllib.parse.urlsplit(adres)
    if czesci.scheme not in ("http", "https") or (czesci.hostname or "") not in LOKALNE:
        raise BladNornicy("asystent.blad_adres_ollamy", adres=adres)
    return adres


_BEZ_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Ollama:
    def __init__(self, adres: str | None = None, czas: float = CZAS_OCZEKIWANIA):
        self.adres = sprawdz_adres(adres)
        self.czas = czas

    def _otworz(self, sciezka: str, dane: dict | None = None):
        tresc = None if dane is None else json.dumps(dane).encode("utf-8")
        zapytanie = urllib.request.Request(self.adres + sciezka, data=tresc,
                                           headers={"Content-Type": "application/json"})
        try:
            return _BEZ_PROXY.open(zapytanie, timeout=self.czas)
        except urllib.error.HTTPError as blad:
            opis = blad.read(2000).decode("utf-8", "replace")
            try:
                opis = json.loads(opis).get("error", opis)
            except ValueError:
                pass
            raise BladNornicy("asystent.blad_ollamy", opis=f"HTTP {blad.code}: {opis}") from None
        except (urllib.error.URLError, OSError) as blad:
            raise BladNornicy("asystent.brak_ollamy", adres=self.adres,
                              opis=str(getattr(blad, "reason", blad))) from None

    def modele(self) -> list[str]:
        """Modele pobrane do Ollamy, alfabetycznie. BladNornicy, gdy Ollama nie działa."""
        with self._otworz("/api/tags") as odpowiedz:
            dane = json.loads(odpowiedz.read().decode("utf-8"))
        return sorted(m["name"] for m in dane.get("models", []) if m.get("name"))

    def czat(self, model: str, wiadomosci: list[dict], schemat: dict | None = None,
             anuluj: threading.Event | None = None) -> dict:
        """Jedna odpowiedź modelu jako słownik z JSON-a zgodnego ze schematem.
        Zgłasza Przerwano (anuluj ustawione) albo BladNornicy."""
        dane = {"model": model, "messages": wiadomosci, "stream": True, "think": False,
                "options": {"temperature": 0, "num_ctx": KONTEKST}}
        if schemat is not None:
            dane["format"] = schemat
        try:
            tekst = self._strumien(dane, anuluj)
        except BladNornicy as blad:
            # model bez trybu „myślenia” odrzuca samo pole think — jeszcze raz bez niego
            if "think" not in str(blad.pola.get("opis", "")):
                raise
            del dane["think"]
            tekst = self._strumien(dane, anuluj)
        try:
            return json.loads(tekst)
        except ValueError:
            raise BladNornicy("asystent.blad_odpowiedzi", opis=tekst[:300]) from None

    def _strumien(self, dane: dict, anuluj: threading.Event | None) -> str:
        if anuluj is not None and anuluj.is_set():
            raise Przerwano()
        odpowiedz = self._otworz("/api/chat", dane)
        koniec = threading.Event()

        def pilnuj():                       # przerwanie = zamknięcie połączenia z drugiego wątku
            while not koniec.wait(0.2):
                if anuluj is not None and anuluj.is_set():
                    odpowiedz.close()
                    return

        if anuluj is not None:
            threading.Thread(target=pilnuj, name="ollama-przerwij", daemon=True).start()
        czesci = []
        try:
            with odpowiedz:
                for linia in odpowiedz:
                    if not linia.strip():
                        continue
                    kawalek = json.loads(linia)
                    if kawalek.get("error"):
                        raise BladNornicy("asystent.blad_ollamy", opis=kawalek["error"])
                    czesci.append(kawalek.get("message", {}).get("content", ""))
                    if kawalek.get("done"):
                        break
        except (OSError, ValueError, AttributeError) as blad:
            if anuluj is not None and anuluj.is_set():
                raise Przerwano() from None
            raise BladNornicy("asystent.blad_ollamy", opis=str(blad)) from None
        finally:
            koniec.set()
        if anuluj is not None and anuluj.is_set():
            raise Przerwano()
        return "".join(czesci)
