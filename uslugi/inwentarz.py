# SPDX-License-Identifier: GPL-3.0-or-later
"""Operacje na kolekcji z regułami biznesowymi.

Każda operacja zmieniająca dane działa w jednej transakcji. Błędy zgłaszane
użytkownikowi to BladNornicy z kluczem tłumaczenia. Puste pola formularza
zamieniane są na NULL, żeby „brak” zawsze znaczył to samo.
"""
from __future__ import annotations

import json
import sqlite3

from baza.polaczenie import transakcja
from baza.repozytoria import egzemplarze, lokalizacje, modele, slowniki, zlacza
from uslugi.formatowanie import sprawdz_date
from baza.repozytoria.kody import nastepny_kod
from wyjatki import BladNornicy


def _normalizuj(dane: dict) -> dict:
    wynik = {}
    for klucz, wartosc in dane.items():
        if isinstance(wartosc, str):
            wartosc = wartosc.strip() or None
        wynik[klucz] = wartosc
    return wynik


def _json_lub_none(slownik: dict | None) -> str | None:
    return json.dumps(slownik, ensure_ascii=False, sort_keys=True) if slownik else None


# ---------------------------------------------------------------------------
# Egzemplarze
# ---------------------------------------------------------------------------
def zapisz_egzemplarz(db: sqlite3.Connection, dane: dict, egz_id: int | None = None) -> int:
    """Dodaje (egz_id=None) lub aktualizuje egzemplarz. Zwraca jego id."""
    d = _normalizuj(dane)
    zlacza_efektywne = d.pop("zlacza", None)   # stan po edycji; zapisywane są tylko różnice od modelu
    if d.get("model_id"):
        d["kategoria_id"] = None            # kategoria pochodzi z modelu
    elif not d.get("kategoria_id"):
        raise BladNornicy("blad.wybierz_kategorie")
    if not d.get("model_id") and not d.get("nazwa_wlasna"):
        raise BladNornicy("blad.egzemplarz_model_lub_nazwa")
    if not d.get("status_id"):
        raise BladNornicy("blad.wybierz_status")
    d["ilosc"] = d.get("ilosc") or 1
    if d.get("rodzic_id"):
        d["lokalizacja_id"] = None          # zamontowany dziedziczy lokalizację
    else:
        d["pozycja_montazu"] = None
    if "atrybuty" in d and not isinstance(d["atrybuty"], (str, type(None))):
        d["atrybuty"] = _json_lub_none(d["atrybuty"])

    with transakcja(db):
        if d.get("rodzic_id"):
            rodzic = db.execute("SELECT ilosc FROM egzemplarz WHERE id = ?", (d["rodzic_id"],)).fetchone()
            if rodzic is None:
                raise BladNornicy("blad.klucz_obcy")
            if egz_id is not None and (d["rodzic_id"] == egz_id
                                       or d["rodzic_id"] in egzemplarze.potomkowie(db, egz_id)):
                raise BladNornicy("blad.cykl_montazu")
        if egz_id is None:
            if not d.get("kod_inwentarzowy"):
                d["kod_inwentarzowy"] = nastepny_kod(db, "egzemplarz")
            egz_id = egzemplarze.wstaw(db, d)
        else:
            if not d.get("kod_inwentarzowy"):
                d.pop("kod_inwentarzowy", None)  # pusty kod przy edycji = zostaw dotychczasowy
            egzemplarze.aktualizuj(db, egz_id, d)
        if zlacza_efektywne is not None:
            z_modelu = zlacza.modelu(db, d.get("model_id"))
            zlacza.zapisz_nadpisania(db, egz_id, zlacza.roznice(zlacza_efektywne, z_modelu))
        return egz_id


