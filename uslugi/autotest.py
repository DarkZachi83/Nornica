# SPDX-License-Identifier: GPL-3.0-or-later
"""Samosprawdzenie zbudowanego programu: `NORNICA.exe --autotest RAPORT.txt`.

Uruchamiane przez GitHub Actions na zbudowanej paczce dla Windows, zanim
trafi do wydania. Testy jednostkowe sprawdzają kod; to sprawdza PACZKĘ:
czy PyInstaller zabrał wszystkie biblioteki i pliki danych, które ładują się
dopiero przy użyciu danej funkcji (kody QR, etykiety PDF, eksport do Excela,
certyfikat skanera, kopia zapasowa, okno tkinter).

Działa na osobnym, tymczasowym folderze danych — kolekcja użytkownika nie
jest otwierana. Okienkowy program nie ma konsoli, więc raport trafia do pliku.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import traceback
from pathlib import Path


def _kolekcja(katalog: Path):
    from baza import dane_startowe
    from baza.migracje import migruj
    from baza.polaczenie import otworz_baze
    from baza.repozytoria import slowniki
    from uslugi import inwentarz
    db = otworz_baze(katalog / "nornica.sqlite3")
    migruj(db)
    dane_startowe.wypelnij(db)
    kat = db.execute("SELECT id FROM kategoria WHERE kod = 'skladaki_pc'").fetchone()[0]
    lok = inwentarz.zapisz_lokalizacje(db, {"nazwa": "Regał A", "typ": "regal"})
    inwentarz.zapisz_egzemplarz(db, {"nazwa_wlasna": "Pentium 166 MMX", "kategoria_id": kat,
                                     "status_id": slowniki.status_id(db, "dziala"), "lokalizacja_id": lok})
    return db


def _sprawdzenia(db, katalog: Path) -> list[tuple[str, object]]:
    def qr():
        from uslugi import etykiety
        assert etykiety.macierz_qr("NOR-000001")

    def etykiety_pdf():
        from uslugi import etykiety
        lista = etykiety.zakres(db, None, True)
        pliki = etykiety.generuj(katalog / "etykiety.pdf", lista, etykiety.FORMATY["avery_l7160"])
        assert pliki and pliki[0].stat().st_size > 1000

    def eksport():
        from raporty import dane
        from uslugi import eksport as e
        formaty = [f for f, jest in e.dostepne_formaty().items() if jest]
        assert {"csv", "xlsx", "xls", "html"} <= set(formaty), formaty
        assert e.eksportuj(db, katalog / "kolekcja", formaty, dane.Opcje(jezyk="pl"))

    def certyfikat():
        from uslugi import certyfikaty
        assert certyfikaty.dostepne()
        pliki = certyfikaty.przygotuj(katalog / "certyfikat", ["192.168.1.10"])
        assert pliki["ca"].is_file() and pliki["cert"].is_file()

    def kopia_zapasowa():
        from uslugi import archiwum
        manifest = archiwum.utworz_kopie(db, katalog / "proba.zip")
        roboczy = katalog / "sprawdzenie"
        roboczy.mkdir()
        archiwum.sprawdz(katalog / "proba.zip", roboczy)
        assert manifest["liczby"]["egzemplarze"] == 1

    def okno():
        import tkinter as tk
        from PIL import ImageTk  # noqa: F401 — miniatury zdjęć
        korzen = tk.Tk()
        korzen.withdraw()
        obraz = tk.PhotoImage(file=str(Path(__file__).resolve().parents[1] / "zasoby" / "ikona_64.png"))
        assert obraz.width() == 64
        korzen.destroy()

    def strona_telefonu():
        from uslugi.serwer_mobilny import KATALOG_WWW
        assert (KATALOG_WWW / "skaner.html").is_file() and (KATALOG_WWW / "jsQR.js").is_file()

    return [("kody QR", qr), ("etykiety PDF", etykiety_pdf), ("eksport CSV/XLSX/XLS/HTML", eksport),
            ("certyfikat skanera", certyfikat), ("kopia zapasowa ZIP", kopia_zapasowa),
            ("okno tkinter i obrazy", okno), ("strona dla telefonu", strona_telefonu)]


def uruchom(plik_raportu: str | Path) -> int:
    """Zwraca 0, gdy wszystko działa, 1 przy pierwszym problemie (lista w raporcie)."""
    katalog = Path(tempfile.mkdtemp(prefix="nornica-autotest-"))
    os.environ["NORNICA_DANE"] = str(katalog)          # folder plików i kopii — tymczasowy
    linie, bledy = [], 0
    try:
        db = _kolekcja(katalog)
        linie.append("OK    baza, migracje i dane startowe")
        for nazwa, sprawdzenie in _sprawdzenia(db, katalog):
            try:
                sprawdzenie()
                linie.append(f"OK    {nazwa}")
            except Exception:   # noqa: BLE001 — raport ma zebrać wszystkie problemy naraz
                bledy += 1
                linie.append(f"BŁĄD  {nazwa}\n{traceback.format_exc()}")
        db.close()
    except Exception:   # noqa: BLE001
        bledy += 1
        linie.append(f"BŁĄD  baza\n{traceback.format_exc()}")
    finally:
        shutil.rmtree(katalog, ignore_errors=True)
    linie.append("WYNIK: " + ("wszystko działa" if not bledy else f"problemy: {bledy}"))
    Path(plik_raportu).write_text("\n".join(linie) + "\n", encoding="utf-8")
    return 1 if bledy else 0
