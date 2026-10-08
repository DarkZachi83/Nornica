# SPDX-License-Identifier: GPL-3.0-or-later
"""Inwentaryzacja: telefonem skanuje się po kolei to, co naprawdę stoi
w lokalizacji, a program porównuje to z bazą.

Zakres: lokalizacja razem ze wszystkimi podlokalizacjami (regał z półkami
i pudełkami). Oczekiwane są egzemplarze „luzem” — nie zamontowane — których
miejsce w bazie leży w tym zakresie. Części zamontowane w komputerze nie
muszą być skanowane osobno: zeskanowanie komputera (albo dowolnej części
w nim) oznacza, że cały zestaw jest na miejscu.

Wyniki skanów:
  na_miejscu      według bazy leży w sprawdzanym zakresie
  nie_na_miejscu  według bazy leży gdzie indziej albo nigdzie — tylko raport,
                  baza się nie zmienia (decyzja użytkownika: przenosi sam)
  brak            oczekiwany, a niezeskanowany — wpisywany przy zakończeniu

Inwentaryzacja niczego w bazie egzemplarzy nie zmienia. Zostaje po niej
sesja z wynikami: historia „kiedy ostatnio sprawdzono tę półkę”.

Teksty dla telefonu powstają w chwili odpowiedzi, w języku programu;
okno na komputerze formatuje surowe dane samo (zmiana języka na żywo).
"""
from __future__ import annotations

import sqlite3

from baza.polaczenie import transakcja
from baza.repozytoria import egzemplarze, lokalizacje
from i18n.tlumacz import t
from uslugi import skaner
from wyjatki import BladNornicy


# ---------------------------------------------------------------------------
# Zakres i oczekiwane
# ---------------------------------------------------------------------------
def zakres(db: sqlite3.Connection, lok_id: int) -> set[int]:
    return {lok_id} | lokalizacje.potomkowie(db, lok_id)


def oczekiwane(db: sqlite3.Connection, lok_id: int) -> list[int]:
    """Egzemplarze luzem (nie zamontowane) z miejscem w zakresie."""
    ids = sorted(zakres(db, lok_id))
    znaki = ", ".join("?" * len(ids))
    return [w[0] for w in db.execute(
        f"SELECT id FROM egzemplarz WHERE rodzic_id IS NULL AND lokalizacja_id IN ({znaki}) "
        "ORDER BY kod_inwentarzowy", ids)]


def _sesja(db: sqlite3.Connection, sesja_id: int, otwarta: bool = False) -> sqlite3.Row:
    wiersz = db.execute("SELECT * FROM inwentaryzacja WHERE id = ?", (sesja_id,)).fetchone()
    if wiersz is None:
        raise BladNornicy("blad.inwentaryzacja_brak")
    if otwarta and wiersz["zakonczono"] is not None:
        raise BladNornicy("blad.inwentaryzacja_zakonczona")
    if otwarta and wiersz["lokalizacja_id"] is None:
        raise BladNornicy("blad.inwentaryzacja_bez_lokalizacji")
    return wiersz


def _miejsce(db: sqlite3.Connection, egz_id: int, sciezki: dict | None = None) -> tuple[int | None, str | None]:
    """(lokalizacja efektywna, jej ścieżka) — dla zamontowanych: miejsce zestawu."""
    lok = egzemplarze.efektywna_lokalizacja(db, egz_id)
    if lok is None:
        return None, None
    sciezki = sciezki if sciezki is not None else lokalizacje.sciezki(db)
    return lok, sciezki.get(lok)


# ---------------------------------------------------------------------------
# Przebieg sesji
# ---------------------------------------------------------------------------
def rozpocznij(db: sqlite3.Connection, lok_id: int) -> int:
    lok = lokalizacje.pobierz(db, lok_id)
    if lok is None:
        raise BladNornicy("blad.inwentaryzacja_bez_lokalizacji")
    sciezka = lokalizacje.sciezki(db).get(lok_id, lok["nazwa"])
    with transakcja(db):
        return db.execute("INSERT INTO inwentaryzacja (lokalizacja_id, lokalizacja_nazwa) VALUES (?, ?)",
                          (lok_id, sciezka)).lastrowid