def usun_egzemplarz(db: sqlite3.Connection, egz_id: int) -> int:
    """Usuwa egzemplarz. Zamontowane w nim części zostają zdemontowane
    i odłożone tam, gdzie stał egzemplarz. Zwraca liczbę zdemontowanych części."""
    with transakcja(db):
        miejsce = egzemplarze.efektywna_lokalizacja(db, egz_id)
        zdemontowane = db.execute(
            "UPDATE egzemplarz SET rodzic_id = NULL, pozycja_montazu = NULL, lokalizacja_id = ? "
            "WHERE rodzic_id = ?", (miejsce, egz_id)).rowcount
        db.execute("DELETE FROM egzemplarz WHERE id = ?", (egz_id,))
    return zdemontowane


def wydziel_z_partii(db: sqlite3.Connection, egz_id: int) -> int:
    """Odejmuje jedną sztukę od partii i tworzy z niej osobny egzemplarz
    z własnym kodem. Zwraca id nowej sztuki."""
    with transakcja(db):
        partia = db.execute("SELECT * FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()
        if partia is None or partia["ilosc"] <= 1:
            raise BladNornicy("blad.nie_partia")
        db.execute("UPDATE egzemplarz SET ilosc = ilosc - 1 WHERE id = ?", (egz_id,))
        kopia = {k: partia[k] for k in ("model_id", "kategoria_id", "nazwa_wlasna", "rewizja",
                                        "status_id", "stan_wizualny", "lokalizacja_id", "atrybuty",
                                        "data_nabycia", "zrodlo_nabycia")}
        kopia["ilosc"] = 1
        kopia["kod_inwentarzowy"] = nastepny_kod(db, "egzemplarz")
        # Cena dotyczyła całej partii — nie kopiujemy jej na pojedynczą sztukę.
        return egzemplarze.wstaw(db, kopia)


# ---------------------------------------------------------------------------
# Lokalizacje
# ---------------------------------------------------------------------------
def zapisz_lokalizacje(db: sqlite3.Connection, dane: dict, lok_id: int | None = None) -> int:
    d = _normalizuj(dane)
    if not d.get("nazwa"):
        raise BladNornicy("blad.wymagana_nazwa")
    with transakcja(db):
        if lok_id is not None and d.get("rodzic_id") is not None and (
                d["rodzic_id"] == lok_id or d["rodzic_id"] in lokalizacje.potomkowie(db, lok_id)):
            raise BladNornicy("blad.cykl_drzewa")
        if lok_id is None:
            if not d.get("kod_etykiety"):
                d["kod_etykiety"] = nastepny_kod(db, "lokalizacja")
            return lokalizacje.wstaw(db, d)
        if not d.get("kod_etykiety"):
            d.pop("kod_etykiety", None)
        lokalizacje.aktualizuj(db, lok_id, d)
        return lok_id


def usun_lokalizacje(db: sqlite3.Connection, lok_id: int, przenies_zawartosc: bool = False) -> None:
    """Usuwa lokalizację. Z przeniesieniem: podlokalizacje i egzemplarze trafiają
    do lokalizacji nadrzędnej (albo stają się „bez lokalizacji”)."""
    with transakcja(db):
        wiersz = lokalizacje.pobierz(db, lok_id)
        if wiersz is None:
            return
        if przenies_zawartosc:
            db.execute("UPDATE lokalizacja SET rodzic_id = ? WHERE rodzic_id = ?",
                       (wiersz["rodzic_id"], lok_id))
            db.execute("UPDATE egzemplarz SET lokalizacja_id = ? WHERE lokalizacja_id = ?",
                       (wiersz["rodzic_id"], lok_id))
        db.execute("DELETE FROM lokalizacja WHERE id = ?", (lok_id,))


# ---------------------------------------------------------------------------
# Modele
# ---------------------------------------------------------------------------
def zapisz_model(db: sqlite3.Connection, dane: dict, model_id: int | None = None) -> int:
    """`dane["producent"]` to nazwa; nowy producent powstaje automatycznie."""
    d = _normalizuj(dane)
    zlacza_modelu = d.pop("zlacza", None)
    if not d.get("nazwa"):
        raise BladNornicy("blad.wymagana_nazwa")
    if not d.get("kategoria_id"):
        raise BladNornicy("blad.wybierz_kategorie")
    if "atrybuty" in d and not isinstance(d["atrybuty"], (str, type(None))):
        d["atrybuty"] = _json_lub_none(d["atrybuty"])
    with transakcja(db):
        d["producent_id"] = slowniki.producent_id(db, d.pop("producent", None), utworz=True)
        if model_id is None:
            model_id = modele.wstaw(db, d)
        else:
            poprzednia = db.execute("SELECT kategoria_id FROM model WHERE id = ?", (model_id,)).fetchone()[0]
            modele.aktualizuj(db, model_id, d)
            if poprzednia != d["kategoria_id"]:
                # zmiana kategorii w formularzu modelu: parametry egzemplarzy porządkowane
                # tak samo jak przy „Przenieś do innej kategorii”
                from uslugi.przeniesienie import po_zmianie_kategorii_modelu
                po_zmianie_kategorii_modelu(db, model_id, poprzednia, d["kategoria_id"])
        if zlacza_modelu is not None:
            zlacza.zapisz_modelu(db, model_id, zlacza_modelu)
        return model_id


def usun_model(db: sqlite3.Connection, model_id: int) -> None:
    """Usuwa model. Model z egzemplarzami jest chroniony przez ON DELETE RESTRICT;
    złącza i powiązania zasobów modelu znikają razem z nim (CASCADE)."""
    with transakcja(db):
        db.execute("DELETE FROM model WHERE id = ?", (model_id,))


# ---------------------------------------------------------------------------
# Historia: testy i naprawy
# ---------------------------------------------------------------------------
def zapisz_zdarzenie(db: sqlite3.Connection, dane: dict, zdarzenie_id: int | None = None,
                     nowy_status_id: int | None = None) -> int:
    """Zapisuje test lub naprawę; opcjonalnie w tej samej transakcji zmienia
    status egzemplarza (np. test nieudany -> „Uszkodzony”)."""
    d = _normalizuj(dane)
    if d.get("typ") not in ("test", "naprawa"):
        raise BladNornicy("blad.zdarzenie_podtyp")
    if d["typ"] == "test":
        d["podtyp"] = None
    elif not d.get("podtyp"):
        d["podtyp"] = "naprawa"
    try:
        d["data"] = sprawdz_date(d.get("data"))
    except ValueError:
        raise BladNornicy("blad.zla_data") from None
    if not d["data"]:
        raise BladNornicy("blad.zla_data")
    pola = ("egzemplarz_id", "data", "typ", "podtyp", "wynik", "opis")
    with transakcja(db):
        if zdarzenie_id is None:
            kolumny = [k for k in pola if k in d]
            zdarzenie_id = db.execute(
                f"INSERT INTO zdarzenie ({', '.join(kolumny)}) VALUES ({', '.join('?' * len(kolumny))})",
                [d[k] for k in kolumny]).lastrowid
        else:
            kolumny = [k for k in pola if k in d and k != "egzemplarz_id"]
            db.execute(f"UPDATE zdarzenie SET {', '.join(k + ' = ?' for k in kolumny)} WHERE id = ?",
                       [d[k] for k in kolumny] + [zdarzenie_id])
        if nowy_status_id:
            egz = db.execute("SELECT egzemplarz_id FROM zdarzenie WHERE id = ?", (zdarzenie_id,)).fetchone()[0]
            db.execute("UPDATE egzemplarz SET status_id = ? WHERE id = ?", (nowy_status_id, egz))
    return zdarzenie_id


def usun_zdarzenie(db: sqlite3.Connection, zdarzenie_id: int) -> None:
    with transakcja(db):
        db.execute("DELETE FROM zdarzenie WHERE id = ?", (zdarzenie_id,))


# ---------------------------------------------------------------------------
# Typy złączy dopisywane przez użytkownika
# ---------------------------------------------------------------------------
def _sprawdz_typ_zlacza(db: sqlite3.Connection, rodzaj: str, nazwy: dict,
                        pomin_id: int | None = None) -> dict:
    nazwy = {jezyk: tekst.strip() for jezyk, tekst in nazwy.items() if tekst and tekst.strip()}
    if not nazwy:
        raise BladNornicy("blad.wymagana_nazwa")
    if rodzaj not in ("port", "slot", "gniazdo", "interfejs"):
        raise BladNornicy("blad.wybierz_rodzaj")
    nowe = {tekst.casefold() for tekst in nazwy.values()}
    for wiersz in db.execute("SELECT id, nazwy FROM zlacze_typ WHERE rodzaj = ?", (rodzaj,)):
        if wiersz[0] == pomin_id:
            continue
        istniejace = {tekst.casefold() for tekst in json.loads(wiersz[1]).values() if tekst}
        if nowe & istniejace:
            raise BladNornicy("blad.duplikat")
    return nazwy


def _typ_wlasny(db: sqlite3.Connection, typ_id: int) -> sqlite3.Row:
    """Typ dopisany przez użytkownika (bez kodu). Typów startowych nie edytujemy:
    program uzupełnia je przy każdym starcie i tłumaczy w obu językach."""
    wiersz = db.execute("SELECT * FROM zlacze_typ WHERE id = ?", (typ_id,)).fetchone()
    if wiersz is None:
        raise BladNornicy("blad.klucz_obcy")
    if wiersz["kod"] is not None:
        raise BladNornicy("blad.typ_wbudowany")
    return wiersz


def dodaj_typ_zlacza(db: sqlite3.Connection, rodzaj: str, nazwy: dict) -> int:
    """Dodaje własny typ złącza. Wystarczy nazwa w jednym języku — drugi język
    pokaże tę samą (cofnięcie w i18n.tlumacz.nazwa). Typ o tej samej nazwie
    i rodzaju już istniejący zgłasza blad.duplikat (bez względu na wielkość liter)."""
    with transakcja(db):
        nazwy = _sprawdz_typ_zlacza(db, rodzaj, nazwy)
        kolejnosc = db.execute("SELECT coalesce(MAX(kolejnosc), 0) + 1 FROM zlacze_typ").fetchone()[0]
        return db.execute("INSERT INTO zlacze_typ (rodzaj, nazwy, kolejnosc) VALUES (?, ?, ?)",
                          (rodzaj, json.dumps(nazwy, ensure_ascii=False), kolejnosc)).lastrowid


def zapisz_typ_zlacza(db: sqlite3.Connection, typ_id: int, rodzaj: str, nazwy: dict) -> None:
    """Poprawka własnego typu (np. literówka w nazwie). Złącza już opisane tym
    typem pokażą poprawioną nazwę — przechowują odwołanie, nie kopię nazwy."""
    with transakcja(db):
        _typ_wlasny(db, typ_id)
        nazwy = _sprawdz_typ_zlacza(db, rodzaj, nazwy, pomin_id=typ_id)
        db.execute("UPDATE zlacze_typ SET rodzaj = ?, nazwy = ? WHERE id = ?",
                   (rodzaj, json.dumps(nazwy, ensure_ascii=False), typ_id))


def usun_typ_zlacza(db: sqlite3.Connection, typ_id: int) -> None:
    """Usuwa własny typ. Typ użyty w modelu lub egzemplarzu jest chroniony —
    komunikat mówi, ile razy jest użyty."""
    from baza.zaleznosci import opis, zaleznosci
    with transakcja(db):
        _typ_wlasny(db, typ_id)
        blokujace, _ = zaleznosci(db, "zlacze_typ", typ_id)
        if blokujace:
            raise BladNornicy("blad.usuwanie_zablokowane", lista=opis(blokujace))
        db.execute("DELETE FROM zlacze_typ WHERE id = ?", (typ_id,))
