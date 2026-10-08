# SPDX-License-Identifier: GPL-3.0-or-later
"""Edycja słowników: własne kategorie, statusy i pola parametrów.

Zasady (te same co dla własnych typów złączy):
  * Wpisy WBUDOWANE (z kodem) są nienaruszalne — program uzupełnia je przy
    każdym starcie i tłumaczy na oba języki. Zmieniać i usuwać można tylko
    wpisy użytkownika (kategoria/status bez kodu, pole z "wlasne": true).
  * Własne pola można dodać do KAŻDEJ kategorii, także wbudowanej.
    Kategorie podrzędne dziedziczą pola nadrzędnych (slowniki.szablon).
  * Usuwanie jest chronione zależnościami. Usunięcie pola z wartościami
    usuwa też te wartości — GUI najpierw pokazuje, ile ich jest.
  * Zmiana typu pola tylko, gdy pole nie ma jeszcze wartości.
  * Do listy wyboru pola WBUDOWANEGO można dopisać własne wartości (np. SECAM
    do normy TV). Trzymane osobno ("wartosci_wlasne"), żeby aktualizacja listy
    wbudowanej ich nie nadpisała; repozytorium łączy obie listy przy odczycie.

Bez zmian w schemacie bazy: kategoria/status z kod = NULL to wpis
użytkownika, a pola mieszkają w JSON szablon_atrybutow kategorii.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata

from baza.polaczenie import transakcja
from baza.repozytoria import slowniki as repo
from baza.zaleznosci import opis, zaleznosci
from wyjatki import BladNornicy

TYPY_POL = ("text", "int", "real", "bool", "enum", "pojemnosc")
RODZAJE = ("komputer_fabryczny", "skladak", "czesc", "akcesorium")


# ---------------------------------------------------------------------------
# Wspólne
# ---------------------------------------------------------------------------
def _nazwy(nazwy: dict) -> dict:
    nazwy = {j: (t or "").strip() for j, t in (nazwy or {}).items() if (t or "").strip()}
    if not nazwy:
        raise BladNornicy("blad.wymagana_nazwa")
    return nazwy


def _zajete(istniejace: list[dict], nazwy: dict) -> bool:
    """Ta sama nazwa (bez względu na wielkość liter) w którymkolwiek języku."""
    nowe = {t.casefold() for t in nazwy.values()}
    return any(nowe & {t.casefold() for t in n.values() if t} for n in istniejace)


def _json(dane) -> str:
    return json.dumps(dane, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Kategorie
# ---------------------------------------------------------------------------
def _kategoria_wlasna(db: sqlite3.Connection, kat_id: int) -> sqlite3.Row:
    wiersz = repo.kategoria(db, kat_id)
    if wiersz is None:
        raise BladNornicy("blad.klucz_obcy")
    if wiersz["kod"] is not None:
        raise BladNornicy("blad.slownik_wbudowany")
    return wiersz


def zapisz_kategorie(db: sqlite3.Connection, dane: dict, kat_id: int | None = None) -> int:
    """dane: nazwy {pl, en}, rodzic_id (None = kategoria główna), rodzaj (tylko dla
    głównej — podkategoria bierze rodzaj od rodzica)."""
    with transakcja(db):
        nazwy = _nazwy(dane.get("nazwy"))
        rodzic_id = dane.get("rodzic_id") or None
        if kat_id is not None:
            _kategoria_wlasna(db, kat_id)
            if rodzic_id is not None and (rodzic_id == kat_id or kat_id in repo.lancuch_kategorii(db, rodzic_id)):
                raise BladNornicy("blad.kategoria_cykl")      # kategoria nie może trafić do własnego wnętrza
        if rodzic_id is not None:
            rodzic = repo.kategoria(db, rodzic_id)
            if rodzic is None:
                raise BladNornicy("blad.klucz_obcy")
            rodzaj = rodzic["rodzaj"]
        else:
            rodzaj = dane.get("rodzaj")
            if rodzaj not in RODZAJE:
                raise BladNornicy("blad.wybierz_rodzaj")
        rodzenstwo = [json.loads(w["nazwy"]) for w in db.execute(
            "SELECT id, nazwy FROM kategoria WHERE rodzic_id IS ? AND id IS NOT ?", (rodzic_id, kat_id))]
        if _zajete(rodzenstwo, nazwy):
            raise BladNornicy("blad.duplikat")
        if kat_id is None:
            kolejnosc = db.execute("SELECT coalesce(MAX(kolejnosc), 0) + 1 FROM kategoria").fetchone()[0]
            return db.execute("INSERT INTO kategoria (rodzic_id, rodzaj, nazwy, szablon_atrybutow, kolejnosc) "
                              "VALUES (?, ?, ?, '[]', ?)", (rodzic_id, rodzaj, _json(nazwy), kolejnosc)).lastrowid
        db.execute("UPDATE kategoria SET rodzic_id = ?, rodzaj = ?, nazwy = ? WHERE id = ?",
                   (rodzic_id, rodzaj, _json(nazwy), kat_id))
        # podkategorie idą za rodzajem rodzica
        for potomek in _potomkowie(db, kat_id):
            db.execute("UPDATE kategoria SET rodzaj = ? WHERE id = ?", (rodzaj, potomek))
        return kat_id


def _potomkowie(db: sqlite3.Connection, kat_id: int) -> list[int]:
    wynik, kolejka = [], [kat_id]
    while kolejka:
        dzieci = [w[0] for w in db.execute("SELECT id FROM kategoria WHERE rodzic_id = ?", (kolejka.pop(),))]
        wynik += dzieci
        kolejka += dzieci
    return wynik


def zaleznosci_kategorii(db: sqlite3.Connection, kat_id: int) -> tuple[dict, dict]:
    return zaleznosci(db, "kategoria", kat_id)


def usun_kategorie(db: sqlite3.Connection, kat_id: int) -> None:
    """Tylko pusta własna kategoria: bez modeli, egzemplarzy i podkategorii.
    Zasoby podpięte do kategorii (poradniki) zostają odpięte."""
    with transakcja(db):
        _kategoria_wlasna(db, kat_id)
        blokujace, _ = zaleznosci(db, "kategoria", kat_id)
        if blokujace:
            raise BladNornicy("blad.usuwanie_zablokowane", lista=opis(blokujace))
        db.execute("DELETE FROM kategoria WHERE id = ?", (kat_id,))


# ---------------------------------------------------------------------------
# Statusy
# ---------------------------------------------------------------------------
def zapisz_status(db: sqlite3.Connection, nazwy: dict, status_id: int | None = None) -> int:
    with transakcja(db):
        nazwy = _nazwy(nazwy)
        if status_id is not None:
            wiersz = db.execute("SELECT kod FROM status WHERE id = ?", (status_id,)).fetchone()
            if wiersz is None:
                raise BladNornicy("blad.klucz_obcy")
            if wiersz["kod"] is not None:
                raise BladNornicy("blad.slownik_wbudowany")
        inne = [json.loads(w["nazwy"]) for w in db.execute("SELECT nazwy FROM status WHERE id IS NOT ?", (status_id,))]
        if _zajete(inne, nazwy):
            raise BladNornicy("blad.duplikat")
        if status_id is None:
            kolejnosc = db.execute("SELECT coalesce(MAX(kolejnosc), 0) + 1 FROM status").fetchone()[0]
            return db.execute("INSERT INTO status (nazwy, kolejnosc) VALUES (?, ?)",
                              (_json(nazwy), kolejnosc)).lastrowid
        db.execute("UPDATE status SET nazwy = ? WHERE id = ?", (_json(nazwy), status_id))
        return status_id


def usun_status(db: sqlite3.Connection, status_id: int) -> None:
    with transakcja(db):
        wiersz = db.execute("SELECT kod FROM status WHERE id = ?", (status_id,)).fetchone()
        if wiersz is None:
            raise BladNornicy("blad.klucz_obcy")
        if wiersz["kod"] is not None:
            raise BladNornicy("blad.slownik_wbudowany")
        blokujace, _ = zaleznosci(db, "status", status_id)
        if blokujace:
            raise BladNornicy("blad.usuwanie_zablokowane", lista=opis(blokujace))
        db.execute("DELETE FROM status WHERE id = ?", (status_id,))


# ---------------------------------------------------------------------------
# Pola parametrów
# ---------------------------------------------------------------------------
def _wlasny_szablon(db: sqlite3.Connection, kat_id: int) -> list[dict]:
    wiersz = repo.kategoria(db, kat_id)
    if wiersz is None:
        raise BladNornicy("blad.klucz_obcy")
    return json.loads(wiersz["szablon_atrybutow"] or "[]")


def _zapisz_szablon(db: sqlite3.Connection, kat_id: int, szablon: list[dict]) -> None:
    db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?", (_json(szablon), kat_id))


def _kod_pola(nazwy: dict, zajete: set[str]) -> str:
    """„Region” -> w_region; „Pamięć ROM” -> w_pamiec_rom. Przedrostek w_ odróżnia
    pola użytkownika od wbudowanych i chroni przed zderzeniem z przyszłymi polami startowymi."""
    tekst = next(iter(nazwy.values()))
    tekst = unicodedata.normalize("NFKD", tekst.replace("ł", "l").replace("Ł", "L"))
    tekst = "".join(z for z in tekst if not unicodedata.combining(z)).casefold()
    baza = "w_" + (re.sub(r"[^a-z0-9]+", "_", tekst).strip("_")[:30] or "pole")
    kod, numer = baza, 2
    while kod in zajete:
        kod, numer = f"{baza}_{numer}", numer + 1
    return kod


def _pole_z_danych(dane: dict) -> dict:
    nazwy = _nazwy(dane.get("nazwy"))
    typ = dane.get("typ")
    if typ not in TYPY_POL:
        raise BladNornicy("blad.wybierz_typ_pola")
    pole = {"typ": typ, "nazwy": nazwy, "wlasne": True}
    jednostka = (dane.get("jednostka") or "").strip()
    if jednostka and typ in ("int", "real"):
        pole["jednostka"] = jednostka[:12]
    if typ == "enum":
        wartosci = []
        for w in dane.get("wartosci") or []:
            w = (w or "").strip()
            if w and w.casefold() not in {x.casefold() for x in wartosci}:
                wartosci.append(w)
        if not wartosci:
            raise BladNornicy("blad.lista_wartosci")
        pole["wartosci"] = wartosci
    return pole


def _wpisy_kategorii(db: sqlite3.Connection, kat_id: int):
    """(tabela, id, atrybuty) modeli i egzemplarzy bez modelu z kategorii i jej podkategorii."""
    kategorie = [kat_id, *_potomkowie(db, kat_id)]
    znaki = ", ".join("?" * len(kategorie))
    for tabela, warunek, list_ in (("model", f"kategoria_id IN ({znaki})", 1),
                                   ("egzemplarz", f"model_id IN (SELECT id FROM model WHERE kategoria_id IN ({znaki})) "
                                                  f"OR kategoria_id IN ({znaki})", 2)):
        argumenty = kategorie * list_
        for w in db.execute(f"SELECT id, atrybuty FROM {tabela} WHERE atrybuty IS NOT NULL AND ({warunek})",
                            argumenty):
            yield tabela, w["id"], json.loads(w["atrybuty"])


def uzycie_pola(db: sqlite3.Connection, kat_id: int, kod: str) -> dict:
    """{"model": n, "egzemplarz": n} — ile wpisów ma wartość tego pola."""
    wynik = {"model": 0, "egzemplarz": 0}
    for tabela, _id, atrybuty in _wpisy_kategorii(db, kat_id):
        if kod in atrybuty:
            wynik[tabela] += 1
    return wynik


def _pole_wlasne(szablon: list[dict], kod: str) -> int:
    i = next((i for i, p in enumerate(szablon) if p["kod"] == kod), None)
    if i is None:
        raise BladNornicy("blad.slownik_pole_dziedziczone")   # pole kategorii nadrzędnej — edycja tam
    if not szablon[i].get("wlasne"):
        raise BladNornicy("blad.slownik_wbudowany")
    return i


def dodaj_pole(db: sqlite3.Connection, kat_id: int, dane: dict) -> str:
    with transakcja(db):
        szablon = _wlasny_szablon(db, kat_id)
        pole = _pole_z_danych(dane)
        # nazwa nie może dublować pola widocznego w tej kategorii (także odziedziczonego)
        widoczne = repo.szablon(db, kat_id)
        if _zajete([p["nazwy"] for p in widoczne], pole["nazwy"]):
            raise BladNornicy("blad.duplikat")
        zajete = {p["kod"] for p in widoczne}
        for potomek in _potomkowie(db, kat_id):                # nie zasłaniać pól podkategorii
            zajete |= {p["kod"] for p in _wlasny_szablon(db, potomek)}
        pole = {"kod": _kod_pola(pole["nazwy"], zajete), **pole}
        _zapisz_szablon(db, kat_id, szablon + [pole])
        return pole["kod"]


def zapisz_pole(db: sqlite3.Connection, kat_id: int, kod: str, dane: dict) -> None:
    with transakcja(db):
        szablon = _wlasny_szablon(db, kat_id)
        i = _pole_wlasne(szablon, kod)
        stary_typ = szablon[i]["typ"]
        if stary_typ == "text" and dane.get("typ") == "enum":
            # tekst -> lista: wartości już wpisane trafiają na listę, nic nie ginie
            uzyte = []
            for _t, _id, atrybuty in _wpisy_kategorii(db, kat_id):
                w = atrybuty.get(kod)
                if isinstance(w, str) and w.strip() and w not in uzyte:
                    uzyte.append(w)
            dane = {**dane, "wartosci": list(dane.get("wartosci") or []) + uzyte}
        nowe = _pole_z_danych(dane)
        if nowe["typ"] != stary_typ and not (stary_typ == "text" and nowe["typ"] == "enum") \
                and any(uzycie_pola(db, kat_id, kod).values()):
            raise BladNornicy("blad.pole_typ_w_uzyciu")
        if nowe["typ"] == "enum":
            usuwane = [w for w in szablon[i].get("wartosci", []) if w not in nowe["wartosci"]]
            w_uzyciu = [w for w in usuwane if uzycie_wartosci(db, kat_id, kod, w)]
            if w_uzyciu:
                raise BladNornicy("blad.wartosc_w_uzyciu", lista=", ".join(w_uzyciu))
        inne = [p["nazwy"] for p in repo.szablon(db, kat_id) if p["kod"] != kod]
        if _zajete(inne, nowe["nazwy"]):
            raise BladNornicy("blad.duplikat")
        szablon[i] = {"kod": kod, **nowe}
        _zapisz_szablon(db, kat_id, szablon)


def usun_pole(db: sqlite3.Connection, kat_id: int, kod: str) -> int:
    """Usuwa pole i jego wartości z modeli i egzemplarzy. Zwraca liczbę wyczyszczonych wpisów."""
    with transakcja(db):
        szablon = _wlasny_szablon(db, kat_id)
        i = _pole_wlasne(szablon, kod)
        wyczyszczone = 0
        for tabela, id_, atrybuty in list(_wpisy_kategorii(db, kat_id)):
            if kod in atrybuty:
                del atrybuty[kod]
                db.execute(f"UPDATE {tabela} SET atrybuty = ? WHERE id = ?",
                           (_json(atrybuty) if atrybuty else None, id_))
                wyczyszczone += 1
        del szablon[i]
        _zapisz_szablon(db, kat_id, szablon)
        return wyczyszczone


def przesun_pole(db: sqlite3.Connection, kat_id: int, kod: str, kierunek: int) -> None:
    """Kolejność pól w formularzu: własne pole o jedno miejsce w górę (-1) albo w dół (+1)."""
    with transakcja(db):
        szablon = _wlasny_szablon(db, kat_id)
        i = _pole_wlasne(szablon, kod)
        j = i + kierunek
        if 0 <= j < len(szablon):
            szablon[i], szablon[j] = szablon[j], szablon[i]
            _zapisz_szablon(db, kat_id, szablon)


# ---------------------------------------------------------------------------
# Własne wartości na listach pól wbudowanych
# ---------------------------------------------------------------------------
def uzycie_wartosci(db: sqlite3.Connection, kat_id: int, kod: str, wartosc: str) -> int:
    return sum(1 for _t, _i, atrybuty in _wpisy_kategorii(db, kat_id) if atrybuty.get(kod) == wartosc)


def kategoria_definiujaca(db: sqlite3.Connection, kat_id: int, kod: str) -> int:
    """Kategoria, w której pole jest zdefiniowane (ta sama albo nadrzędna — pole odziedziczone)."""
    for k in repo.lancuch_kategorii(db, kat_id):
        if any(p["kod"] == kod for p in _wlasny_szablon(db, k)):
            return k
    raise BladNornicy("blad.klucz_obcy")


def wartosci_listy(db: sqlite3.Connection, kat_id: int, kod: str) -> dict:
    """{"wbudowane": [...] (tylko do odczytu), "edytowalne": [...], "wlasne_pole": bool, "kategoria": id}."""
    definiujaca = kategoria_definiujaca(db, kat_id, kod)
    pole = next(p for p in _wlasny_szablon(db, definiujaca) if p["kod"] == kod)
    if pole["typ"] != "enum":
        raise BladNornicy("blad.wartosci_nie_lista")
    if pole.get("wlasne"):
        return {"wbudowane": [], "edytowalne": list(pole.get("wartosci", [])), "wlasne_pole": True,
                "kategoria": definiujaca, "nazwy": pole["nazwy"]}
    return {"wbudowane": list(pole.get("wartosci", [])), "edytowalne": list(pole.get("wartosci_wlasne", [])),
            "wlasne_pole": False, "kategoria": definiujaca, "nazwy": pole["nazwy"]}


def ustaw_wartosci_wlasne(db: sqlite3.Connection, kat_id: int, kod: str, wartosci: list[str]) -> list[str]:
    """Wartości do wyboru w KAŻDYM polu typu „wybór z listy” — wbudowanym, własnym
    albo odziedziczonym (zmiana trafia do kategorii, która pole definiuje).

    * pole wbudowane: lista wbudowana nietknięta, dopiski w "wartosci_wlasne",
    * pole własne: cała lista (co najmniej jedna wartość).
    Puste i powtórzone pomijane. Wartości usuwanej z listy nie może używać
    żaden model ani egzemplarz. Pola pojemności (B/KB/MB/GB) nie są listą.
    Zwraca zapisaną listę edytowalną."""
    with transakcja(db):
        definiujaca = kategoria_definiujaca(db, kat_id, kod)
        szablon = _wlasny_szablon(db, definiujaca)
        i = next(i for i, p in enumerate(szablon) if p["kod"] == kod)
        pole = szablon[i]
        if pole["typ"] != "enum":
            raise BladNornicy("blad.wartosci_nie_lista")
        wlasne_pole = bool(pole.get("wlasne"))
        znane = set() if wlasne_pole else {w.casefold() for w in pole.get("wartosci", [])}
        nowe = []
        for w in wartosci or []:
            w = (w or "").strip()
            if w and w.casefold() not in znane:
                znane.add(w.casefold())
                nowe.append(w)
        dotychczasowe = pole.get("wartosci", []) if wlasne_pole else pole.get("wartosci_wlasne", [])
        w_uzyciu = [w for w in dotychczasowe if w not in nowe and uzycie_wartosci(db, definiujaca, kod, w)]
        if w_uzyciu:
            raise BladNornicy("blad.wartosc_w_uzyciu", lista=", ".join(w_uzyciu))
        if wlasne_pole:
            if not nowe:
                raise BladNornicy("blad.lista_wartosci")
            pole["wartosci"] = nowe
        elif nowe:
            pole["wartosci_wlasne"] = nowe
        else:
            pole.pop("wartosci_wlasne", None)
        _zapisz_szablon(db, definiujaca, szablon)
        return nowe
