# SPDX-License-Identifier: GPL-3.0-or-later
"""Skąd asystent bierze strony: Ollama web search albo SearXNG.

Obie wyszukiwarki mają ten sam interfejs: szukaj(zapytanie) zwraca listę stron
z krótkim fragmentem, pobierz(strona) — tę samą stronę z pełnym tekstem
(albo z samym fragmentem, gdy pobranie się nie uda).

Ollama web search (https://docs.ollama.com/capabilities/web-search) wymaga
darmowego konta i klucza API. Do serwera Ollamy trafia samo zapytanie
(np. „KM44C4100 datasheet”) i adres pobieranej strony — nic z kolekcji.

SearXNG to wyszukiwarka uruchamiana u siebie (np. w Dockerze); w jej
ustawieniach musi być włączony format JSON (search: formats: [html, json]).
Strony pobiera wtedy sam program.

Klucz API: zmienna środowiskowa OLLAMA_API_KEY albo plik w folderze danych
z prawami tylko dla właściciela. Celowo NIE w bazie — baza trafia do kopii
zapasowych i eksportów.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from html.parser import HTMLParser

from wyjatki import BladNornicy

ZRODLA = ("ollama", "searxng")
ADRES_OLLAMA_WEB = "https://ollama.com"
MAKS_POBRANIE = 3 * 1024 * 1024          # bajtów strony
MAKS_TEKST = 60_000                      # znaków tekstu strony (i tak przycinane przed modelem)
PLIK_KLUCZA = "ollama_klucz.txt"


@dataclass(frozen=True)
class Strona:
    tytul: str
    adres: str
    tekst: str
    pelna: bool = False                  # False: tylko fragment z wyników wyszukiwania


# --------------------------------------------------------------------- klucz API
def _plik_klucza():
    import konfiguracja
    return konfiguracja.katalog_danych() / PLIK_KLUCZA


def klucz_api() -> str:
    """Klucz Ollama web search: najpierw zmienna środowiskowa, potem plik."""
    klucz = os.environ.get("OLLAMA_API_KEY", "").strip()
    if klucz:
        return klucz
    try:
        return _plik_klucza().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def zapisz_klucz(klucz: str) -> None:
    """Zapis klucza do pliku czytelnego tylko dla właściciela; pusty klucz usuwa plik."""
    plik = _plik_klucza()
    klucz = (klucz or "").strip()
    if not klucz:
        plik.unlink(missing_ok=True)
        return
    plik.parent.mkdir(parents=True, exist_ok=True)
    deskryptor = os.open(plik, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(deskryptor, "w", encoding="utf-8") as wyjscie:
        wyjscie.write(klucz)
    os.chmod(plik, 0o600)                # plik istniał wcześniej z szerszymi prawami


# ------------------------------------------------------------------- sieć, HTML
def _agent() -> str:
    from wersja import WERSJA
    return f"NORNICA-VOLE/{WERSJA} (collection catalogue; AI assistant, single lookup on user request)"


def _lokalny(adres: str) -> bool:
    return (urllib.parse.urlsplit(adres).hostname or "") in {"127.0.0.1", "localhost", "::1"}


def _otworz(adres: str, dane: dict | None = None, naglowki: dict | None = None, czas: float = 30):
    if urllib.parse.urlsplit(adres).scheme not in ("http", "https"):
        raise BladNornicy("asystent.blad_sieci", opis=adres)
    tresc = None if dane is None else json.dumps(dane).encode("utf-8")
    zapytanie = urllib.request.Request(adres, data=tresc, headers={
        "User-Agent": _agent(), **({"Content-Type": "application/json"} if dane is not None else {}),
        **(naglowki or {})})
    otwieracz = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
                 if _lokalny(adres) else urllib.request.build_opener())
    try:
        return otwieracz.open(zapytanie, timeout=czas)
    except urllib.error.HTTPError as blad:
        opis = f"HTTP {blad.code}"
        wyjasnienie = _tresc_bledu(blad)
        if wyjasnienie:
            opis += f": {wyjasnienie}"
        if blad.code in (401, 403):
            raise BladNornicy("asystent.blad_klucza", opis=opis) from None
        if blad.code in (402, 429):              # limit konta wyczerpany / za często
            raise BladNornicy("asystent.limit_wyszukiwania", opis=opis) from None
        raise BladNornicy("asystent.blad_sieci", opis=opis) from None
    except (urllib.error.URLError, OSError) as blad:
        raise BladNornicy("asystent.blad_sieci", opis=str(getattr(blad, "reason", blad))) from None


def _tresc_bledu(blad) -> str:
    """Wyjaśnienie, które serwer wysłał z błędem ({"error": "..."} albo krótki tekst)."""
    try:
        tresc = blad.read(2000).decode("utf-8", "replace").strip()
    except Exception:   # noqa: BLE001
        return ""
    try:
        dane = json.loads(tresc)
        if isinstance(dane, dict):
            tresc = str(dane.get("error") or dane.get("message") or "")
    except ValueError:
        pass
    if tresc.lstrip().startswith("<"):           # strona HTML zamiast komunikatu
        return ""
    return " ".join(tresc.split())[:200]


class _Tekst(HTMLParser):
    POMIJANE = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
    BLOKOWE = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table",
               "section", "article", "dt", "dd", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.czesci: list[str] = []
        self._pomin = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.POMIJANE:
            self._pomin += 1
        elif tag in self.BLOKOWE:
            self.czesci.append("\n")
        elif tag in ("td", "th"):
            self.czesci.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.POMIJANE and self._pomin:
            self._pomin -= 1
        elif tag in self.BLOKOWE:
            self.czesci.append("\n")

    def handle_data(self, data):
        if not self._pomin:
            self.czesci.append(data)


def html_na_tekst(html: str) -> str:
    """Treść strony bez skryptów i stylów; tabele jako „a | b”, puste linie zwinięte."""
    parser = _Tekst()
    parser.feed(html)
    parser.close()
    linie = (re.sub(r"[ \t\r\f\v ]+", " ", linia).strip(" |") for linia in "".join(parser.czesci).split("\n"))
    return "\n".join(linia for linia in linie if linia)[:MAKS_TEKST]


def pobierz_strone(strona: Strona) -> Strona:
    """Pełny tekst strony HTML pobrany przez program. PDF i inne formaty —
    zostaje fragment z wyszukiwarki (model dostaje wtedy mniej, ale uczciwie)."""
    try:
        with _otworz(strona.adres, naglowki={"Accept": "text/html,text/plain"}, czas=20) as odpowiedz:
            rodzaj = odpowiedz.headers.get_content_type()
            if rodzaj not in ("text/html", "text/plain", "application/xhtml+xml"):
                return strona
            dane = odpowiedz.read(MAKS_POBRANIE + 1)
            kodowanie = odpowiedz.headers.get_content_charset() or "utf-8"
    except BladNornicy:
        return strona
    tekst = dane[:MAKS_POBRANIE].decode(kodowanie, "replace")
    tekst = html_na_tekst(tekst) if rodzaj != "text/plain" else tekst[:MAKS_TEKST]
    return replace(strona, tekst=tekst, pelna=True) if tekst.strip() else strona


# ------------------------------------------------------------------ wyszukiwarki
class OllamaWeb:
    """Ollama web search: wyniki i pobieranie stron po stronie Ollamy (także PDF)."""

    def __init__(self, klucz: str | None = None, adres: str = ADRES_OLLAMA_WEB):
        self.klucz = (klucz if klucz is not None else klucz_api()).strip()
        self.adres = adres.rstrip("/")
        if not self.klucz:
            raise BladNornicy("asystent.brak_klucza")

    def _zapytaj(self, sciezka: str, dane: dict) -> dict:
        naglowki = {"Authorization": f"Bearer {self.klucz}"}
        with _otworz(self.adres + sciezka, dane, naglowki) as odpowiedz:
            return json.loads(odpowiedz.read(MAKS_POBRANIE).decode("utf-8", "replace"))

    def szukaj(self, zapytanie: str, ile: int = 5) -> list[Strona]:
        wynik = self._zapytaj("/api/web_search", {"query": zapytanie, "max_results": max(1, min(ile, 10))})
        return [Strona(w.get("title") or w["url"], w["url"], (w.get("content") or "")[:MAKS_TEKST])
                for w in wynik.get("results", []) if w.get("url")]

    def pobierz(self, strona: Strona) -> Strona:
        try:
            wynik = self._zapytaj("/api/web_fetch", {"url": strona.adres})
        except BladNornicy:
            return strona
        tekst = (wynik.get("content") or "").strip()[:MAKS_TEKST]
        return replace(strona, tytul=wynik.get("title") or strona.tytul, tekst=tekst, pelna=True) if tekst else strona


class SearXNG:
    """Własna instancja SearXNG; strony pobiera program."""

    def __init__(self, adres: str):
        adres = (adres or "").strip().rstrip("/")
        if urllib.parse.urlsplit(adres).scheme not in ("http", "https"):
            raise BladNornicy("asystent.brak_searxng")
        self.adres = adres

    def szukaj(self, zapytanie: str, ile: int = 5) -> list[Strona]:
        adres = f"{self.adres}/search?" + urllib.parse.urlencode({"q": zapytanie, "format": "json"})
        try:
            with _otworz(adres, naglowki={"Accept": "application/json"}) as odpowiedz:
                wynik = json.loads(odpowiedz.read(MAKS_POBRANIE).decode("utf-8", "replace"))
        except BladNornicy as blad:
            if "403" in str(blad.pola.get("opis", "")) or blad.klucz == "asystent.blad_klucza":
                raise BladNornicy("asystent.searxng_bez_json") from None
            raise
        except ValueError:
            raise BladNornicy("asystent.searxng_bez_json") from None
        return [Strona(w.get("title") or w["url"], w["url"], (w.get("content") or "")[:MAKS_TEKST])
                for w in wynik.get("results", [])[:ile] if w.get("url")]

    def pobierz(self, strona: Strona) -> Strona:
        return pobierz_strone(strona)


def wyszukiwarka(zrodlo: str, searxng: str = "", klucz: str | None = None):
    """Wyszukiwarka wybrana w oknie asystenta."""
    if zrodlo == "searxng":
        return SearXNG(searxng)
    return OllamaWeb(klucz)
