# SPDX-License-Identifier: GPL-3.0-or-later
"""Obsługa zeskanowanych kodów — wspólna dla wszystkich źródeł skanu:
pole „Skanuj” (czytnik USB/Bluetooth działa jak klawiatura) i telefon.

Kod egzemplarza (NOR-000123) albo lokalizacji (LOC-0012), bez względu na
wielkość liter i spacje dookoła. Karta dla telefonu NIGDY nie zawiera danych
prywatnych (cena, źródło i data nabycia).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass

from baza.enumy import etykieta
from baza.repozytoria import egzemplarze, lokalizacje
from i18n.tlumacz import nazwa, t

MAKS_EGZEMPLARZY_W_LOKALIZACJI = 60


@dataclass
class Wynik:
    typ: str            # "egzemplarz" | "lokalizacja" | "nieznany"
    kod: str
    ident: int | None = None


def normalizuj(kod: str) -> str:
    """Spacje i znaki końca linii z czytnika precz; kod wielkimi literami."""
    return "".join((kod or "").split()).upper()


def rozpoznaj(db: sqlite3.Connection, kod: str) -> Wynik:
    kod = normalizuj(kod)
    if not kod:
        return Wynik("nieznany", kod)
    # kolumny mają COLLATE NOCASE — porównanie bez względu na wielkość liter
    wiersz = db.execute("SELECT id FROM egzemplarz WHERE kod_inwentarzowy = ?", (kod,)).fetchone()
    if wiersz:
        return Wynik("egzemplarz", kod, wiersz[0])
    wiersz = db.execute("SELECT id FROM lokalizacja WHERE kod_etykiety = ?", (kod,)).fetchone()
    if wiersz:
        return Wynik("lokalizacja", kod, wiersz[0])
    return Wynik("nieznany", kod)


def karta_mobilna(db: sqlite3.Connection, wynik: Wynik, jezyk: str | None = None) -> dict:
    """Krótka karta do pokazania na telefonie. Napisy w języku programu,
    powstają teraz — w chwili wyświetlenia."""
    from uslugi import pliki
    if wynik.typ == "egzemplarz":
        e = egzemplarze.pobierz(db, wynik.ident)
        miejsce = ""
        if e["rodzic_id"]:
            rodzic = egzemplarze.pobierz(db, e["rodzic_id"])
            miejsce = t("pole.zamontowany_w_wartosc", jezyk, nazwa=egzemplarze.nazwa_wyswietlana(rodzic),
                        pozycja=e["pozycja_montazu"] or "—")
        else:
            lok = egzemplarze.efektywna_lokalizacja(db, e["id"])
            miejsce = lokalizacje.sciezki(db).get(lok, "") if lok else t("lokalizacja.brak", jezyk)
        zdjecie = pliki.zdjecie_glowne(db, e["id"])
        model = " ".join(c for c in (e["producent"], e["model_nazwa"]) if c)
        pola = [
            (t("pole.model", jezyk), model),
            (t("pole.kategoria", jezyk), nazwa(e["kategoria_nazwy"], jezyk)),
            (t("pole.status", jezyk), nazwa(e["status_nazwy"], jezyk)),
            (t("pole.stan_wizualny", jezyk),
             etykieta("egzemplarz.stan_wizualny", e["stan_wizualny"], jezyk) if e["stan_wizualny"] else ""),
            (t("pole.miejsce", jezyk), miejsce),
            (t("pole.numer_seryjny", jezyk), e["numer_seryjny"] or ""),
            (t("pole.ilosc", jezyk), str(e["ilosc"]) if e["ilosc"] > 1 else ""),
            (t("pole.uwagi", jezyk), e["uwagi"] or ""),
        ]
        zamontowane = db.execute("SELECT id FROM egzemplarz WHERE rodzic_id = ?", (e["id"],)).fetchall()
        return {
            "typ": "egzemplarz", "kod": e["kod_inwentarzowy"], "nazwa": egzemplarze.nazwa_wyswietlana(e),
            "zdjec": len(pliki.zdjecia_egzemplarza(db, e["id"])),
            "status_kod": e["status_kod"],
            "pola": [{"etykieta": k, "wartosc": v} for k, v in pola if v],
            "zdjecie": base64.b64encode(zdjecie["miniatura"]).decode() if zdjecie is not None
            and zdjecie["miniatura"] else None,
            "lista_tytul": t("mobilny.zamontowane", jezyk) if zamontowane else "",
            "lista": [_pozycja(db, w[0], jezyk) for w in zamontowane],
        }
    if wynik.typ == "lokalizacja":
        l = lokalizacje.pobierz(db, wynik.ident)
        sciezka = lokalizacje.sciezki(db).get(l["id"], l["nazwa"])
        ids = [w[0] for w in db.execute("SELECT id FROM egzemplarz WHERE lokalizacja_id = ?", (l["id"],))]
        podlokalizacje = [w["nazwa"] for w in db.execute(
            "SELECT nazwa FROM lokalizacja WHERE rodzic_id = ? ORDER BY nazwa COLLATE NOCASE", (l["id"],))]
        pola = [(t("pole.typ", jezyk), etykieta("lokalizacja.typ", l["typ"], jezyk) if l["typ"] else ""),
                (t("eksport.kolumna.sciezka", jezyk), sciezka),
                (t("mobilny.podlokalizacje", jezyk), ", ".join(podlokalizacje))]
        lista = sorted((_pozycja(db, i, jezyk) for i in ids), key=lambda p: p["kod"])
        return {
            "typ": "lokalizacja", "kod": l["kod_etykiety"], "nazwa": l["nazwa"], "status_kod": None,
            "pola": [{"etykieta": k, "wartosc": v} for k, v in pola if v],
            "zdjecie": None,
            "lista_tytul": t("mobilny.zawartosc", jezyk, liczba=len(lista)),
            "lista": lista[:MAKS_EGZEMPLARZY_W_LOKALIZACJI],
        }
    return {"typ": "nieznany", "kod": wynik.kod, "nazwa": t("skaner.nieznany", jezyk, kod=wynik.kod or "—"),
            "pola": [], "zdjecie": None, "lista_tytul": "", "lista": [], "status_kod": None}


def _pozycja(db: sqlite3.Connection, egz_id: int, jezyk: str | None) -> dict:
    e = egzemplarze.pobierz(db, egz_id)
    return {"kod": e["kod_inwentarzowy"] or "", "nazwa": egzemplarze.nazwa_wyswietlana(e),
            "status": nazwa(e["status_nazwy"], jezyk), "status_kod": e["status_kod"]}


def json_karty(db: sqlite3.Connection, kod: str, jezyk: str | None = None) -> str:
    return json.dumps(karta_mobilna(db, rozpoznaj(db, kod), jezyk), ensure_ascii=False)
