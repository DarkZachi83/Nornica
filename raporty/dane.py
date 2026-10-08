# SPDX-License-Identifier: GPL-3.0-or-later
"""Dane raportów: neutralne tabele, z których piszą wszystkie formaty.

Każda tabela powstaje w JĘZYKU RAPORTU (parametr `jezyk`), niezależnym od
języka programu — można wyeksportować angielski raport z polskiego okna.
Wartości zostają surowe (liczby jako liczby, daty jako tekst ISO), a każdy
format sam decyduje o ich zapisie: CSV z przecinkiem dziesiętnym po polsku,
XLSX z formatem liczbowym komórki, HTML jako tekst.

Dane prywatne (cena, źródło i data nabycia) trafiają do raportu tylko na
wyraźne życzenie — domyślnie raport można bezpiecznie wysłać innym.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from baza.enumy import etykieta
from baza.polaczenie import klucz_sortowania
from baza.repozytoria import egzemplarze, lokalizacje, slowniki
from baza.repozytoria.szczegoly import zlacza_egzemplarza
from i18n.tlumacz import nazwa, t
from uslugi.formatowanie import data_lokalna, liczba_na_tekst, pojemnosc_na_tekst

TEKST, LICZBA, KWOTA = "tekst", "liczba", "kwota"


@dataclass
class Kolumna:
    naglowek: str
    typ: str = TEKST
    szerokosc: int = 18          # orientacyjna szerokość w znakach (arkusze)


@dataclass
class Tabela:
    kod: str                     # stały identyfikator: egzemplarze, modele...
    nazwa: str                   # przetłumaczona nazwa (arkusz, nagłówek sekcji)
    plik: str                    # przetłumaczony fragment nazwy pliku CSV
    kolumny: list[Kolumna]
    wiersze: list[list] = field(default_factory=list)
    miniatury: list[bytes | None] = field(default_factory=list)   # tylko HTML, równoległe do wierszy


@dataclass
class Opcje:
    jezyk: str = "en"
    lokalizacja_id: int | None = None          # None = cała kolekcja
    tabele: tuple[str, ...] = ("egzemplarze", "modele", "lokalizacje", "historia")
    prywatne: bool = False
    miniatury: bool = True


# ---------------------------------------------------------------------------
# Zakres
# ---------------------------------------------------------------------------
def lokalizacje_w_zakresie(db: sqlite3.Connection, lok_id: int | None) -> list[int]:
    if lok_id is None:
        return [w[0] for w in db.execute("SELECT id FROM lokalizacja")]
    return [lok_id, *lokalizacje.potomkowie(db, lok_id)]


def egzemplarze_w_zakresie(db: sqlite3.Connection, lok_id: int | None) -> list[int]:
    """Cała kolekcja albo wszystko w lokalizacji z podlokalizacjami — razem
    z częściami zamontowanymi w środku (efektywna lokalizacja)."""
    if lok_id is None:
        return [w[0] for w in db.execute("SELECT id FROM egzemplarz")]
    lokacje = lokalizacje_w_zakresie(db, lok_id)
    znaki = ", ".join("?" * len(lokacje))
    return [w[0] for w in db.execute(
        f"SELECT egzemplarz_id FROM v_egzemplarz_lokalizacja WHERE lokalizacja_id IN ({znaki})", lokacje)]


# ---------------------------------------------------------------------------
# Opisy złożonych pól
# ---------------------------------------------------------------------------
def opis_parametrow(db: sqlite3.Connection, kat_id: int | None, z_modelu: dict, wlasne: dict, jezyk: str) -> str:
    """„Procesor: 6502C; Taktowanie procesora: 1,77 MHz” — parametry modelu
    z nadpisaniami egzemplarza, w kolejności szablonu kategorii."""
    wartosci = {**z_modelu, **wlasne}
    czesci, znane = [], set()
    for pole in slowniki.szablon(db, kat_id):
        znane.add(pole["kod"])
        if pole["kod"] not in wartosci:
            continue
        wartosc = wartosci[pole["kod"]]
        if isinstance(wartosc, bool):
            tekst = t("ogolne.tak", jezyk) if wartosc else t("ogolne.nie", jezyk)
        elif pole.get("typ") == "pojemnosc" and isinstance(wartosc, (int, float)):
            tekst = pojemnosc_na_tekst(wartosc, jezyk)
        else:
            tekst = liczba_na_tekst(wartosc, jezyk)
        if pole.get("jednostka"):
            tekst = f"{tekst} {pole['jednostka']}"
        czesci.append(f"{nazwa(pole['nazwy'], jezyk)}: {tekst}")
    czesci += [f"{kod}: {liczba_na_tekst(w, jezyk)}" for kod, w in wartosci.items() if kod not in znane]
    return "; ".join(czesci)


def opis_zlaczy(zlacza: list[dict], jezyk: str) -> str:
    """„Posiada: 2× Port joysticka (Atari DB9), 1× SCART | Wymaga: 1× ISA 16-bit”."""
    grupy = []
    for rola in ("posiada", "wymaga"):
        pozycje = [f"{z['ilosc']}× {nazwa(z['nazwy'], jezyk)}" for z in zlacza if z["rola"] == rola]
        if pozycje:
            grupy.append(f"{etykieta('model_zlacze.rola', rola, jezyk)}: {', '.join(pozycje)}")
    return " | ".join(grupy)


def _zlacza_modelu(db: sqlite3.Connection, model_id: int) -> list[dict]:
    wiersze = db.execute("SELECT z.ilosc, z.rola, t.nazwy, t.kolejnosc FROM model_zlacze z "
                         "JOIN zlacze_typ t ON t.id = z.zlacze_typ_id WHERE z.model_id = ? "
                         "ORDER BY t.kod IS NULL, t.kolejnosc, t.id", (model_id,)).fetchall()
    return [dict(w) for w in wiersze]


# ---------------------------------------------------------------------------
# Tabele
# ---------------------------------------------------------------------------
def tabela_egzemplarzy(db: sqlite3.Connection, identyfikatory: list[int], o: Opcje) -> Tabela:
    j = o.jezyk
    kolumny = [Kolumna(t("pole.kod_inwentarzowy", j), szerokosc=13), Kolumna(t("kolumna.nazwa", j), szerokosc=30),
               Kolumna(t("pole.producent", j)), Kolumna(t("pole.model", j), szerokosc=22),
               Kolumna(t("pole.numer_czesci", j), szerokosc=12), Kolumna(t("pole.kategoria", j), szerokosc=22),
               Kolumna(t("pole.status", j), szerokosc=13), Kolumna(t("pole.stan_wizualny", j), szerokosc=13),
               Kolumna(t("pole.lokalizacja", j), szerokosc=34), Kolumna(t("pole.zamontowany_w", j), szerokosc=26),
               Kolumna(t("pole.pozycja_montazu", j), szerokosc=14), Kolumna(t("pole.numer_seryjny", j), szerokosc=16),
               Kolumna(t("pole.rewizja", j), szerokosc=10), Kolumna(t("pole.ilosc", j), LICZBA, 7),
               Kolumna(t("zakladka.parametry", j), szerokosc=50), Kolumna(t("zakladka.zlacza", j), szerokosc=40),
               Kolumna(t("pole.uwagi", j), szerokosc=40), Kolumna(t("kolumna.zmieniono", j), szerokosc=16)]
    if o.prywatne:
        kolumny += [Kolumna(t("pole.data_nabycia", j), szerokosc=12), Kolumna(t("pole.zrodlo_nabycia", j), szerokosc=20),
                    Kolumna(t("pole.cena", j), KWOTA, 11), Kolumna(t("pole.waluta", j), szerokosc=7)]
    tabela = Tabela("egzemplarze", t("eksport.tabela.egzemplarze", j), t("eksport.plik.egzemplarze", j), kolumny)
    sciezki = lokalizacje.sciezki(db)
    wybrane = set(identyfikatory)
    wiersze = [e for e in egzemplarze.lista(db) if e["id"] in wybrane]
    wiersze.sort(key=lambda e: e["kod_inwentarzowy"] or "")
    po_id = {e["id"]: e for e in egzemplarze.lista(db)}
    from uslugi import pliki
    for e in wiersze:
        miejsce = egzemplarze.efektywna_lokalizacja(db, e["id"])
        rodzic = po_id.get(e["rodzic_id"])
        wiersz = [
            e["kod_inwentarzowy"], egzemplarze.nazwa_wyswietlana(e), e["producent"] or "", e["model_nazwa"] or "",
            e["numer_czesci"] or "", nazwa(e["kategoria_nazwy"], j), nazwa(e["status_nazwy"], j),
            etykieta("egzemplarz.stan_wizualny", e["stan_wizualny"], j) if e["stan_wizualny"] else "",
            sciezki.get(miejsce, "") if miejsce else t("lokalizacja.brak", j),
            f"{egzemplarze.nazwa_wyswietlana(rodzic)} ({rodzic['kod_inwentarzowy']})" if rodzic else "",
            e["pozycja_montazu"] or "", e["numer_seryjny"] or "", e["rewizja"] or "", e["ilosc"],
            opis_parametrow(db, e["kat_id"], json.loads(e["model_atrybuty"] or "{}"),
                            json.loads(e["atrybuty"] or "{}"), j),
            opis_zlaczy(zlacza_egzemplarza(db, e["id"]), j), e["uwagi"] or "", data_lokalna(e["zmieniono"], j),
        ]
        if o.prywatne:
            cena = None
            if e["cena_minor"] is not None:
                cena = Decimal(e["cena_minor"]).scaleb(-slowniki.miejsca_dziesietne(db, e["waluta_kod"]))
            wiersz += [e["data_nabycia"] or "", e["zrodlo_nabycia"] or "", cena, e["waluta_kod"] or ""]
        tabela.wiersze.append(wiersz)
        if o.miniatury:
            zdjecie = pliki.zdjecie_glowne(db, e["id"])
            tabela.miniatury.append(zdjecie["miniatura"] if zdjecie is not None else None)
    return tabela


def tabela_modeli(db: sqlite3.Connection, identyfikatory_egz: list[int] | None, o: Opcje) -> Tabela:
    """Modele użyte przez egzemplarze w zakresie (None = wszystkie modele katalogu)."""
    j = o.jezyk
    tabela = Tabela("modele", t("eksport.tabela.modele", j), t("eksport.plik.modele", j), [
        Kolumna(t("pole.producent", j)), Kolumna(t("pole.nazwa_modelu", j), szerokosc=24),
        Kolumna(t("pole.numer_czesci", j), szerokosc=12), Kolumna(t("pole.kategoria", j), szerokosc=22),
        Kolumna(t("pole.produkcja", j), szerokosc=11), Kolumna(t("kolumna.egzemplarze", j), LICZBA, 10),
        Kolumna(t("zakladka.parametry", j), szerokosc=50), Kolumna(t("zakladka.zlacza", j), szerokosc=40),
        Kolumna(t("pole.zrodlo_url", j), szerokosc=30), Kolumna(t("pole.opis", j), szerokosc=60)])
    wiersze = db.execute(
        "SELECT m.*, p.nazwa AS producent, k.nazwy AS kategoria_nazwy, "
        "(SELECT COUNT(*) FROM egzemplarz e WHERE e.model_id = m.id) AS liczba "
        "FROM model m LEFT JOIN producent p ON p.id = m.producent_id "
        "JOIN kategoria k ON k.id = m.kategoria_id").fetchall()
    if identyfikatory_egz is not None:
        znaki = ", ".join("?" * len(identyfikatory_egz)) or "NULL"
        uzyte = {w[0] for w in db.execute(f"SELECT DISTINCT model_id FROM egzemplarz WHERE id IN ({znaki})",
                                          identyfikatory_egz)}
        wiersze = [m for m in wiersze if m["id"] in uzyte]
    for m in sorted(wiersze, key=lambda m: (klucz_sortowania(m["producent"] or ""), klucz_sortowania(m["nazwa"]))):
        lata = ""
        if m["rok_od"] or m["rok_do"]:
            lata = f"{m['rok_od'] or '?'}–{m['rok_do'] or '?'}" if m["rok_od"] != m["rok_do"] else str(m["rok_od"])
        tabela.wiersze.append([
            m["producent"] or "", m["nazwa"], m["numer_czesci"] or "", nazwa(m["kategoria_nazwy"], j), lata,
            m["liczba"], opis_parametrow(db, m["kategoria_id"], json.loads(m["atrybuty"] or "{}"), {}, j),
            opis_zlaczy(_zlacza_modelu(db, m["id"]), j), m["zrodlo_url"] or "", m["opis"] or ""])
    return tabela


def tabela_lokalizacji(db: sqlite3.Connection, lok_id: int | None, o: Opcje) -> Tabela:
    j = o.jezyk
    tabela = Tabela("lokalizacje", t("eksport.tabela.lokalizacje", j), t("eksport.plik.lokalizacje", j), [
        Kolumna(t("pole.kod_etykiety", j), szerokosc=11), Kolumna(t("eksport.kolumna.sciezka", j), szerokosc=40),
        Kolumna(t("pole.typ", j), szerokosc=12), Kolumna(t("pole.liczba_egzemplarzy", j), LICZBA, 12),
        Kolumna(t("pole.uwagi", j), szerokosc=40)])
    sciezki = lokalizacje.sciezki(db)
    for l_id in sorted(lokalizacje_w_zakresie(db, lok_id), key=lambda i: klucz_sortowania(sciezki.get(i, ""))):
        l = lokalizacje.pobierz(db, l_id)
        liczba = db.execute("SELECT COUNT(*) FROM egzemplarz WHERE lokalizacja_id = ?", (l_id,)).fetchone()[0]
        tabela.wiersze.append([l["kod_etykiety"] or "", sciezki.get(l_id, l["nazwa"]),
                               etykieta("lokalizacja.typ", l["typ"], j) if l["typ"] else "", liczba, l["uwagi"] or ""])
    return tabela


def tabela_historii(db: sqlite3.Connection, identyfikatory_egz: list[int], o: Opcje) -> Tabela:
    j = o.jezyk
    tabela = Tabela("historia", t("eksport.tabela.historia", j), t("eksport.plik.historia", j), [
        Kolumna(t("kolumna.data", j), szerokosc=11), Kolumna(t("pole.kod_inwentarzowy", j), szerokosc=13),
        Kolumna(t("kolumna.nazwa", j), szerokosc=28), Kolumna(t("kolumna.typ", j), szerokosc=13),
        Kolumna(t("kolumna.wynik", j), szerokosc=10), Kolumna(t("kolumna.opis", j), szerokosc=60)])
    if not identyfikatory_egz:
        return tabela
    znaki = ", ".join("?" * len(identyfikatory_egz))
    for z in db.execute(f"SELECT * FROM zdarzenie WHERE egzemplarz_id IN ({znaki}) ORDER BY data DESC, id DESC",
                        identyfikatory_egz):
        e = egzemplarze.pobierz(db, z["egzemplarz_id"])
        rodzaj = (etykieta("zdarzenie.podtyp", z["podtyp"], j) if z["podtyp"]
                  else etykieta("zdarzenie.typ", z["typ"], j))
        tabela.wiersze.append([z["data"], e["kod_inwentarzowy"], egzemplarze.nazwa_wyswietlana(e), rodzaj,
                               etykieta("zdarzenie.wynik", z["wynik"], j) if z["wynik"] else "", z["opis"] or ""])
    return tabela


def zbierz(db: sqlite3.Connection, o: Opcje) -> list[Tabela]:
    egz = egzemplarze_w_zakresie(db, o.lokalizacja_id)
    budowniczy = {
        "egzemplarze": lambda: tabela_egzemplarzy(db, egz, o),
        "modele": lambda: tabela_modeli(db, None if o.lokalizacja_id is None else egz, o),
        "lokalizacje": lambda: tabela_lokalizacji(db, o.lokalizacja_id, o),
        "historia": lambda: tabela_historii(db, egz, o),
    }
    return [budowniczy[kod]() for kod in budowniczy if kod in o.tabele]


def podsumowanie(db: sqlite3.Connection, o: Opcje) -> dict:
    """Liczby do nagłówka raportu HTML: egzemplarze wg statusu i kategorii,
    wartość kolekcji wg walut (tylko z danymi prywatnymi)."""
    egz = set(egzemplarze_w_zakresie(db, o.lokalizacja_id))
    wiersze = [e for e in egzemplarze.lista(db) if e["id"] in egz]
    wynik = {"egzemplarze": len(wiersze), "wygenerowano": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "statusy": {}, "kategorie": {}, "wartosc": {}}
    for e in wiersze:
        status = nazwa(e["status_nazwy"], o.jezyk)
        kategoria = nazwa(e["kategoria_nazwy"], o.jezyk)
        wynik["statusy"][status] = wynik["statusy"].get(status, 0) + e["ilosc"]
        wynik["kategorie"][kategoria] = wynik["kategorie"].get(kategoria, 0) + e["ilosc"]
        if o.prywatne and e["cena_minor"] is not None:
            kwota = Decimal(e["cena_minor"]).scaleb(-slowniki.miejsca_dziesietne(db, e["waluta_kod"]))
            wynik["wartosc"][e["waluta_kod"]] = wynik["wartosc"].get(e["waluta_kod"], Decimal(0)) + kwota
    return wynik
