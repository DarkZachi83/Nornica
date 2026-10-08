# SPDX-License-Identifier: GPL-3.0-or-later
"""Magazyn plików: zdjęcia, instrukcje, sterowniki, obrazy BIOS i ROM.

Zasady:
  * Oryginał jest KOPIOWANY do folderu „pliki” obok bazy, pod nazwą z sumy
    SHA-256 (np. pliki/3f/3fa9…e1.jpg). Ten sam plik dodany drugi raz nie
    zajmuje miejsca — powstaje tylko nowe powiązanie z istniejącym zasobem.
  * Miniatura (PNG, do 160 px) trafia do bazy jako BLOB; generuje ją Pillow.
    Bez Pillow plik i tak zostaje dodany, tylko bez podglądu. Wyświetlanie
    miniatur Pillow nie wymaga — tkinter czyta PNG sam.
  * Kolejność: najpierw plik na dysk (zapis atomowy przez plik tymczasowy),
    potem rekord w bazie. Jeśli zapis do bazy się nie uda, zostaje plik bez
    rekordu — wyłapie go skan folderu. Przy usuwaniu odwrotnie: najpierw
    rekord, po zatwierdzeniu plik.
"""
from __future__ import annotations

import functools
import hashlib
import io
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import konfiguracja
from baza.polaczenie import transakcja
from baza.repozytoria.zasoby import usun_osierocone
from wyjatki import BladNornicy

_log = logging.getLogger(__name__)

ROZSZERZENIA_ZDJEC = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".heif"}
ROZMIAR_MINIATURY = 160
CELE = ("kategoria_id", "model_id", "egzemplarz_id")


def katalog_plikow(db: sqlite3.Connection) -> Path:
    """Folder plików leży obok pliku bazy — kolekcja przeniesiona w inne
    miejsce (--baza) zabiera pliki ze sobą. Baza w pamięci (testy) używa
    katalogu danych z konfiguracji."""
    for wiersz in db.execute("PRAGMA database_list"):
        if wiersz["name"] == "main" and wiersz["file"]:
            return Path(wiersz["file"]).parent / "pliki"
    return konfiguracja.katalog_plikow()


def sciezka_pliku(db: sqlite3.Connection, wzgledna: str) -> Path:
    return katalog_plikow(db) / wzgledna


def suma_pliku(sciezka: Path) -> tuple[str, int]:
    skrot = hashlib.sha256()
    rozmiar = 0
    with open(sciezka, "rb") as plik:
        for blok in iter(lambda: plik.read(1 << 20), b""):
            skrot.update(blok)
            rozmiar += len(blok)
    return skrot.hexdigest(), rozmiar


def czy_zdjecie(sciezka: str | Path) -> bool:
    return Path(sciezka).suffix.lower() in ROZSZERZENIA_ZDJEC