def skanuj(db: sqlite3.Connection, sesja_id: int, kod: str) -> dict:
    """Zapisuje skan i zwraca surowy wynik:
    {"wynik": na_miejscu | nie_na_miejscu | juz | lokalizacja | nieznany,
     "egzemplarz_id", "miejsce" (ścieżka wg bazy), "zamontowany_w" (id), "lokalizacja_id"}."""
    sesja = _sesja(db, sesja_id, otwarta=True)
    rozpoznany = skaner.rozpoznaj(db, kod)
    if rozpoznany.typ == "nieznany":
        return {"wynik": "nieznany", "kod": rozpoznany.kod}
    if rozpoznany.typ == "lokalizacja":
        return {"wynik": "lokalizacja", "lokalizacja_id": rozpoznany.ident,
                "w_zakresie": rozpoznany.ident in zakres(db, sesja["lokalizacja_id"])}
    egz_id = rozpoznany.ident
    poprzedni = db.execute("SELECT wynik, miejsce_w_bazie FROM inwentaryzacja_wynik "
                           "WHERE inwentaryzacja_id = ? AND egzemplarz_id = ?", (sesja_id, egz_id)).fetchone()
    rodzic = db.execute("SELECT rodzic_id FROM egzemplarz WHERE id = ?", (egz_id,)).fetchone()[0]
    if poprzedni is not None:
        return {"wynik": "juz", "egzemplarz_id": egz_id, "poprzedni": poprzedni["wynik"],
                "miejsce": poprzedni["miejsce_w_bazie"], "zamontowany_w": rodzic}
    lok, sciezka = _miejsce(db, egz_id)
    wynik = "na_miejscu" if lok is not None and lok in zakres(db, sesja["lokalizacja_id"]) else "nie_na_miejscu"
    with transakcja(db):
        kolejnosc = db.execute("SELECT coalesce(MAX(kolejnosc), 0) + 1 FROM inwentaryzacja_wynik "
                               "WHERE inwentaryzacja_id = ?", (sesja_id,)).fetchone()[0]
        db.execute("INSERT INTO inwentaryzacja_wynik (inwentaryzacja_id, egzemplarz_id, wynik, "
                   "miejsce_w_bazie, kolejnosc) VALUES (?, ?, ?, ?, ?)",
                   (sesja_id, egz_id, wynik, sciezka, kolejnosc))
    return {"wynik": wynik, "egzemplarz_id": egz_id, "miejsce": sciezka, "zamontowany_w": rodzic,
            "w_podlokalizacji": wynik == "na_miejscu" and lok != sesja["lokalizacja_id"]}


def _znalezione_korzenie(db: sqlite3.Connection, sesja_id: int) -> set[int]:
    """Egzemplarze luzem uznane za znalezione: zeskanowane same albo przez
    dowolną część w nich zamontowaną."""
    return {w[0] for w in db.execute(
        "SELECT v.korzen_id FROM inwentaryzacja_wynik r "
        "JOIN v_egzemplarz_lokalizacja v ON v.egzemplarz_id = r.egzemplarz_id "
        "WHERE r.inwentaryzacja_id = ? AND r.wynik = 'na_miejscu'", (sesja_id,))}


def stan(db: sqlite3.Connection, sesja_id: int) -> dict:
    """Liczby do paska postępu: oczekiwane, znalezione z nich, nie na miejscu."""
    sesja = _sesja(db, sesja_id)
    if sesja["zakonczono"] is None and sesja["lokalizacja_id"] is not None:
        spodziewane = set(oczekiwane(db, sesja["lokalizacja_id"]))
        znalezione = len(spodziewane & _znalezione_korzenie(db, sesja_id))
        brak = len(spodziewane) - znalezione
    else:
        spodziewane, znalezione = None, None
        brak = db.execute("SELECT COUNT(*) FROM inwentaryzacja_wynik WHERE inwentaryzacja_id = ? "
                          "AND wynik = 'brak'", (sesja_id,)).fetchone()[0]
    liczby = dict(db.execute("SELECT wynik, COUNT(*) FROM inwentaryzacja_wynik WHERE inwentaryzacja_id = ? "
                             "GROUP BY wynik", (sesja_id,)).fetchall())
    return {"sesja": sesja_id, "lokalizacja": sesja["lokalizacja_nazwa"],
            "lokalizacja_id": sesja["lokalizacja_id"],
            "rozpoczeto": sesja["rozpoczeto"], "zakonczono": sesja["zakonczono"],
            "oczekiwane": len(spodziewane) if spodziewane is not None else None,
            "znalezione": znalezione if znalezione is not None else liczby.get("na_miejscu", 0),
            "na_miejscu": liczby.get("na_miejscu", 0),
            "nie_na_miejscu": liczby.get("nie_na_miejscu", 0), "brak": brak}


