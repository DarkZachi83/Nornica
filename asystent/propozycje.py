# SPDX-License-Identifier: GPL-3.0-or-later
"""Od opisu przedmiotu do sprawdzonych propozycji parametrów.

1. Zapytanie z producenta, nazwy i oznaczeń (użytkownik może je poprawić).
2. Wyszukiwarka zwraca strony, program pobiera pierwsze trzy.
3. Model dostaje pola kategorii i ponumerowane źródła; odpowiada JSON-em
   wymuszonym schematem: wartość, numer źródła i DOSŁOWNY cytat.
4. Program sprawdza każdą wartość:
   - czy pasuje do typu pola (lista wyboru, liczba, zakres, pojemność),
   - czy cytat naprawdę jest w tekście wskazanego źródła.
   Wartość z błędem nie da się wstawić; bez potwierdzonego cytatu jest
   „niepotwierdzona” i nie jest zaznaczana domyślnie.

Małe modele lokalne (4–8B) chętnie zmyślają parametry — dlatego to program,
nie model, decyduje, co uznać za potwierdzone.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field

from asystent.ollama import Przerwano
from asystent.wyszukiwarki import Strona
from wyjatki import BladNornicy

ILE_WYNIKOW = 5
ILE_STRON = 3
ZNAKOW_ZE_STRONY = 4000           # 3 strony × 4000 znaków ≈ 3–4 tys. tokenów
MAKS_CYTAT = 300
PRODUCENT, NAZWA = "model.producent", "model.nazwa"     # pola ogólne modelu (kropka: nie koliduje z kodami pól)
PELNE, PODOBNE, BRAK = "pelne", "podobne", "brak"         # dopasowanie źródła do oznaczeń przedmiotu
INNA_NAZWA = "inna_nazwa"        # nazwa ze źródła nie zawiera żadnego oznaczenia przedmiotu

JEZYKI_ODPOWIEDZI = {"pl": "Polish", "en": "English"}
OPISY_TYPOW = {
    "text": "short text",
    "int": "whole number, digits only",
    "real": "decimal number, digits only",
    "zakres": "number or range, e.g. 1.225-1.325",
    "bool": "true or false",
    "pojemnosc": "capacity with unit, e.g. 16 MB",
    "enum": "exactly one of the allowed values",
}


@dataclass
class Wartosc:
    kod: str
    etykieta: str
    wartosc: object                  # wartość do formularza (jak w bazie); None przy błędzie
    tekst: str                       # wartość do wyświetlenia
    zrodlo: Strona | None
    cytat: str
    potwierdzona: bool
    blad: str | None = None          # klucz tłumaczenia
    dopasowanie: str = PELNE         # czy źródło wymienia oznaczenie przedmiotu (PELNE / PODOBNE / BRAK)
    podobne: str = ""                # przy PODOBNE: oznaczenie znalezione na stronie

    @property
    def mozna_wstawic(self) -> bool:
        return self.blad is None and self.wartosc not in (None, "")


@dataclass
class Wynik:
    zapytanie: str
    wartosci: list[Wartosc] = field(default_factory=list)
    zrodla: list[Strona] = field(default_factory=list)
    uwagi: str = ""
    model: str = ""

    def wartosc(self, kod: str) -> Wartosc | None:
        return next((w for w in self.wartosci if w.kod == kod), None)

    def atrybuty(self, kody: set[str]) -> dict:
        """Wybrane wartości parametrów: {kod: wartość} — do FormularzAtrybutow.wstaw()."""
        return {w.kod: w.wartosc for w in self.wartosci
                if w.kod in kody and w.mozna_wstawic and w.kod not in (PRODUCENT, NAZWA)}


# ------------------------------------------------------------------- zapytanie
# Słowa z cyframi, które NIE są numerami części: pojemności, standardy pamięci,
# częstotliwości, czasy, liczby pinów, same liczby (rok, kod daty, ilość).
_NIE_NUMER = re.compile(
    r"^(\d{1,5}|\d+([.,]\d+)?\s*([kmgt]i?b|mb|gb|ns|mhz|ghz|v|w|pin|pins|piny|pinów|szt\.?)"
    r"|\d+-?(pin|pins|piny|pinów)|pc\d?-?\d{3,5}[a-z]?|ddr\d?-?\d{3,4}|sdram-?\d+|cl\d+|[x×*]\d+"
    r"|\d+[kmg]([x×]\d+)?|\d+-?bit(s|ów|owe?)?)$", re.I)       # organizacja kości: 32M, 4Mx16, 8-bit


def numery(*teksty: str) -> list[str]:
    """Numery części z tekstów (słowa z cyfrą, min. 3 znaki), z pierwszej linii
    każdego tekstu, bez dopisków w nawiasach i bez powtórzeń. Pomija parametry
    (256, 16MB, PC3200, DDR-400, 184-pin, 60ns) — zapytanie ma szukać przedmiotu."""
    wynik: list[str] = []
    for tekst in teksty:
        tekst = (tekst or "").strip()
        linia = re.sub(r"\([^)]*\)", " ", tekst.splitlines()[0] if tekst else "")
        for slowo in linia.split():
            slowo = slowo.strip(",;:")
            if (re.search(r"\d", slowo) and len(slowo) >= 3 and not _NIE_NUMER.match(slowo)
                    and slowo.casefold() not in {w.casefold() for w in wynik}):
                wynik.append(slowo)
    return wynik


def dopasowanie(zrodlo: Strona | None, oznaczenia: list[str]) -> tuple[str, str]:
    """Czy strona mówi o TYM przedmiocie: PELNE — wymienia któreś z oznaczeń;
    PODOBNE — tylko oznaczenie z tym samym początkiem (np. „GR400D64L3/512” zamiast
    „…/512DC”: inny wariant albo cała rodzina w karcie katalogowej); BRAK — żadnego.
    Krótkie oznaczenia (poniżej 5 znaków) nie są brane pod uwagę."""
    oznaczenia = [o for o in oznaczenia if len(o) >= 5]
    if not oznaczenia or zrodlo is None:
        return PELNE, ""
    tekst = _normalizuj(zrodlo.tekst)
    if any(_normalizuj(o) in tekst for o in oznaczenia):
        return PELNE, ""
    najlepsze = ""
    for oznaczenie in oznaczenia:
        minimum = max(5, -(-len(oznaczenie) * 6 // 10))             # co najmniej 60% długości
        for dlugosc in range(len(oznaczenie) - 1, minimum - 1, -1):
            trafienie = re.search(re.escape(oznaczenie[:dlugosc]) + r"[\w/.\-]*", zrodlo.tekst, re.I)
            if trafienie:
                if dlugosc > len(najlepsze):
                    najlepsze = trafienie.group(0)
                break
    return (PODOBNE, najlepsze) if najlepsze else (BRAK, "")


def zapytanie(producent: str = "", nazwa: str = "", oznaczenia: str = "") -> str:
    """„Samsung KMM5321200AW-6 KM44C1000AJ-6 datasheet” — z pierwszej linii oznaczeń
    tylko numery części (słowa z cyfrą), bez dopisków w nawiasach i bez powtórzeń.
    Słowo „datasheet” kieruje do kart katalogowych."""
    slowa: list[str] = []
    for czesc in (producent, nazwa, " ".join(numery(oznaczenia))):
        for slowo in (czesc or "").split():
            if slowo.casefold() not in {s.casefold() for s in slowa}:
                slowa.append(slowo)
    tekst = " ".join(slowa)[:120].strip()
    return f"{tekst} datasheet" if tekst else ""


# ------------------------------------------------------------- polecenie dla modelu
def schemat(szablon: list[dict]) -> dict:
    """Schemat JSON odpowiedzi. Każde pole zawsze obecne; „nie wiem” = pusty
    napis i źródło 0 (prostsza gramatyka niż null — działa w każdym modelu)."""
    def pole(wartosc: dict) -> dict:
        return {"type": "object", "required": ["wartosc", "zrodlo", "cytat"],
                "properties": {"wartosc": wartosc, "zrodlo": {"type": "integer"},
                               "cytat": {"type": "string"}}}

    pola = {}
    for opis in szablon:
        if opis["typ"] == "enum" and opis.get("wartosci"):
            pola[opis["kod"]] = pole({"type": "string", "enum": [*opis["wartosci"], ""]})
        else:
            pola[opis["kod"]] = pole({"type": "string"})
    return {"type": "object", "required": ["producent", "nazwa", "pola", "uwagi"],
            "properties": {"producent": pole({"type": "string"}), "nazwa": pole({"type": "string"}),
                           "pola": {"type": "object", "required": list(pola), "properties": pola},
                           "uwagi": {"type": "string"}}}


def _slowa_kluczowe(*teksty: str) -> list[str]:
    return [s.casefold() for tekst in teksty for s in re.split(r"[\s,;/]+", tekst or "") if len(s) >= 4]


def wycinek(tekst: str, slowa: list[str], dlugosc: int = ZNAKOW_ZE_STRONY) -> str:
    """Fragment strony zaczynający się tuż przed pierwszą wzmianką o przedmiocie —
    karty katalogowe mają przedmiot w środku długiej strony."""
    maly = tekst.casefold()
    trafienia = [maly.find(s) for s in slowa if s in maly]
    poczatek = max(0, min(trafienia) - 400) if trafienia else 0
    return tekst[poczatek:poczatek + dlugosc]


def wiadomosci(szablon: list[dict], dane: dict, zrodla: list[Strona], jezyk: str = "pl") -> list[dict]:
    from i18n.tlumacz import nazwa as nazwa_pola
    linie_pol = []
    for opis in szablon:
        typ = OPISY_TYPOW.get(opis["typ"], "short text")
        linia = f"- {opis['kod']}: {nazwa_pola(opis['nazwy'], 'en')} ({typ}"
        if opis.get("jednostka"):
            linia += f", unit {opis['jednostka']}"
        if opis["typ"] == "enum" and opis.get("wartosci"):
            linia += ", allowed: " + ", ".join(opis["wartosci"])
        linie_pol.append(linia + ")")
    slowa = _slowa_kluczowe(dane.get("nazwa", ""), dane.get("oznaczenia", ""))
    linie_zrodel = [f"[{i}] {s.tytul}\n{s.adres}\n{wycinek(s.tekst, slowa)}" for i, s in enumerate(zrodla, 1)]
    system = (
        "You extract technical specifications of retro computer hardware from web pages. "
        "Use ONLY the numbered sources below, never your own memory. "
        "For every field: if a source states the value, put it in 'wartosc', the source number in "
        "'zrodlo' and in 'cytat' a short fragment copied EXACTLY, character for character, from that "
        "source that proves the value (max 200 characters). If no source states it, use an empty "
        "'wartosc', zrodlo 0 and an empty 'cytat'. Do not guess and do not convert units unless the "
        "field asks for it. If the item markings match several variants, leave the field empty and "
        "explain in 'uwagi'. A source may describe a similar but different product (another suffix, "
        "e.g. GR400D64L3/512 instead of GR400D64L3/512DC): then say so in 'uwagi'. Part numbers ending "
        "with DC, K2 or KIT are kits of several modules and the capacity in the name is the total of the "
        "kit: give the capacity of ONE module. Copy the model name exactly as the source writes it, "
        "never shorten it. 'producent' and 'nazwa' describe the item itself (e.g. the memory MODULE), "
        "not the chips on it: a module made by an unknown company with Hynix chips has an unknown "
        "manufacturer — leave it empty and mention the chips in 'uwagi'. "
        f"Write 'uwagi' in {JEZYKI_ODPOWIEDZI.get(jezyk, 'English')}: one or two sentences about "
        "doubts, conflicting sources or what the user should check on the item.")
    uzytkownik = (
        f"Category: {dane.get('kategoria', '')}\n"
        f"Manufacturer: {dane.get('producent', '') or '?'}\n"
        f"Model: {dane.get('nazwa', '') or '?'}\n"
        f"Markings and notes from the owner:\n{dane.get('oznaczenia', '') or '-'}\n\n"
        "Fields (key: name (type)):\n- producent: manufacturer (short text)\n"
        "- nazwa: model name or part number (short text)\n" + "\n".join(linie_pol) +
        "\n\nSources:\n\n" + "\n\n".join(linie_zrodel) +
        f"\n\nRemember: write 'uwagi' in {JEZYKI_ODPOWIEDZI.get(jezyk, 'English')}.")
    return [{"role": "system", "content": system}, {"role": "user", "content": uzytkownik}]


# ------------------------------------------------------------- sprawdzanie odpowiedzi
def konwertuj(opis: dict, tekst: str):
    """Tekst od modelu -> wartość pola (jak w bazie). Zgłasza ValueError."""
    from uslugi.formatowanie import tekst_na_zakres
    from uslugi.retroweb import pojemnosc
    tekst = (tekst or "").strip()
    typ = opis["typ"]
    if typ == "enum":
        for wartosc in opis.get("wartosci", []):
            if wartosc.casefold() == tekst.casefold():
                return wartosc
        raise ValueError(tekst)
    if typ == "pojemnosc":
        wynik = pojemnosc(tekst.replace("iB", "B"))
        if wynik is None:
            raise ValueError(tekst)
        return wynik
    if typ == "bool":
        mapa = {"true": True, "yes": True, "tak": True, "false": False, "no": False, "nie": False}
        if tekst.casefold() not in mapa:
            raise ValueError(tekst)
        return mapa[tekst.casefold()]
    if typ in ("int", "real", "zakres"):
        jednostka = opis.get("jednostka") or ""
        bez_jednostki = tekst
        if jednostka and tekst.casefold().endswith(jednostka.casefold()):
            bez_jednostki = tekst[:-len(jednostka)].strip()
        if typ == "int":
            return int(bez_jednostki.replace(" ", ""))
        if typ == "real":
            return float(bez_jednostki.replace(",", "."))
        wynik = tekst_na_zakres(bez_jednostki, opis.get("jednostka"))
        if wynik is None:
            raise ValueError(tekst)
        return wynik
    return tekst[:200]


def _normalizuj(tekst: str) -> str:
    tekst = unicodedata.normalize("NFKC", tekst or "").casefold()
    tekst = re.sub(r"[‐‑‒–—−]", "-", tekst).replace("|", " ")
    return re.sub(r"\s+", " ", tekst).strip()


def potwierdzony(cytat: str, zrodlo: Strona | None) -> bool:
    """Cytat (co najmniej 3 znaki) występuje w tekście źródła — po ujednoliceniu
    wielkości liter, myślników i odstępów."""
    cytat = _normalizuj(cytat)
    return zrodlo is not None and len(cytat) >= 3 and cytat in _normalizuj(zrodlo.tekst)


def _tekst_wartosci(opis: dict | None, wartosc) -> str:
    from uslugi.formatowanie import liczba_na_tekst, pojemnosc_na_tekst
    if opis is not None and opis["typ"] == "pojemnosc" and isinstance(wartosc, (int, float)):
        return pojemnosc_na_tekst(wartosc)
    return liczba_na_tekst(wartosc)


def _wartosc(kod: str, etykieta: str, opis: dict | None, surowe, zrodla: list[Strona],
             zgodnosc: dict | None = None) -> Wartosc | None:
    surowe = surowe if isinstance(surowe, dict) else {}
    tekst = str(surowe.get("wartosc") or "").strip()
    if not tekst:
        return None                                   # model nie znalazł — nie pokazujemy pustych
    numer = surowe.get("zrodlo")
    zrodlo = zrodla[numer - 1] if isinstance(numer, int) and 1 <= numer <= len(zrodla) else None
    cytat = str(surowe.get("cytat") or "").strip()[:MAKS_CYTAT]
    try:
        wartosc = konwertuj(opis, tekst) if opis is not None else tekst[:200]
        blad = None
    except ValueError:
        wartosc, blad = None, "asystent.wartosc_niezgodna"
    dopasowane, podobne = (zgodnosc or {}).get(zrodlo.adres if zrodlo else None, (PELNE, ""))
    return Wartosc(kod, etykieta, wartosc, _tekst_wartosci(opis, wartosc) if blad is None else tekst,
                   zrodlo, cytat, potwierdzony(cytat, zrodlo), blad, dopasowane, podobne)


def _nazwa_innego_produktu(nazwa_: str, oznaczenia: list[str]) -> bool:
    """Strona o module Kingstona na kościach Hynixa wymienia oznaczenie kości, ale jej
    nazwa (KVR400X64C3A/256) to nazwa INNEGO produktu. Nazwa jest „nasza”, gdy zawiera
    któreś z oznaczeń przedmiotu albo sama się w nim zawiera."""
    oznaczenia = [_normalizuj(o) for o in oznaczenia if len(o) >= 5]
    if not oznaczenia:
        return False
    nazwa_ = _normalizuj(nazwa_)
    return not any(o in nazwa_ or (len(nazwa_) >= 5 and nazwa_ in o) for o in oznaczenia)


def opracuj(odpowiedz: dict, szablon: list[dict], zrodla: list[Strona],
            oznaczenia: list[str] | None = None) -> list[Wartosc]:
    """Odpowiedź modelu -> lista sprawdzonych propozycji w kolejności formularza.
    oznaczenia: numery części przedmiotu — do sprawdzenia, czy źródło mówi o nim."""
    from i18n.tlumacz import nazwa, t
    odpowiedz = odpowiedz if isinstance(odpowiedz, dict) else {}
    zgodnosc = {z.adres: dopasowanie(z, oznaczenia or []) for z in zrodla}
    nazwa_ = _wartosc(NAZWA, t("pole.nazwa_modelu"), None, odpowiedz.get("nazwa"), zrodla, zgodnosc)
    if nazwa_ is not None and _nazwa_innego_produktu(nazwa_.tekst, oznaczenia or []):
        nazwa_.dopasowanie = INNA_NAZWA
    wynik = [_wartosc(PRODUCENT, t("pole.producent"), None, odpowiedz.get("producent"), zrodla, zgodnosc), nazwa_]
    pola = odpowiedz.get("pola") if isinstance(odpowiedz.get("pola"), dict) else {}
    for opis in szablon:
        etykieta = nazwa(opis["nazwy"]) + (f" [{opis['jednostka']}]" if opis.get("jednostka") else "")
        wynik.append(_wartosc(opis["kod"], etykieta, opis, pola.get(opis["kod"]), zrodla, zgodnosc))
    return [w for w in wynik if w is not None]


# ---------------------------------------------------------------------- całość
class Asystent:
    """llm: obiekt z czat(model, wiadomosci, schemat, anuluj) — Ollama albo zamiennik w testach;
    wyszukiwarka: obiekt z szukaj(zapytanie, ile) i pobierz(strona)."""

    def __init__(self, llm, wyszukiwarka, model: str):
        self.llm = llm
        self.wyszukiwarka = wyszukiwarka
        self.model = model

    def zaproponuj(self, szablon: list[dict], dane: dict, zapytanie_: str | None = None,
                   anuluj: threading.Event | None = None, postep=None, jezyk: str = "pl") -> Wynik:
        """Zgłasza BladNornicy albo Przerwano. postep(klucz, **pola) — kroki do paska stanu."""
        def krok(klucz: str, **pola):
            if anuluj is not None and anuluj.is_set():
                raise Przerwano()
            if postep is not None:
                postep(klucz, **pola)

        tekst_zapytania = (zapytanie_ or zapytanie(dane.get("producent", ""), dane.get("nazwa", ""),
                                                   dane.get("oznaczenia", ""))).strip()
        if not tekst_zapytania:
            raise BladNornicy("asystent.brak_opisu")
        krok("asystent.krok_szukam", zapytanie=tekst_zapytania)
        znalezione = self.wyszukiwarka.szukaj(tekst_zapytania, ILE_WYNIKOW)
        if not znalezione:
            raise BladNornicy("asystent.brak_wynikow", zapytanie=tekst_zapytania)
        zrodla = []
        for numer, strona in enumerate(znalezione[:ILE_STRON], 1):
            krok("asystent.krok_pobieram", numer=numer, ile=min(ILE_STRON, len(znalezione)), adres=strona.adres)
            zrodla.append(self.wyszukiwarka.pobierz(strona))
        krok("asystent.krok_mysle", model=self.model)
        odpowiedz = self.llm.czat(self.model, wiadomosci(szablon, dane, zrodla, jezyk), schemat(szablon), anuluj)
        krok("asystent.krok_sprawdzam")
        uwagi = str(odpowiedz.get("uwagi") or "").strip() if isinstance(odpowiedz, dict) else ""
        oznaczenia = numery(dane.get("nazwa", ""), dane.get("oznaczenia", ""))
        return Wynik(tekst_zapytania, opracuj(odpowiedz, szablon, zrodla, oznaczenia), zrodla, uwagi[:1000],
                     self.model)