def pillow_dostepne() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def zrob_miniature(sciezka: Path) -> bytes | None:
    """PNG o dłuższym boku do ROZMIAR_MINIATURY px albo None."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(sciezka) as obraz:
            # Zdjęcia z telefonu zapisują obrót w EXIF — bez tego leżałyby bokiem
            obraz = ImageOps.exif_transpose(obraz)
            obraz.thumbnail((ROZMIAR_MINIATURY, ROZMIAR_MINIATURY))
            if obraz.mode not in ("RGB", "RGBA"):
                obraz = obraz.convert("RGBA" if "A" in obraz.getbands() else "RGB")
            bufor = io.BytesIO()
            obraz.save(bufor, format="PNG", optimize=True)
            return bufor.getvalue()
    except Exception as blad:   # noqa: BLE001 — uszkodzony lub nietypowy plik: bez miniatury
        _log.warning("Nie udało się zrobić miniatury %s: %s", sciezka, blad)
        return None


def _skopiuj_do_magazynu(zrodlo: Path, cel: Path) -> None:
    if cel.exists():
        return
    cel.parent.mkdir(parents=True, exist_ok=True)
    deskryptor, tymczasowy = tempfile.mkstemp(dir=cel.parent, prefix=".kopia-")
    os.close(deskryptor)
    try:
        shutil.copyfile(zrodlo, tymczasowy)
        os.replace(tymczasowy, cel)          # atomowo: plik jest cały albo go nie ma
    except BaseException:
        Path(tymczasowy).unlink(missing_ok=True)
        raise


def _sprawdz_cel(cel: dict) -> dict:
    cel = {k: v for k, v in cel.items() if k in CELE and v is not None}
    if len(cel) != 1:
        raise BladNornicy("blad.zasob_jedno_powiazanie")
    return cel


def _powiaz(db: sqlite3.Connection, zasob_id: int, cel: dict) -> None:
    kolumna, wartosc = next(iter(cel.items()))
    # OR IGNORE: to samo powiązanie drugi raz nie jest błędem
    db.execute(f"INSERT OR IGNORE INTO zasob_powiazanie (zasob_id, {kolumna}) VALUES (?, ?)",
               (zasob_id, wartosc))


# ---------------------------------------------------------------------------
# Dodawanie, edycja, odpinanie
# ---------------------------------------------------------------------------
def typ_obrazu(poczatek: bytes) -> str | None:
    """Rozszerzenie wg ZAWARTOŚCI pliku (pierwsze bajty), nie nazwy. None = to nie obraz."""
    if poczatek.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if poczatek.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if poczatek.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if poczatek[:4] == b"RIFF" and poczatek[8:12] == b"WEBP":
        return ".webp"
    if poczatek[4:8] == b"ftyp" and poczatek[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc", b"heim"):
        return ".heic"
    return None


def przygotuj(sciezka: str | Path) -> dict:
    """Część dodawania pliku, która NIE dotyka bazy: suma kontrolna i miniatura.
    Może działać w dowolnym wątku — serwer telefonu liczy ją sam, żeby długie
    liczenie miniatury z 12-megapikselowego zdjęcia nie zatrzymywało okna."""
    zrodlo = Path(sciezka)
    suma, rozmiar = suma_pliku(zrodlo)
    return {"suma": suma, "rozmiar": rozmiar,
            "miniatura": zrob_miniature(zrodlo) if czy_zdjecie(zrodlo) else None}


def dodaj_plik(db: sqlite3.Connection, sciezka: str | Path, cel: dict,
               typ: str | None = None, tytul: str | None = None, wersja: str | None = None,
               wstepnie: dict | None = None) -> int:
    """Kopiuje plik do magazynu i podpina go do celu. Zwraca id zasobu.
    wstepnie — wynik przygotuj() policzony wcześniej (np. w wątku serwera)."""
    zrodlo = Path(sciezka)
    if not zrodlo.is_file():
        raise BladNornicy("blad.brak_pliku", sciezka=str(zrodlo))
    cel = _sprawdz_cel(cel)
    wstepnie = wstepnie or przygotuj(zrodlo)
    suma, rozmiar, miniatura = wstepnie["suma"], wstepnie["rozmiar"], wstepnie["miniatura"]
    wzgledna = f"{suma[:2]}/{suma}{zrodlo.suffix.lower()}"
    _skopiuj_do_magazynu(zrodlo, katalog_plikow(db) / wzgledna)
    typ = typ or ("zdjecie" if czy_zdjecie(zrodlo) else "dokumentacja")
    with transakcja(db):
        istniejacy = db.execute("SELECT id FROM zasob WHERE plik_sha256 = ?", (suma,)).fetchone()
        if istniejacy:
            zasob_id = istniejacy[0]
        else:
            zasob_id = db.execute(
                "INSERT INTO zasob (typ, tytul, plik_sciezka, plik_sha256, plik_rozmiar, miniatura, wersja) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (typ, (tytul or zrodlo.stem).strip(), wzgledna, suma, rozmiar, miniatura,
                 (wersja or "").strip() or None)).lastrowid
        _powiaz(db, zasob_id, cel)
    return zasob_id


def dodaj_zasob(db: sqlite3.Connection, dane: dict, cel: dict) -> int:
    """Zasób bez pliku: odnośnik (url) albo notatka (tresc)."""
    cel = _sprawdz_cel(cel)
    tytul = (dane.get("tytul") or "").strip()
    if not tytul:
        raise BladNornicy("blad.wymagany_tytul")
    with transakcja(db):
        zasob_id = db.execute(
            "INSERT INTO zasob (typ, tytul, url, tresc, wersja) VALUES (?, ?, ?, ?, ?)",
            (dane["typ"], tytul, (dane.get("url") or "").strip() or None,
             (dane.get("tresc") or "").strip() or None,
             (dane.get("wersja") or "").strip() or None)).lastrowid
        _powiaz(db, zasob_id, cel)
    return zasob_id


def zapisz_zasob(db: sqlite3.Connection, zasob_id: int, dane: dict) -> None:
    """Edycja opisu zasobu. Plik się nie zmienia (nowa wersja = nowy plik)."""
    tytul = (dane.get("tytul") or "").strip()
    if not tytul:
        raise BladNornicy("blad.wymagany_tytul")
    pola = {"typ": dane["typ"], "tytul": tytul,
            "wersja": (dane.get("wersja") or "").strip() or None}
    for klucz in ("url", "tresc"):
        if klucz in dane:
            pola[klucz] = (dane[klucz] or "").strip() or None
    with transakcja(db):
        db.execute(f"UPDATE zasob SET {', '.join(k + ' = ?' for k in pola)} WHERE id = ?",
                   [*pola.values(), zasob_id])


def odepnij(db: sqlite3.Connection, zasob_id: int, cel: dict) -> bool:
    """Usuwa powiązanie. Zwraca True, jeśli zasób został sierotą."""
    kolumna, wartosc = next(iter(_sprawdz_cel(cel).items()))
    with transakcja(db):
        db.execute(f"DELETE FROM zasob_powiazanie WHERE zasob_id = ? AND {kolumna} = ?",
                   (zasob_id, wartosc))
        if kolumna == "egzemplarz_id":     # odpięte zdjęcie przestaje być główne
            db.execute("UPDATE egzemplarz SET zdjecie_glowne_id = NULL "
                       "WHERE id = ? AND zdjecie_glowne_id = ?", (wartosc, zasob_id))
        pozostale = db.execute("SELECT COUNT(*) FROM zasob_powiazanie WHERE zasob_id = ?",
                               (zasob_id,)).fetchone()[0]
    return pozostale == 0


def usun_sieroty_z_plikami(db: sqlite3.Connection, identyfikatory: list[int]) -> int:
    """Usuwa zasoby-sieroty i ich pliki. Najpierw baza, po zatwierdzeniu dysk.
    Zwraca liczbę usuniętych plików."""
    with transakcja(db):
        sciezki = usun_osierocone(db, identyfikatory)
    usuniete = 0
    for wzgledna in sciezki:
        try:
            sciezka_pliku(db, wzgledna).unlink(missing_ok=True)
            usuniete += 1
        except OSError as blad:
            _log.warning("Nie udało się usunąć %s: %s", wzgledna, blad)
    return usuniete


# ---------------------------------------------------------------------------
# Otwieranie w programie systemowym
# ---------------------------------------------------------------------------
def otworz(cel: str | Path) -> None:
    """Otwiera plik lub adres w domyślnym programie systemu."""
    cel = str(cel)
    if sys.platform.startswith("win"):
        os.startfile(cel)  # noqa: S606 — celowe otwarcie w programie systemowym
    elif sys.platform == "darwin":
        subprocess.Popen(["open", cel])
    else:
        subprocess.Popen(["xdg-open", cel], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def otworz_zasob(db: sqlite3.Connection, zasob: sqlite3.Row) -> None:
    if zasob["plik_sciezka"]:
        sciezka = sciezka_pliku(db, zasob["plik_sciezka"])
        if not sciezka.exists():
            raise BladNornicy("blad.brak_pliku", sciezka=str(sciezka))
        otworz(sciezka)
    elif zasob["url"]:
        otworz(zasob["url"])


# ---------------------------------------------------------------------------
# Zdjęcie główne egzemplarza
# ---------------------------------------------------------------------------
def zdjecia_egzemplarza(db: sqlite3.Connection, egz_id: int) -> list[sqlite3.Row]:
    """Zdjęcia widoczne przy egzemplarzu: własne, modelu i kategorii."""
    from baza.repozytoria.szczegoly import zasoby_dziedziczone
    return [z for z in zasoby_dziedziczone(db, egz_id) if z["typ"] == "zdjecie"]


def ustaw_zdjecie_glowne(db: sqlite3.Connection, egz_id: int, zasob_id: int | None) -> None:
    """Wybiera zdjęcie główne (None = brak). Dozwolone tylko zdjęcia widoczne
    przy egzemplarzu."""
    if zasob_id is not None and zasob_id not in {z["id"] for z in zdjecia_egzemplarza(db, egz_id)}:
        raise BladNornicy("blad.nie_zdjecie")
    with transakcja(db):
        db.execute("UPDATE egzemplarz SET zdjecie_glowne_id = ? WHERE id = ?", (zasob_id, egz_id))


def zdjecie_glowne(db: sqlite3.Connection, egz_id: int) -> sqlite3.Row | None:
    """Wybrane zdjęcie główne — o ile nadal jest widoczne przy egzemplarzu
    (np. po odpięciu od modelu wybór przestaje obowiązywać)."""
    wiersz = db.execute("SELECT zdjecie_glowne_id FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()
    if not wiersz or wiersz[0] is None:
        return None
    return next((z for z in zdjecia_egzemplarza(db, egz_id) if z["id"] == wiersz[0]), None)


@functools.lru_cache(maxsize=32)
def _podglad_z_pliku(sciezka: str, zmiana: float, szerokosc: int, wysokosc: int) -> bytes | None:
    """Podgląd PNG z oryginału. Pamięć podręczna: dekodowanie zdjęcia z aparatu
    trwa, a karta jest przebudowywana przy każdym zaznaczeniu. Czas modyfikacji
    pliku w kluczu unieważnia wpis, gdyby plik się zmienił."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(sciezka) as obraz:
            obraz.draft("RGB", (szerokosc * 2, wysokosc * 2))   # JPEG: szybkie wczytanie w mniejszej skali
            obraz = ImageOps.exif_transpose(obraz)
            obraz.thumbnail((szerokosc, wysokosc))
            if obraz.mode not in ("RGB", "RGBA"):
                obraz = obraz.convert("RGB")
            bufor = io.BytesIO()
            obraz.save(bufor, format="PNG")
            return bufor.getvalue()
    except Exception as blad:   # noqa: BLE001
        _log.warning("Nie udało się zrobić podglądu %s: %s", sciezka, blad)
        return None


def podglad(db: sqlite3.Connection, zasob: sqlite3.Row, szerokosc: int, wysokosc: int) -> bytes | None:
    """PNG o wymiarach mieszczących się w ramce. Bez Pillow lub bez pliku —
    miniatura z bazy (mniejsza, ale lepsza niż nic)."""
    if zasob["plik_sciezka"]:
        sciezka = sciezka_pliku(db, zasob["plik_sciezka"])
        if sciezka.exists():
            dane = _podglad_z_pliku(str(sciezka), sciezka.stat().st_mtime, szerokosc, wysokosc)
            if dane:
                return dane
    return zasob["miniatura"]


def podglad_pliku(sciezka: Path, szerokosc: int, wysokosc: int) -> bytes | None:
    """Podgląd dowolnego pliku graficznego (np. obrazka zastępczego) w zadanym rozmiarze."""
    if not Path(sciezka).exists():
        return None
    return _podglad_z_pliku(str(sciezka), Path(sciezka).stat().st_mtime, szerokosc, wysokosc)
