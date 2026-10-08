# SPDX-License-Identifier: GPL-3.0-or-later
"""Kopia zapasowa całej kolekcji w jednym pliku ZIP — i przywracanie z niej.

Zawartość archiwum:
    manifest.json          program, format, wersje, data, liczby, sumy SHA-256
    nornica.sqlite3        spójna migawka bazy (API backup SQLite)
    pliki/xx/<sha>.<roz>   zdjęcia, instrukcje, ROM-y — tylko te, na które
                           wskazuje baza (pliki bez wpisu zostają poza kopią)

Poza kopią zostają: certyfikat skanera w telefonie (klucz prywatny nie
powinien krążyć po pendrive'ach i chmurach — po przywróceniu program zrobi
nowy, a telefon trzeba raz sparować ponownie), dziennik i kopie sprzed migracji.

Tworzenie ma dwa kroki. migawka() — w wątku interfejsu, bo połączenie
SQLite należy do niego — kopiuje bazę do pliku tymczasowego (ułamek sekundy).
zapisz() pakuje migawkę i pliki; nie dotyka bazy, więc może iść w tle
z paskiem postępu. Archiwum powstaje pod nazwą tymczasową i dopiero
sprawdzone (CRC każdego wpisu) dostaje docelową nazwę — przerwane pakowanie
nie zostawi pliku wyglądającego na dobrą kopię.

Przywracanie najpierw sprawdza WSZYSTKO (manifest, CRC, sumy, spójność bazy,
wersję schematu), potem robi kopię bezpieczeństwa obecnej bazy w folderze
kopii, dokłada brakujące pliki (niczego nie kasuje — nadmiarowe wyłapie okno
porządków) i na końcu podmienia zawartość bazy jednym krokiem API backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from baza import dane_startowe
from baza.migracje import biezaca_wersja, migruj, znajdz_migracje
from baza.polaczenie import otworz_baze
from baza.repozytoria import ustawienia
from uslugi import pliki
from wersja import WERSJA
from wyjatki import BladNornicy

FORMAT = 1
PROGRAM = "NORNICA"
PLIK_MANIFESTU = "manifest.json"
PLIK_BAZY = "nornica.sqlite3"
KATALOG_PLIKOW = "pliki"
BEZ_KOMPRESJI = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".zip", ".7z",
                 ".gz", ".bz2", ".xz", ".rar", ".mp4", ".mp3"}
_BLOK = 1 << 20

Postep = Callable[[int, int], None]          # (zrobione bajty, wszystkie bajty)


@dataclass
class Migawka:
    katalog: Path                            # tymczasowy — usuwa go zapisz()
    baza: Path
    wersja_schematu: int
    liczby: dict
    pliki: list[tuple[str, Path, int]] = field(default_factory=list)   # (względna, pełna, rozmiar)
    brakujace: list[str] = field(default_factory=list)

    @property
    def rozmiar(self) -> int:
        return self.baza.stat().st_size + sum(r for _, _, r in self.pliki)


def domyslna_nazwa(teraz: datetime | None = None) -> str:
    return f"nornica_kopia_{(teraz or datetime.now()).strftime('%Y-%m-%d_%H%M')}.zip"


def _suma(sciezka: Path) -> str:
    skrot = hashlib.sha256()
    with open(sciezka, "rb") as plik:
        for blok in iter(lambda: plik.read(_BLOK), b""):
            skrot.update(blok)
    return skrot.hexdigest()


def _liczby(db: sqlite3.Connection) -> dict:
    return {nazwa: db.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            for nazwa, tabela in (("egzemplarze", "egzemplarz"), ("lokalizacje", "lokalizacja"),
                                  ("modele", "model"), ("zasoby", "zasob"))}


# ---------------------------------------------------------------------------
# Tworzenie
# ---------------------------------------------------------------------------
def migawka(db: sqlite3.Connection) -> Migawka:
    """Spójna kopia bazy w pliku tymczasowym + lista plików do spakowania."""
    if db.in_transaction:
        raise RuntimeError("migawka() w trakcie transakcji")
    katalog = Path(tempfile.mkdtemp(prefix="nornica-kopia-"))
    try:
        sciezka = katalog / PLIK_BAZY
        cel = sqlite3.connect(sciezka)
        try:
            db.backup(cel)
        finally:
            cel.close()
        wynik = Migawka(katalog, sciezka, biezaca_wersja(db), _liczby(db))
        for (wzgledna,) in db.execute("SELECT DISTINCT plik_sciezka FROM zasob "
                                      "WHERE plik_sciezka IS NOT NULL ORDER BY plik_sciezka"):
            pelna = pliki.sciezka_pliku(db, wzgledna)
            if _bezpieczna(wzgledna) and pelna.is_file():
                wynik.pliki.append((wzgledna, pelna, pelna.stat().st_size))
            else:
                wynik.brakujace.append(wzgledna)
        return wynik
    except BaseException:
        shutil.rmtree(katalog, ignore_errors=True)
        raise


def _dopisz(archiwum: zipfile.ZipFile, nazwa: str, zrodlo: Path, rozmiar: int,
            postep: Postep | None, licznik: list[int], razem: int) -> str:
    kompresja = zipfile.ZIP_STORED if zrodlo.suffix.lower() in BEZ_KOMPRESJI else zipfile.ZIP_DEFLATED
    info = zipfile.ZipInfo(nazwa, date_time=datetime.fromtimestamp(zrodlo.stat().st_mtime).timetuple()[:6])
    info.compress_type = kompresja
    skrot = hashlib.sha256()
    with open(zrodlo, "rb") as wejscie, archiwum.open(info, "w", force_zip64=rozmiar >= 1 << 31) as wyjscie:
        for blok in iter(lambda: wejscie.read(_BLOK), b""):
            skrot.update(blok)
            wyjscie.write(blok)
            licznik[0] += len(blok)
            if postep:
                postep(licznik[0], razem)
    return skrot.hexdigest()


def zapisz(m: Migawka, cel: str | Path, postep: Postep | None = None) -> dict:
    """Pakuje migawkę do pliku `cel`. Nie używa połączenia z bazą — może
    działać w wątku pobocznym. Zwraca manifest. Usuwa katalog migawki."""
    cel = Path(cel)
    tymczasowy = None
    try:
        cel.parent.mkdir(parents=True, exist_ok=True)
        deskryptor, nazwa = tempfile.mkstemp(dir=cel.parent, prefix=".nornica-kopia-", suffix=".zip")
        os.close(deskryptor)
        tymczasowy = Path(nazwa)
        razem, licznik = m.rozmiar, [0]
        sumy = {}
        with zipfile.ZipFile(tymczasowy, "w", allowZip64=True) as archiwum:
            sumy[PLIK_BAZY] = _dopisz(archiwum, PLIK_BAZY, m.baza, m.baza.stat().st_size,
                                      postep, licznik, razem)
            for wzgledna, pelna, rozmiar in m.pliki:
                nazwa_w_zip = f"{KATALOG_PLIKOW}/{wzgledna}"
                sumy[nazwa_w_zip] = _dopisz(archiwum, nazwa_w_zip, pelna, rozmiar, postep, licznik, razem)
            manifest = {
                "program": PROGRAM, "format": FORMAT, "wersja_programu": WERSJA,
                "wersja_schematu": m.wersja_schematu,
                "utworzono": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "liczby": {**m.liczby, "pliki": len(m.pliki)},
                "brakujace_pliki": m.brakujace,
                "sumy_sha256": sumy,
            }
            archiwum.writestr(PLIK_MANIFESTU, json.dumps(manifest, ensure_ascii=False, indent=1),
                              zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(tymczasowy) as sprawdzane:
            if sprawdzane.testzip() is not None:
                raise BladNornicy("blad.kopia_uszkodzona", plik=str(cel))
        os.replace(tymczasowy, cel)
        tymczasowy = None
        return manifest
    finally:
        if tymczasowy is not None:
            tymczasowy.unlink(missing_ok=True)
        shutil.rmtree(m.katalog, ignore_errors=True)


def utworz_kopie(db: sqlite3.Connection, cel: str | Path, postep: Postep | None = None) -> dict:
    """Migawka i zapis w jednym kroku (wątek interfejsu, testy, wiersz poleceń).
    Zapamiętuje datę i folder ostatniej kopii."""
    manifest = zapisz(migawka(db), cel, postep)
    zapamietaj(db, cel, manifest)
    return manifest


def zapamietaj(db: sqlite3.Connection, cel: str | Path, manifest: dict) -> None:
    ustawienia.zapisz(db, "kopia_ostatnia", manifest["utworzono"])
    ustawienia.zapisz(db, "kopia_folder", str(Path(cel).resolve().parent))


# ---------------------------------------------------------------------------
# Odczyt i sprawdzanie
# ---------------------------------------------------------------------------
def _bezpieczna(wzgledna: str) -> bool:
    """Ścieżka względna bez wyjść poza folder: żadnych „..”, „/” na początku,
    liter dysków ani odwrotnych ukośników."""
    sciezka = PurePosixPath(wzgledna)
    return (bool(wzgledna) and not sciezka.is_absolute() and "\\" not in wzgledna and ":" not in wzgledna
            and "//" not in wzgledna and not wzgledna.endswith("/")
            and all(czesc not in ("", ".", "..") for czesc in sciezka.parts))


def odczytaj_manifest(sciezka: str | Path) -> dict:
    """Manifest kopii — do pokazania przed przywróceniem. Sprawdza tylko,
    czy to w ogóle kopia NORNICY w obsługiwanym formacie."""
    try:
        with zipfile.ZipFile(sciezka) as archiwum:
            manifest = json.loads(archiwum.read(PLIK_MANIFESTU).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        raise BladNornicy("blad.kopia_nieprawidlowa", plik=str(sciezka)) from None
    if not isinstance(manifest, dict) or manifest.get("program") != PROGRAM \
            or not isinstance(manifest.get("sumy_sha256"), dict):
        raise BladNornicy("blad.kopia_nieprawidlowa", plik=str(sciezka))
    if manifest.get("format") != FORMAT:
        raise BladNornicy("blad.kopia_format", plik=str(sciezka))
    return manifest


def _najwyzsza_wersja() -> int:
    return max((numer for numer, _ in znajdz_migracje()), default=0)


def sprawdz(sciezka: str | Path, katalog_roboczy: Path) -> tuple[dict, Path]:
    """Pełne sprawdzenie kopii. Rozpakowuje bazę do katalogu roboczego
    i zwraca (manifest, ścieżka bazy). Wyjątek = kopia nie nadaje się do użycia."""
    manifest = odczytaj_manifest(sciezka)
    if manifest.get("wersja_schematu", 0) > _najwyzsza_wersja():
        raise BladNornicy("blad.kopia_nowsza", wersja=manifest.get("wersja_programu", "?"))
    sumy = manifest["sumy_sha256"]
    if PLIK_BAZY not in sumy or any(not _bezpieczna(n) for n in sumy):
        raise BladNornicy("blad.kopia_nieprawidlowa", plik=str(sciezka))
    with zipfile.ZipFile(sciezka) as archiwum:
        nazwy = set(archiwum.namelist())
        if not set(sumy) <= nazwy or archiwum.testzip() is not None:
            raise BladNornicy("blad.kopia_uszkodzona", plik=str(sciezka))
        baza = katalog_roboczy / PLIK_BAZY
        with archiwum.open(PLIK_BAZY) as wejscie, open(baza, "wb") as wyjscie:
            shutil.copyfileobj(wejscie, wyjscie, _BLOK)
    if _suma(baza) != sumy[PLIK_BAZY]:
        raise BladNornicy("blad.kopia_uszkodzona", plik=str(sciezka))
    try:
        polaczenie = otworz_baze(baza)       # z kolacją programu, gdyby kiedyś trafiła do indeksów
    except sqlite3.DatabaseError:
        raise BladNornicy("blad.kopia_uszkodzona", plik=str(sciezka)) from None
    try:
        wynik = polaczenie.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError:
        wynik = "błąd"
    finally:
        polaczenie.close()
    if wynik != "ok":
        raise BladNornicy("blad.kopia_uszkodzona", plik=str(sciezka))
    return manifest, baza


# ---------------------------------------------------------------------------
# Przywracanie
# ---------------------------------------------------------------------------
def _rozpakuj_pliki(db: sqlite3.Connection, sciezka: str | Path, sumy: dict) -> int:
    """Dokłada pliki z kopii, których brakuje w magazynie. Każdy trafia na
    dysk pod nazwą tymczasową i dostaje właściwą dopiero po zgodności sumy."""
    katalog = pliki.katalog_plikow(db)
    dodane = 0
    przedrostek = KATALOG_PLIKOW + "/"
    with zipfile.ZipFile(sciezka) as archiwum:
        for nazwa, suma in sumy.items():
            if not nazwa.startswith(przedrostek):
                continue
            cel = katalog / nazwa[len(przedrostek):]
            if cel.is_file():
                continue
            cel.parent.mkdir(parents=True, exist_ok=True)
            deskryptor, tymczasowy = tempfile.mkstemp(dir=cel.parent, prefix=".kopia-")
            os.close(deskryptor)
            try:
                skrot = hashlib.sha256()
                with archiwum.open(nazwa) as wejscie, open(tymczasowy, "wb") as wyjscie:
                    for blok in iter(lambda: wejscie.read(_BLOK), b""):
                        skrot.update(blok)
                        wyjscie.write(blok)
                if skrot.hexdigest() != suma:
                    raise BladNornicy("blad.kopia_uszkodzona", plik=str(sciezka))
                os.replace(tymczasowy, cel)
                dodane += 1
            finally:
                Path(tymczasowy).unlink(missing_ok=True)
    return dodane


def przywroc(db: sqlite3.Connection, sciezka: str | Path, katalog_kopii: Path) -> dict:
    """Zastępuje zawartość bazy kopią. Zwraca podsumowanie:
    manifest, dodane_pliki, kopia_bezpieczenstwa (ścieżka)."""
    if db.in_transaction:
        raise RuntimeError("przywroc() w trakcie transakcji")
    roboczy = Path(tempfile.mkdtemp(prefix="nornica-przywracanie-"))
    try:
        manifest, baza = sprawdz(sciezka, roboczy)
        # kopia bezpieczeństwa tego, co jest teraz — gdyby przywrócono nie ten plik
        katalog_kopii.mkdir(parents=True, exist_ok=True)
        znacznik = datetime.now().strftime("%Y%m%d_%H%M%S")
        bezpieczenstwo = katalog_kopii / f"przed_przywroceniem_{znacznik}.sqlite3"
        cel = sqlite3.connect(bezpieczenstwo)
        try:
            db.backup(cel)
        finally:
            cel.close()
        dodane = _rozpakuj_pliki(db, sciezka, manifest["sumy_sha256"])
        zrodlo = sqlite3.connect(baza)
        try:
            zrodlo.backup(db)            # jeden krok: całość albo nic
        finally:
            zrodlo.close()
        migruj(db, katalog_kopii)        # kopia ze starszej wersji programu
        dane_startowe.wypelnij(db)
        return {"manifest": manifest, "dodane_pliki": dodane, "kopia_bezpieczenstwa": bezpieczenstwo}
    finally:
        shutil.rmtree(roboczy, ignore_errors=True)
