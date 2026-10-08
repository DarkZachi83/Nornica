# SPDX-License-Identifier: GPL-3.0-or-later
"""The Retro Web (https://theretroweb.com) — uzupełnianie modelu danymi ze strony.

Serwis: społeczna baza sprzętu PC (płyty główne, karty rozszerzeń, dyski,
napędy). Komputerów 8-bitowych ani konsol jako całości w nim nie ma.

LICENCJA. Treści The Retro Web są na licencji CC BY-SA 4.0, a kopiowanie
danych dopuszczają przy akceptacji GPL-3.0 i CC BY-SA 4.0
(https://theretroweb.com/info/legal). NORNICA jest na GPL-3.0. Warunek
CC BY-SA — podanie źródła — spełnia link w polu „Strona źródłowa” i dopisek
w opisie modelu. Przenosimy TYLKO dane tekstowe: zdjęcia na stronach bywają
podpisane nazwiskami innych autorów, więc ich nie kopiujemy.

KULTURA DOSTĘPU. Mały serwis prowadzony przez wolontariuszy: jedno pobranie
na jedno kliknięcie użytkownika, nazwa programu w nagłówku User-Agent,
poszanowanie robots.txt (sprawdzane przed pobraniem), limit rozmiaru.
Brak publicznego API — czytamy zwykłą stronę HTML. Strona zapisana
w przeglądarce działa tak samo (import z pliku).

CZYTNIK na bibliotece standardowej (html.parser) — bez nowych zależności.
Zbudowany i przetestowany na prawdziwych stronach (testy/dane/trw/).
Gdy serwis zmieni wygląd stron, testy pokażą, co przestało działać.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlsplit

from wyjatki import BladNornicy

HOST = "theretroweb.com"
LICENCJA = "CC BY-SA 4.0"
MAKS_ROZMIAR = 3 * 1024 * 1024
_PUSTE = {"", "empty", "unknown", "n/a"}


# ---------------------------------------------------------------------------
# Minimalne drzewo HTML (html.parser z biblioteki standardowej)
# ---------------------------------------------------------------------------
_PUSTE_ZNACZNIKI = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                    "source", "track", "wbr", "param"}


class Wezel:
    __slots__ = ("tag", "atrybuty", "dzieci", "rodzic")

    def __init__(self, tag: str, atrybuty: dict, rodzic: "Wezel | None"):
        self.tag, self.atrybuty, self.dzieci, self.rodzic = tag, atrybuty, [], rodzic

    @property
    def klasy(self) -> set[str]:
        return set((self.atrybuty.get("class") or "").split())

    def elementy(self) -> list["Wezel"]:
        return [d for d in self.dzieci if isinstance(d, Wezel)]

    def potomkowie(self):
        for d in self.dzieci:
            if isinstance(d, Wezel):
                yield d
                yield from d.potomkowie()

    def z_klasa(self, klasa: str) -> list["Wezel"]:
        return [w for w in self.potomkowie() if klasa in w.klasy]

    def pierwszy(self, warunek) -> "Wezel | None":
        return next((w for w in self.potomkowie() if warunek(w)), None)

    def tekst(self) -> str:
        czesci = []

        def zbierz(w):
            for d in w.dzieci:
                if isinstance(d, str):
                    czesci.append(d)
                elif d.tag not in ("script", "style"):
                    zbierz(d)
        zbierz(self)
        return " ".join("".join(czesci).replace("\xa0", " ").split())


class _Budowniczy(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.korzen = Wezel("#dokument", {}, None)
        self._stos = [self.korzen]

    def handle_starttag(self, tag, atrybuty):
        wezel = Wezel(tag, {k: v or "" for k, v in atrybuty}, self._stos[-1])
        self._stos[-1].dzieci.append(wezel)
        if tag not in _PUSTE_ZNACZNIKI:
            self._stos.append(wezel)

    def handle_startendtag(self, tag, atrybuty):
        self._stos[-1].dzieci.append(Wezel(tag, {k: v or "" for k, v in atrybuty}, self._stos[-1]))

    def handle_endtag(self, tag):
        # zamknięcie najbliższego otwartego znacznika tej nazwy; nadmiarowe zamknięcia ignorowane
        for i in range(len(self._stos) - 1, 0, -1):
            if self._stos[i].tag == tag:
                del self._stos[i:]
                return

    def handle_data(self, dane):
        self._stos[-1].dzieci.append(dane)


def drzewo(html: str) -> Wezel:
    budowniczy = _Budowniczy()
    budowniczy.feed(html)
    budowniczy.close()
    return budowniczy.korzen


# ---------------------------------------------------------------------------
# Odczyt strony
# ---------------------------------------------------------------------------
@dataclass
class Strona:
    dzial: str                                  # Motherboards / Expansion cards / Hard drives / …
    id: str | None
    producent: str | None
    nazwa: str
    url: str | None
    parametry: dict[str, list[str]] = field(default_factory=dict)   # etykieta -> wartości
    zlacza: list[tuple[str, int, str]] = field(default_factory=list)  # (sekcja, ilość, nazwa)
    uklady: dict[str, list[str]] = field(default_factory=dict)       # rodzaj -> układy
    aliasy: list[str] = field(default_factory=list)


def _ilosc(tekst: str) -> int | None:
    m = re.match(r"\s*(\d+)\s*x", tekst or "", re.I)
    return int(m.group(1)) if m else None


_SCIEZKI_DZIALOW = {"motherboards": "Motherboards", "expansioncards": "Expansion cards",
                    "harddrives": "Hard drives", "cddrives": "Optical drives", "floppydrives": "Floppy & tape drives"}


def parsuj(html: str, url: str | None = None) -> Strona:
    """Strona produktu The Retro Web -> Strona. Zgłasza blad.trw_strona, gdy to
    nie jest strona produktu (np. strona główna, wyniki wyszukiwania, błąd)."""
    d = drzewo(html)
    # dział i ID ze ścieżki nawigacji: Home › Motherboards › ID: 5805
    okruszki = [w.tekst() for nav in d.z_klasa("navbar-subcategories") for w in nav.potomkowie() if w.tag == "li"]
    dzial = okruszki[1] if len(okruszki) > 1 else ""
    ident = next((o.split(":", 1)[1].strip() for o in okruszki if o.upper().startswith("ID:")), None)
    # nazwa: <div class="title"><a href=".../manufacturers/442">Zida</a>&nbsp;4DPS 2.x</div>
    tytul = d.pierwszy(lambda w: w.tag == "div" and w.klasy == {"title"})
    if tytul is None or not d.z_klasa("quick-spec-table"):
        raise BladNornicy("blad.trw_strona")
    link = tytul.pierwszy(lambda w: w.tag == "a" and "/manufacturers/" in w.atrybuty.get("href", ""))
    producent = link.tekst() if link else None
    pelna = tytul.tekst()
    if producent and pelna.startswith(producent):
        nazwa = pelna[len(producent):].strip()
    elif pelna.startswith("[Unknown]"):
        producent, nazwa = None, pelna[len("[Unknown]"):].strip()
    else:
        nazwa = pelna
    if url is None:
        meta = d.pierwszy(lambda w: w.tag == "meta" and w.atrybuty.get("property") == "og:url")
        url = meta.atrybuty.get("content") if meta else None
    if not dzial and url:                       # zapas: dział z adresu strony
        dzial = _SCIEZKI_DZIALOW.get(urlsplit(url).path.strip("/").split("/")[0], "")
    strona = Strona(dzial=dzial, id=ident, producent=producent, nazwa=nazwa, url=url)

    # tabela parametrów: pary <div class="quick-spec-head">Etykieta</div> + element z wartością
    for tabela in d.z_klasa("quick-spec-table"):
        elementy = tabela.elementy()
        for i, w in enumerate(elementy):
            if "quick-spec-head" not in w.klasy or i + 1 >= len(elementy):
                continue
            wartosc = elementy[i + 1]
            if "quick-spec-head" in wartosc.klasy:
                continue                         # pusta pozycja — od razu kolejna etykieta
            pozycje = [x.tekst() for x in wartosc.potomkowie() if x.tag == "li"] or \
                      [x.tekst() for x in wartosc.z_klasa("text-block")] or [wartosc.tekst()]
            pozycje = [p for p in pozycje if p.casefold() not in _PUSTE]
            if pozycje:
                strona.parametry[w.tekst()] = pozycje

    # porty i złącza: <div class="full-spec-head">Sekcja</div> + list-table z parami „1x” / nazwa;
    # wiersze bez liczby sztuk to uzupełnienia poprzedniej pozycji (np. „DE-15, VGA”) — pomijane
    for kolumna in d.z_klasa("full-spec-col"):
        glowa = next((w for w in kolumna.potomkowie() if "full-spec-head" in w.klasy), None)
        lista = next((w for w in kolumna.potomkowie() if "list-table" in w.klasy), None)
        if glowa is None or lista is None:
            continue
        ilosc = None
        for w in lista.elementy():
            if "list-table-head" in w.klasy:
                ilosc = _ilosc(w.tekst())
            elif ilosc is not None:
                nazwa_zlacza = w.tekst()
                if nazwa_zlacza.casefold() not in _PUSTE:
                    strona.zlacza.append((glowa.tekst(), ilosc, nazwa_zlacza))
                ilosc = None

    # układy: <span>-> Video</span><div class="tag-container"><a>ATI Rage XL</a></div>
    for lista in d.z_klasa("chip-list"):
        rodzaj = None
        for w in lista.elementy():
            if w.tag == "span":
                rodzaj = w.tekst().lstrip("->").strip()
            elif "tag-container" in w.klasy and rodzaj:
                strona.uklady.setdefault(rodzaj, []).extend(x.tekst() for x in w.z_klasa("text-block"))

    # inne nazwy tej samej konstrukcji
    for karta in d.z_klasa("card"):
        naglowek = next((w for w in karta.potomkowie() if "card-header" in w.klasy), None)
        if naglowek and naglowek.tekst() == "Also known as":
            strona.aliasy = [w.tekst() for w in karta.potomkowie() if w.tag == "li"]
    return strona


# ---------------------------------------------------------------------------
# Dopasowanie do kategorii, pól i złączy programu
# ---------------------------------------------------------------------------
# (wzorzec nazwy w The Retro Web, kod typu złącza w programie) — pierwsze trafienie wygrywa
ZLACZA = [
    (r"super\s*socket\s*7", "super7"), (r"socket\s*370", "socket370"), (r"socket\s*a\b|socket\s*462", "socket_a"),
    (r"socket\s*7\b", "socket7"), (r"socket\s*3\b", "socket3"), (r"slot\s*1\b", "slot1"), (r"slot\s*a\b", "slot_a"),
    (r"pga.?132", "pga132"), (r"plcc.?68", "plcc68"), (r"dip.?40", "dip40"),
    (r"30.?pin\s*simm", "simm30"), (r"72.?pin\s*simm", "simm72"),
    (r"184.?pin|ddr\s*dimm", "dimm184"), (r"168.?pin|sdr\s*dimm|dimm", "dimm168"),
    (r"sata\s*power", "zasilanie_sata"), (r"\batx\b.*20|20.?pin\s*atx", "zasilanie_atx20"), (r"\bat\b.*p8|p8.*p9", "zasilanie_at"),
    (r"molex", "zasilanie_molex"), (r"berg|floppy\s*power|mini.?molex", "zasilanie_berg"),
    (r"8.?bit\s*isa", "isa8"), (r"16.?bit\s*isa|\bisa\b", "isa16"), (r"\beisa\b", "eisa"),
    (r"\bvlb\b|vesa\s*local", "vlb"), (r"pci\s*e(xpress)?\s*x?16|pcie\s*x?16", "pcie_x16"),
    (r"pci\s*e(xpress)?\s*x?1\b|pcie\s*x?1\b", "pcie_x1"), (r"\bagp\b", "agp"), (r"\bpci\b", "pci"),
    (r"at\s*keyboard", "din5_klawiatura"), (r"ps/?2", "ps2"), (r"floppy", "fdd34"),
    (r"game\s*port", "gameport_da15"), (r"\bsata\b", "sata"), (r"\bide\b|\bata\b|pata", "ide40"),
    (r"scsi", "scsi50"), (r"st.?506|mfm|rll", "st506"),
    (r"parallel", "lpt_db25"), (r"serial", "com_db9"), (r"\busb\b", "usb_a"),
    (r"\bvga\b|de.?15", "vga_de15"), (r"\bcga\b|\bega\b|rgbi", "rgbi_de9"), (r"composite|rca", "kompozyt_rca"),
    (r"midi", "midi_din5"), (r"rj.?45|ethernet|10base.?t", "rj45"), (r"bnc|10base.?2", "bnc"),
]

DZIALY = {"Motherboards": "plyty_glowne", "Hard drives": "dyski_twarde", "Optical drives": "napedy_optyczne",
          "Floppy & tape drives": "napedy_dyskietek"}
TYPY_KART = [(r"video|graphic", "karty_graficzne"), (r"sound|audio", "karty_dzwiekowe"),
             (r"network|ethernet|lan", "karty_sieciowe"),
             (r"disk|storage|scsi|ide|controller|multi.?i/?o", "kontrolery")]
FORMATY_PLYT = [("baby at", "Baby AT"), ("micro atx", "Micro ATX"), ("microatx", "Micro ATX"), ("atx", "ATX"),
                ("lpx", "LPX"), ("nlx", "NLX"), ("xt", "XT"), ("at", "AT")]


@dataclass
class Propozycja:
    kategoria_kod: str
    producent: str | None
    nazwa: str
    rok_od: int | None
    zrodlo_url: str | None
    atrybuty: dict = field(default_factory=dict)              # kod pola -> wartość
    zlacza: dict = field(default_factory=dict)                # (typ_id, rola) -> ilość
    zlacza_opis: list[tuple[str, str, int]] = field(default_factory=list)   # (rola, nazwa w programie, ilość)
    nieprzypisane: list[str] = field(default_factory=list)    # złącza bez odpowiednika
    opis: str = ""                                            # dopisek do opisu modelu


def pojemnosc(tekst: str, dziesietnie: bool = False) -> int | None:
    """„64MB” -> 67108864; dyski (dziesietnie=True): „500GB” -> 500·10⁹ bajtów —
    producenci dysków liczą gigabajty dziesiętnie (pojemność z naklejki)."""
    m = re.match(r"\s*([\d.,]+)\s*([KMGT]?)i?B\b", tekst or "", re.I)
    if not m:
        return None
    podstawa = 1000 if dziesietnie else 1024
    wykladnik = " KMGT".index(m.group(2).upper() or " ")
    try:
        return int(Decimal(m.group(1).replace(",", ".")) * podstawa ** wykladnik)
    except InvalidOperation:
        return None


def _rok(tekst: str | None) -> int | None:
    m = re.search(r"\b(19[6-9]\d|20[0-4]\d)\b", tekst or "")
    return int(m.group(1)) if m else None


def _typ_zlacza(nazwa: str) -> str | None:
    return next((kod for wzorzec, kod in ZLACZA if re.search(wzorzec, nazwa, re.I)), None)


def _kategoria(strona: Strona) -> str:
    if strona.dzial in DZIALY:
        return DZIALY[strona.dzial]
    if strona.dzial == "Expansion cards":
        typ = " ".join(strona.parametry.get("Type", []))
        return next((kod for wzorzec, kod in TYPY_KART if re.search(wzorzec, typ, re.I)), "karty_inne")
    return "czesci"


def propozycja(db: sqlite3.Connection, strona: Strona) -> Propozycja:
    from i18n.tlumacz import nazwa as nazwa_slownika, t
    kategoria = _kategoria(strona)
    p = Propozycja(kategoria_kod=kategoria, producent=strona.producent, nazwa=strona.nazwa,
                   rok_od=_rok(" ".join(strona.parametry.get("Release date", []))), zrodlo_url=strona.url)
    par = strona.parametry
    uzyte = {"Release date", "Type"}

    def ustaw(kod, etykieta, przeksztalcenie=lambda w: w[0]):
        if etykieta in par:
            wartosc = przeksztalcenie(par[etykieta])
            if wartosc not in (None, ""):
                p.atrybuty[kod] = wartosc
                uzyte.add(etykieta)

    if kategoria == "plyty_glowne":
        ustaw("chipset", "Chipset")
        ustaw("format", "Form factor", lambda w: next(
            (cel for wzorzec, cel in FORMATY_PLYT if w[0].casefold().startswith(wzorzec)), "inny / other"))
        ustaw("max_ram", "Max RAM size", lambda w: pojemnosc(w[0]))
        # cache: strona podaje warianty montażu — największy z nich
        ustaw("cache", "Cache", lambda w: max((pojemnosc(x) or 0 for x in w), default=None) or None)
    elif kategoria == "dyski_twarde":
        ustaw("pojemnosc", "Capacity", lambda w: pojemnosc(w[0], dziesietnie=True))
        ustaw("format_cali", "Form factor", lambda w: next(
            (f'{r}"' for r in ("5.25", "3.5", "2.5") if w[0].startswith(r)), None))
        for kod, etykiety in (("cylindry", ("Cylinders",)), ("glowice", ("Heads",)),
                              ("sektory", ("Sectors", "Sectors per track"))):
            for etykieta in etykiety:
                ustaw(kod, etykieta, lambda w: int(re.sub(r"\D", "", w[0]) or 0) or None)
    elif kategoria.startswith("karty_") or kategoria == "kontrolery":
        uklad = next((u for rodzaj in ("Video", "Graphics", "Audio", "Sound", "Network", "Controller")
                      for u in strona.uklady.get(rodzaj, [])), None)
        if uklad is None:
            uklad = next((u for lista in strona.uklady.values() for u in lista), None)
        if uklad:
            p.atrybuty["chipset"] = uklad
        if kategoria == "karty_graficzne":
            ustaw("pamiec", "RAM size", lambda w: pojemnosc(w[0]))

    # złącza: płyta posiada wszystko; karta/dysk WYMAGA interfejsu i zasilania, posiada porty
    typy = {w["kod"]: (w["id"], w["nazwy"]) for w in db.execute(
        "SELECT id, kod, nazwy FROM zlacze_typ WHERE kod IS NOT NULL")}
    pozycje = list(strona.zlacza)
    for etykieta in ("Interface", "RAM slot"):
        for wartosc in par.get(etykieta, []):
            ilosc = _ilosc(wartosc) or 1
            pozycje.append((etykieta, ilosc, re.sub(r"^\s*\d+\s*x\s*", "", wartosc, flags=re.I)))
            uzyte.add(etykieta)
    widziane = set()
    for sekcja, ilosc, nazwa in pozycje:
        if (sekcja, nazwa) in widziane:          # „RAM slot” bywa powtórzony bez liczby sztuk
            continue
        widziane.add((sekcja, nazwa))
        wymaga = kategoria != "plyty_glowne" and sekcja in ("Interface", "Power connector", "Power connectors")
        kod = _typ_zlacza(nazwa)
        if "power" in sekcja.casefold() or "psu" in sekcja.casefold():
            # w sekcjach zasilania tylko typy zasilania: „SATA Power (15-pin)” to nie złącze danych SATA
            kod = kod if kod and kod.startswith("zasilanie_") else None
        if kategoria == "dyski_twarde" and kod == "ide40" and "2.5" in " ".join(par.get("Form factor", [])):
            kod = "ide44"
        if kod is None or kod not in typy:
            p.nieprzypisane.append(f"{sekcja}: {ilosc}× {nazwa}")
            continue
        rola = "wymaga" if wymaga else "posiada"
        klucz = (typy[kod][0], rola)
        p.zlacza[klucz] = p.zlacza.get(klucz, 0) + ilosc
    for (typ_id, rola), ilosc in p.zlacza.items():
        nazwy = next(n for i, n in typy.values() if i == typ_id)
        p.zlacza_opis.append((rola, nazwa_slownika(nazwy), ilosc))

    # opis: źródło i licencja (warunek CC BY-SA) + wszystko, czego nie przypisano do pól
    linie = [t("trw.zrodlo", url=strona.url or f"https://{HOST}", licencja=LICENCJA)]
    if strona.aliasy:
        linie.append(t("trw.aliasy", lista=", ".join(strona.aliasy)))
    for etykieta, wartosci in par.items():
        if etykieta not in uzyte:
            linie.append(f"{etykieta}: {', '.join(wartosci)}")
    for rodzaj, uklady in strona.uklady.items():
        linie.append(f"{rodzaj}: {', '.join(uklady)}")
    if p.nieprzypisane:
        linie.append(t("trw.nieprzypisane", lista="; ".join(p.nieprzypisane)))
    p.opis = "\n".join(linie)
    return p


# ---------------------------------------------------------------------------
# Wyszukiwanie i pobieranie
# ---------------------------------------------------------------------------
def adres_wyszukiwania(producent: str | None, nazwa: str | None) -> str:
    """Serwis nie ma publicznego API wyszukiwania — zwykła wyszukiwarka z filtrem site:."""
    zapytanie = " ".join(c for c in (f"site:{HOST}", producent, nazwa) if c)
    return f"https://duckduckgo.com/?q={quote_plus(zapytanie)}"


def sprawdz_adres(url: str) -> str:
    url = (url or "").strip()
    czesci = urlsplit(url)
    if czesci.scheme != "https" or (czesci.hostname or "").lower().removeprefix("www.") != HOST \
            or not re.match(r"^/(motherboards|expansioncards|harddrives|cddrives|floppydrives)/", czesci.path):
        raise BladNornicy("blad.trw_adres")
    return url


_roboty = None


def _wolno(url: str, agent: str, otworz) -> bool:
    """robots.txt serwisu — sprawdzany przed pobraniem (wczytywany raz na sesję)."""
    global _roboty
    from urllib.robotparser import RobotFileParser
    if _roboty is None:
        roboty = RobotFileParser()
        try:
            with otworz(f"https://{HOST}/robots.txt") as odpowiedz:
                roboty.parse(odpowiedz.read(256 * 1024).decode("utf-8", "replace").splitlines())
        except Exception:   # noqa: BLE001 — brak robots.txt: zgodnie ze standardem wszystko dozwolone
            roboty.parse([])
        _roboty = roboty
    return _roboty.can_fetch(agent, url)


def pobierz(url: str) -> str:
    """Jedno pobranie strony produktu na żądanie użytkownika. Woła się w wątku
    pobocznym (sieć potrafi trwać) — nie dotyka bazy ani okien."""
    import urllib.error
    import urllib.request
    from wersja import WERSJA
    url = sprawdz_adres(url)
    agent = f"NORNICA-VOLE/{WERSJA} (collection catalogue; single page on user request)"

    def otworz(adres):
        zapytanie = urllib.request.Request(adres, headers={"User-Agent": agent, "Accept": "text/html"})
        return urllib.request.urlopen(zapytanie, timeout=20)

    if not _wolno(url, agent, otworz):
        raise BladNornicy("blad.trw_robots")
    try:
        with otworz(url) as odpowiedz:
            dane = odpowiedz.read(MAKS_ROZMIAR + 1)
            kodowanie = odpowiedz.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as blad:
        raise BladNornicy("blad.trw_siec", opis=f"HTTP {blad.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as blad:
        raise BladNornicy("blad.trw_siec", opis=str(getattr(blad, "reason", blad))) from None
    if len(dane) > MAKS_ROZMIAR:
        raise BladNornicy("blad.trw_strona")
    return dane.decode(kodowanie, "replace")


def wczytaj_plik(sciezka) -> str:
    """Strona zapisana w przeglądarce (Ctrl+S) — bez sieci."""
    from pathlib import Path
    sciezka = Path(sciezka)
    if sciezka.stat().st_size > MAKS_ROZMIAR:
        raise BladNornicy("blad.trw_strona")
    return sciezka.read_text(encoding="utf-8", errors="replace")