def zakoncz(db: sqlite3.Connection, sesja_id: int) -> dict:
    """Wpisuje brakujące (stan z tej chwili) i zamyka sesję. Zwraca raport."""
    sesja = _sesja(db, sesja_id, otwarta=True)
    brakujace = [e for e in oczekiwane(db, sesja["lokalizacja_id"])
                 if e not in _znalezione_korzenie(db, sesja_id)]
    sciezki = lokalizacje.sciezki(db)
    with transakcja(db):
        kolejnosc = db.execute("SELECT coalesce(MAX(kolejnosc), 0) FROM inwentaryzacja_wynik "
                               "WHERE inwentaryzacja_id = ?", (sesja_id,)).fetchone()[0]
        for numer, egz_id in enumerate(brakujace, start=kolejnosc + 1):
            db.execute("INSERT INTO inwentaryzacja_wynik (inwentaryzacja_id, egzemplarz_id, wynik, "
                       "miejsce_w_bazie, kolejnosc, skanowano) VALUES (?, ?, 'brak', ?, ?, NULL)",
                       (sesja_id, egz_id, _miejsce(db, egz_id, sciezki)[1], numer))
        db.execute("UPDATE inwentaryzacja SET zakonczono = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
                   (sesja_id,))
    return raport(db, sesja_id)


def anuluj(db: sqlite3.Connection, sesja_id: int) -> None:
    with transakcja(db):
        db.execute("DELETE FROM inwentaryzacja WHERE id = ?", (sesja_id,))


def usun(db: sqlite3.Connection, sesja_id: int) -> None:
    """Usunięcie sesji z historii (okno na komputerze)."""
    anuluj(db, sesja_id)


# ---------------------------------------------------------------------------
# Raport i historia
# ---------------------------------------------------------------------------
def pozycje(db: sqlite3.Connection, sesja_id: int) -> list[dict]:
    """Wszystkie wyniki sesji z danymi egzemplarza; najnowsze skany pierwsze,
    brakujące na końcu."""
    wynik = []
    for w in db.execute("SELECT egzemplarz_id, wynik, miejsce_w_bazie, skanowano FROM inwentaryzacja_wynik "
                        "WHERE inwentaryzacja_id = ? "
                        "ORDER BY wynik = 'brak', CASE WHEN wynik = 'brak' THEN kolejnosc ELSE -kolejnosc END",
                        (sesja_id,)):
        e = egzemplarze.pobierz(db, w["egzemplarz_id"])
        rodzic = egzemplarze.pobierz(db, e["rodzic_id"]) if e["rodzic_id"] else None
        wynik.append({"egzemplarz_id": e["id"], "kod": e["kod_inwentarzowy"] or "",
                      "nazwa": egzemplarze.nazwa_wyswietlana(e), "wynik": w["wynik"],
                      "zamontowany_w": egzemplarze.nazwa_wyswietlana(rodzic) if rodzic else None,
                      "miejsce": w["miejsce_w_bazie"], "skanowano": w["skanowano"],
                      "status_kod": e["status_kod"], "status_nazwy": e["status_nazwy"]})
    return wynik


def raport(db: sqlite3.Connection, sesja_id: int) -> dict:
    return {"stan": stan(db, sesja_id), "pozycje": pozycje(db, sesja_id)}


def sesje(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT i.*, "
        "  (SELECT COUNT(*) FROM inwentaryzacja_wynik r WHERE r.inwentaryzacja_id = i.id "
        "     AND r.wynik = 'na_miejscu') AS na_miejscu, "
        "  (SELECT COUNT(*) FROM inwentaryzacja_wynik r WHERE r.inwentaryzacja_id = i.id "
        "     AND r.wynik = 'nie_na_miejscu') AS nie_na_miejscu, "
        "  (SELECT COUNT(*) FROM inwentaryzacja_wynik r WHERE r.inwentaryzacja_id = i.id "
        "     AND r.wynik = 'brak') AS brak "
        "FROM inwentaryzacja i ORDER BY i.rozpoczeto DESC, i.id DESC").fetchall()


