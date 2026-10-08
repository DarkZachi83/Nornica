# SPDX-License-Identifier: GPL-3.0-or-later
"""Porządki w kolekcji: wyszukiwanie śmieci i luk w danych.

Dwie grupy kontroli:
  * do usunięcia — zasoby bez powiązań, pliki bez wpisu w bazie, wpisy
    wskazujące nieistniejący plik, puste lokalizacje, modele bez egzemplarzy,
    producenci bez modeli;
  * do sprawdzenia — egzemplarze bez miejsca i powtórzone numery seryjne.
    Tu program niczego nie usuwa, tylko prowadzi do rekordu.

Zasady (te same co w uslugi/pliki.py i baza/repozytoria/zasoby.py):
  * nic nie znika automatycznie — użytkownik zaznacza, co usunąć;
  * każde usuwanie SPRAWDZA WARUNEK PONOWNIE w chwili usuwania: między
    wyświetleniem listy a kliknięciem „Usuń” coś mogło zostać podpięte
    (choćby zdjęcie z telefonu), a takiego rekordu ani pliku nie ruszamy;
  * najpierw baza (transakcja), po zatwierdzeniu dysk;
  * plik bez wpisu musi być starszy niż WIEK_PLIKU_BEZ_WPISU — dodawanie
    zdjęcia zapisuje plik na dysk chwilę PRZED rekordem w bazie, więc świeży
    plik bez wpisu może być właśnie dodawany.

Funkcje zwracają surowe dane (bez tekstów): okno formatuje je przy
wyświetleniu, więc lista przeżywa zmianę języka.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from baza.polaczenie import transakcja
from baza.repozytoria import zasoby
from uslugi import pliki

_log = logging.getLogger(__name__)

WIEK_PLIKU_BEZ_WPISU = 600          # sekund
_PRZEDROSTEK_TYMCZASOWY = ".kopia-"  # pliki tymczasowe _skopiuj_do_magazynu


@dataclass(frozen=True)
class Kontrola:
    kod: str
    usuwanie: bool        # czy wolno usuwać zaznaczone pozycje
    przejscie: bool       # czy pozycja prowadzi do egzemplarza / lokalizacji


KONTROLE: tuple[Kontrola, ...] = (
    Kontrola("zasoby_sieroty", usuwanie=True, przejscie=False),
    Kontrola("pliki_bez_wpisu", usuwanie=True, przejscie=False),
    Kontrola("brakujace_pliki", usuwanie=True, przejscie=True),
    Kontrola("puste_lokalizacje", usuwanie=True, przejscie=True),
    Kontrola("nieuzywane_modele", usuwanie=True, przejscie=False),
    Kontrola("nieuzywani_producenci", usuwanie=True, przejscie=False),
    Kontrola("bez_lokalizacji", usuwanie=False, przejscie=True),
    Kontrola("powtorzone_numery", usuwanie=False, przejscie=True),
)
PO_KODZIE = {k.kod: k for k in KONTROLE}


# ---------------------------------------------------------------------------
# Wyszukiwanie
# ---------------------------------------------------------------------------
def zasoby_sieroty(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return zasoby.osierocone(db)


def _wzgledna(sciezka: Path, katalog: Path) -> str:
    return sciezka.relative_to(katalog).as_posix()


def pliki_bez_wpisu(db: sqlite3.Connection, teraz: float | None = None) -> list[dict]:
    """Pliki w magazynie, których nie wskazuje żaden zasób. Najstarsze najpierw."""
    katalog = pliki.katalog_plikow(db)
    if not katalog.is_dir():
        return []
    znane = {w[0] for w in db.execute("SELECT plik_sciezka FROM zasob WHERE plik_sciezka IS NOT NULL")}
    granica = (time.time() if teraz is None else teraz) - WIEK_PLIKU_BEZ_WPISU
    wynik = []
    for sciezka in katalog.rglob("*"):
        try:
            if not sciezka.is_file() or sciezka.is_symlink():
                continue
            stan = sciezka.stat()
        except OSError:
            continue
        wzgledna = _wzgledna(sciezka, katalog)
        if wzgledna in znane or stan.st_mtime > granica:
            continue
        wynik.append({"sciezka": wzgledna, "rozmiar": stan.st_size, "zmieniono": stan.st_mtime,
                      "tymczasowy": sciezka.name.startswith(_PRZEDROSTEK_TYMCZASOWY)})
    wynik.sort(key=lambda p: p["zmieniono"])
    return wynik


def brakujace_pliki(db: sqlite3.Connection) -> list[dict]:
    """Zasoby wskazujące plik, którego nie ma na dysku, z pierwszym
    egzemplarzem, do którego są podpięte (żeby było wiadomo, czego dotyczą)."""
    wynik = []
    for w in db.execute(
            "SELECT z.id, z.typ, z.tytul, z.plik_sciezka, z.plik_rozmiar, "
            "       (SELECT p.egzemplarz_id FROM zasob_powiazanie p "
            "         WHERE p.zasob_id = z.id AND p.egzemplarz_id IS NOT NULL "
            "         ORDER BY p.egzemplarz_id LIMIT 1) AS egzemplarz_id, "
            "       (SELECT COUNT(*) FROM zasob_powiazanie p WHERE p.zasob_id = z.id) AS powiazan "
            "FROM zasob z WHERE z.plik_sciezka IS NOT NULL ORDER BY z.dodano"):
        if not pliki.sciezka_pliku(db, w["plik_sciezka"]).is_file():
            wynik.append(dict(w))
    return wynik


_PUSTA_LOKALIZACJA = (
    "NOT EXISTS (SELECT 1 FROM egzemplarz e WHERE e.lokalizacja_id = l.id) "
    "AND NOT EXISTS (SELECT 1 FROM lokalizacja d WHERE d.rodzic_id = l.id)")


def puste_lokalizacje(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT l.id, l.nazwa, l.typ, l.kod_etykiety, s.sciezka "
        "FROM lokalizacja l LEFT JOIN v_lokalizacja_sciezka s ON s.lokalizacja_id = l.id "
        f"WHERE {_PUSTA_LOKALIZACJA} ORDER BY s.sciezka").fetchall()


_NIEUZYWANY_MODEL = "NOT EXISTS (SELECT 1 FROM egzemplarz e WHERE e.model_id = m.id)"


def nieuzywane_modele(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT m.id, m.nazwa, m.numer_czesci, p.nazwa AS producent, k.nazwy AS kategoria_nazwy "
        "FROM model m LEFT JOIN producent p ON p.id = m.producent_id "
        "JOIN kategoria k ON k.id = m.kategoria_id "
        f"WHERE {_NIEUZYWANY_MODEL} "
        "ORDER BY p.nazwa COLLATE NOCASE, m.nazwa COLLATE NOCASE").fetchall()


_NIEUZYWANY_PRODUCENT = "NOT EXISTS (SELECT 1 FROM model m WHERE m.producent_id = p.id)"


def nieuzywani_producenci(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(f"SELECT p.id, p.nazwa FROM producent p WHERE {_NIEUZYWANY_PRODUCENT} "
                      "ORDER BY p.nazwa COLLATE NOCASE").fetchall()


_EGZEMPLARZ = (
    "SELECT e.id, e.kod_inwentarzowy, e.nazwa_wlasna, e.numer_seryjny, "
    "       m.nazwa AS model_nazwa, p.nazwa AS producent, s.nazwy AS status_nazwy "
    "FROM egzemplarz e LEFT JOIN model m ON m.id = e.model_id "
    "LEFT JOIN producent p ON p.id = m.producent_id JOIN status s ON s.id = e.status_id ")


def bez_lokalizacji(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Egzemplarze ani nie zamontowane, ani nie odłożone w żadne miejsce."""
    return db.execute(_EGZEMPLARZ + "WHERE e.lokalizacja_id IS NULL AND e.rodzic_id IS NULL "
                      "ORDER BY e.kod_inwentarzowy").fetchall()


