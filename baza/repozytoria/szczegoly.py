# SPDX-License-Identifier: GPL-3.0-or-later
"""Dane do zakładek karty szczegółów: złącza, zasoby (z dziedziczeniem), historia."""
from __future__ import annotations

import sqlite3

from baza.repozytoria.slowniki import lancuch_kategorii


def zlacza_egzemplarza(db: sqlite3.Connection, egz_id: int) -> list[dict]:
    """Złącza modelu z nadpisaniami egzemplarza (ilość 0 = usunięte)."""
    wiersz = db.execute("SELECT model_id FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()
    zlacza: dict[tuple, dict] = {}
    if wiersz and wiersz[0]:
        for w in db.execute("SELECT zlacze_typ_id, rola, ilosc FROM model_zlacze WHERE model_id = ?",
                            (wiersz[0],)):
            zlacza[(w[0], w[1])] = {"ilosc": w[2], "zmienione": False}
    for w in db.execute("SELECT zlacze_typ_id, rola, ilosc FROM egzemplarz_zlacze WHERE egzemplarz_id = ?",
                        (egz_id,)):
        zlacza[(w[0], w[1])] = {"ilosc": w[2], "zmienione": True}
    typy = {w["id"]: w for w in db.execute("SELECT id, rodzaj, nazwy, kolejnosc FROM zlacze_typ")}
    wynik = []
    for (typ_id, rola), dane in zlacza.items():
        if dane["ilosc"] > 0:
            typ = typy[typ_id]
            wynik.append({"rodzaj": typ["rodzaj"], "nazwy": typ["nazwy"], "rola": rola,
                          "ilosc": dane["ilosc"], "zmienione": dane["zmienione"],
                          "kolejnosc": typ["kolejnosc"]})
    return sorted(wynik, key=lambda z: (z["rola"], z["kolejnosc"]))


def zasoby_dziedziczone(db: sqlite3.Connection, egz_id: int) -> list[sqlite3.Row]:
    """Zasoby egzemplarza, jego modelu i kategorii (z rodzicami).

    Każdy wiersz ma `pochodzenie` ('egzemplarz' | 'model' | 'kategoria') oraz
    kolumny powiązania (p_kategoria_id, p_model_id, p_egzemplarz_id) — potrzebne,
    żeby odpiąć zasób dokładnie tam, gdzie jest podpięty.
    """
    egz = db.execute("SELECT e.model_id, coalesce(m.kategoria_id, e.kategoria_id) "
                     "FROM egzemplarz e LEFT JOIN model m ON m.id = e.model_id WHERE e.id = ?",
                     (egz_id,)).fetchone()
    if not egz:
        return []
    kategorie = lancuch_kategorii(db, egz[1]) or [-1]
    znaki = ", ".join("?" * len(kategorie))
    kolumny = ("z.*, p.kategoria_id AS p_kategoria_id, p.model_id AS p_model_id, "
               "p.egzemplarz_id AS p_egzemplarz_id")
    return db.execute(
        f"SELECT {kolumny}, 'egzemplarz' AS pochodzenie, 0 AS kolejnosc FROM zasob z "
        "JOIN zasob_powiazanie p ON p.zasob_id = z.id WHERE p.egzemplarz_id = ? "
        "UNION ALL "
        f"SELECT {kolumny}, 'model', 1 FROM zasob z "
        "JOIN zasob_powiazanie p ON p.zasob_id = z.id WHERE p.model_id IS ? AND p.model_id IS NOT NULL "
        "UNION ALL "
        f"SELECT {kolumny}, 'kategoria', 2 FROM zasob z "
        f"JOIN zasob_powiazanie p ON p.zasob_id = z.id WHERE p.kategoria_id IN ({znaki}) "
        "ORDER BY kolejnosc, dodano",
        [egz_id, egz[0], *kategorie]).fetchall()


def cel_powiazania(wiersz) -> dict:
    """{'model_id': 7} itp. — dokładnie jedno powiązanie, z którego pochodzi wiersz."""
    for kolumna in ("kategoria_id", "model_id", "egzemplarz_id"):
        if wiersz[f"p_{kolumna}"] is not None:
            return {kolumna: wiersz[f"p_{kolumna}"]}
    return {}


def zdarzenia(db: sqlite3.Connection, egz_id: int) -> list[sqlite3.Row]:
    return db.execute("SELECT * FROM zdarzenie WHERE egzemplarz_id = ? ORDER BY data DESC, id DESC",
                      (egz_id,)).fetchall()