# ---------------------------------------------------------------------------
# Telefon: zapytanie z serwera (wątek interfejsu, przez Most)
# ---------------------------------------------------------------------------
def _tekst_skanu(db: sqlite3.Connection, w: dict, jezyk: str | None) -> str:
    rodzaj = w["wynik"]
    if rodzaj == "nieznany":
        return t("skaner.nieznany", jezyk, kod=w.get("kod") or "—")
    if rodzaj == "lokalizacja":
        l = lokalizacje.pobierz(db, w["lokalizacja_id"])
        return t("inw.tel.lokalizacja_w" if w["w_zakresie"] else "inw.tel.lokalizacja_poza", jezyk,
                 nazwa=l["nazwa"])
    if rodzaj == "juz":
        if w.get("poprzedni") == "nie_na_miejscu":       # powtórka nie zmienia koloru ani treści
            return t("inw.tel.juz", jezyk) + " " + _tekst_skanu(db, {**w, "wynik": "nie_na_miejscu"}, jezyk)
        return t("inw.tel.juz", jezyk)
    if w.get("zamontowany_w") and rodzaj == "na_miejscu":
        rodzic = egzemplarze.pobierz(db, w["zamontowany_w"])
        return t("inw.tel.zamontowany", jezyk, nazwa=egzemplarze.nazwa_wyswietlana(rodzic))
    if rodzaj == "na_miejscu":
        return t("inw.tel.podlokalizacja", jezyk, miejsce=w["miejsce"]) if w.get("w_podlokalizacji") \
            else t("inw.tel.na_miejscu", jezyk)
    return t("inw.tel.nie_na_miejscu", jezyk, miejsce=w["miejsce"]) if w.get("miejsce") \
        else t("inw.tel.bez_miejsca", jezyk)


def _pozycja_tel(p: dict, jezyk: str | None) -> dict:
    if p["wynik"] == "nie_na_miejscu" and p["miejsce"]:
        opis = t("inw.tel.bylo", jezyk, miejsce=p["miejsce"])
    elif p["zamontowany_w"]:
        opis = t("inw.tel.w_zestawie", jezyk, nazwa=p["zamontowany_w"])
    else:
        opis = ""
    return {"kod": p["kod"], "nazwa": p["nazwa"], "wynik": p["wynik"], "opis": opis}


def _stan_tel(db: sqlite3.Connection, sesja_id: int, jezyk: str | None) -> dict:
    s = stan(db, sesja_id)
    return {**s, "postep": t("inw.tel.postep", jezyk, znalezione=s["znalezione"], oczekiwane=s["oczekiwane"])
            if s["oczekiwane"] is not None else "",
            "pozycje": [_pozycja_tel(p, jezyk) for p in pozycje(db, sesja_id) if p["wynik"] != "brak"][:40]}


def obsluga_telefonu(db: sqlite3.Connection, dane: dict, jezyk: str | None = None) -> dict:
    """Zapytanie strony telefonu: {"akcja": start|skan|stan|koniec|anuluj, "kod", "sesja"}."""
    akcja = dane.get("akcja")
    if akcja == "start":
        rozpoznany = skaner.rozpoznaj(db, dane.get("kod", ""))
        if rozpoznany.typ != "lokalizacja":
            raise BladNornicy("blad.inwentaryzacja_zacznij_od_lokalizacji")
        return _stan_tel(db, rozpocznij(db, rozpoznany.ident), jezyk)
    try:
        sesja_id = int(dane.get("sesja"))
    except (TypeError, ValueError):
        raise BladNornicy("blad.inwentaryzacja_brak") from None
    if akcja == "skan":
        w = skanuj(db, sesja_id, dane.get("kod", ""))
        # powtórka wygląda jak pierwszy skan (kolor), z dopiskiem „już zeskanowany”
        klasa = w.get("poprzedni") or w["wynik"]
        odpowiedz = {"skan": {"wynik": klasa, "tekst": _tekst_skanu(db, w, jezyk)},
                     "stan": _stan_tel(db, sesja_id, jezyk)}
        if "egzemplarz_id" in w:
            e = egzemplarze.pobierz(db, w["egzemplarz_id"])
            odpowiedz["skan"].update({"kod": e["kod_inwentarzowy"], "nazwa": egzemplarze.nazwa_wyswietlana(e),
                                      "poprzedni": w.get("poprzedni")})
        return odpowiedz
    if akcja == "stan":
        return {"stan": _stan_tel(db, sesja_id, jezyk)}
    if akcja == "koniec":
        r = zakoncz(db, sesja_id)
        grupy = {k: [_pozycja_tel(p, jezyk) for p in r["pozycje"] if p["wynik"] == k]
                 for k in ("brak", "nie_na_miejscu", "na_miejscu")}
        return {"raport": {**r["stan"], "grupy": grupy,
                           "podsumowanie": t("inw.tel.podsumowanie", jezyk, znalezione=r["stan"]["na_miejscu"],
                                             nie_na_miejscu=r["stan"]["nie_na_miejscu"], brak=r["stan"]["brak"])}}
    if akcja == "anuluj":
        anuluj(db, sesja_id)
        return {"anulowano": True}
    raise BladNornicy("blad.inwentaryzacja_brak")