def powtorzone_numery(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Egzemplarze dzielące numer seryjny (bez rozróżniania wielkości liter
    i spacji na brzegach). Często literówka albo ten sam sprzęt wpisany dwa razy."""
    return db.execute(
        _EGZEMPLARZ + "WHERE trim(e.numer_seryjny) <> '' AND upper(trim(e.numer_seryjny)) IN ("
        "  SELECT upper(trim(numer_seryjny)) FROM egzemplarz WHERE trim(numer_seryjny) <> '' "
        "  GROUP BY upper(trim(numer_seryjny)) HAVING COUNT(*) > 1) "
        "ORDER BY upper(trim(e.numer_seryjny)), e.kod_inwentarzowy").fetchall()


_WYSZUKIWANIE = {
    "zasoby_sieroty": zasoby_sieroty,
    "pliki_bez_wpisu": pliki_bez_wpisu,
    "brakujace_pliki": brakujace_pliki,
    "puste_lokalizacje": puste_lokalizacje,
    "nieuzywane_modele": nieuzywane_modele,
    "nieuzywani_producenci": nieuzywani_producenci,
    "bez_lokalizacji": bez_lokalizacji,
    "powtorzone_numery": powtorzone_numery,
}


def znajdz(db: sqlite3.Connection, kod: str) -> list:
    return list(_WYSZUKIWANIE[kod](db))


def przeglad(db: sqlite3.Connection) -> dict[str, list]:
    """Wyniki wszystkich kontroli naraz (okno pokazuje liczby przy każdej)."""
    return {k.kod: znajdz(db, k.kod) for k in KONTROLE}


def klucz_pozycji(kod: str, pozycja) -> str | int:
    """Identyfikator pozycji do zaznaczania i usuwania."""
    return pozycja["sciezka"] if kod == "pliki_bez_wpisu" else pozycja["id"]


# ---------------------------------------------------------------------------
# Usuwanie — zawsze z ponownym sprawdzeniem warunku
# ---------------------------------------------------------------------------
def _znaki(lista: list) -> str:
    return ", ".join("?" * len(lista))


def _usun_pliki(db: sqlite3.Connection, wzgledne: list[str]) -> int:
    usuniete = 0
    for wzgledna in wzgledne:
        try:
            pliki.sciezka_pliku(db, wzgledna).unlink(missing_ok=True)
            usuniete += 1
        except OSError as blad:
            _log.warning("Nie udało się usunąć %s: %s", wzgledna, blad)
    return usuniete


def usun_pliki_bez_wpisu(db: sqlite3.Connection, wzgledne: list[str], teraz: float | None = None) -> int:
    """Usuwa pliki z magazynu — tylko te, które nadal nie mają wpisu, są
    dostatecznie stare i leżą w folderze plików (nie poza nim)."""
    katalog = pliki.katalog_plikow(db).resolve()
    aktualne = {p["sciezka"] for p in pliki_bez_wpisu(db, teraz)}
    do_usuniecia = []
    for wzgledna in wzgledne:
        if wzgledna not in aktualne:
            continue
        pelna = (katalog / wzgledna).resolve()
        if katalog not in pelna.parents:
            continue
        do_usuniecia.append(wzgledna)
    usuniete = _usun_pliki(db, do_usuniecia)
    for podkatalog in sorted({(katalog / w).parent for w in do_usuniecia}, reverse=True):
        if podkatalog != katalog:
            try:
                podkatalog.rmdir()           # tylko pusty folder (np. pliki/3f/)
            except OSError:
                pass
    return usuniete


def usun_zasoby_sieroty(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    """Zwraca liczbę usuniętych wpisów (pliki znikają razem z nimi)."""
    przed = db.execute("SELECT COUNT(*) FROM zasob").fetchone()[0]
    pliki.usun_sieroty_z_plikami(db, identyfikatory)
    return przed - db.execute("SELECT COUNT(*) FROM zasob").fetchone()[0]


def usun_wpisy_brakujacych(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    """Usuwa wpisy zasobów, których pliku nadal nie ma. Powiązania znikają
    razem z nimi, a zdjęcie główne egzemplarza wraca do „brak” (SET NULL)."""
    nadal = {p["id"] for p in brakujace_pliki(db)} & set(identyfikatory)
    if not nadal:
        return 0
    lista = sorted(nadal)
    with transakcja(db):
        return db.execute(f"DELETE FROM zasob WHERE id IN ({_znaki(lista)})", lista).rowcount


def _usun_gdzie(db: sqlite3.Connection, tabela: str, alias: str, warunek: str, identyfikatory: list[int]) -> int:
    if not identyfikatory:
        return 0
    with transakcja(db):
        return db.execute(
            f"DELETE FROM {tabela} WHERE id IN ({_znaki(identyfikatory)}) "
            f"AND id IN (SELECT {alias}.id FROM {tabela} {alias} WHERE {warunek})",
            list(identyfikatory)).rowcount


def usun_puste_lokalizacje(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    """Lokalizacje bez egzemplarzy i podlokalizacji. Gdy zaznaczono też
    rodzica, który był pusty dopiero po usunięciu dziecka, zostaje — lista
    po odświeżeniu pokaże go jako nową pozycję."""
    return _usun_gdzie(db, "lokalizacja", "l", _PUSTA_LOKALIZACJA, identyfikatory)


def usun_nieuzywane_modele(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    """Złącza modelu znikają z nim; jego dokumenty i zdjęcia zostają jako
    zasoby bez powiązań (do przejrzenia w pierwszej kontroli)."""
    return _usun_gdzie(db, "model", "m", _NIEUZYWANY_MODEL, identyfikatory)


def usun_nieuzywanych_producentow(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    return _usun_gdzie(db, "producent", "p", _NIEUZYWANY_PRODUCENT, identyfikatory)


_USUWANIE = {
    "zasoby_sieroty": usun_zasoby_sieroty,
    "pliki_bez_wpisu": usun_pliki_bez_wpisu,
    "brakujace_pliki": usun_wpisy_brakujacych,
    "puste_lokalizacje": usun_puste_lokalizacje,
    "nieuzywane_modele": usun_nieuzywane_modele,
    "nieuzywani_producenci": usun_nieuzywanych_producentow,
}


def usun(db: sqlite3.Connection, kod: str, klucze: list) -> int:
    """Usuwa zaznaczone pozycje kontroli `kod`. Zwraca liczbę usuniętych."""
    if not PO_KODZIE[kod].usuwanie:
        raise ValueError(f"kontrola {kod} nie pozwala usuwać")
    return _USUWANIE[kod](db, list(klucze))
