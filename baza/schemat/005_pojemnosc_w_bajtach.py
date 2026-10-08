"""NORNICA / VOLE — migracja 005: pojemności w bajtach, jednostka do wyboru.

Pola pojemności miały jednostkę zaszytą na stałe (pamięć w KB, dyski w MB).
Atari 2600 ma 128 BAJTÓW RAM — w polu „KB” trzeba było wpisywać 0,125.
Teraz pojemność jest zapisywana w bajtach (typ pola „pojemnosc”), a formularz
pozwala wybrać jednostkę B / KB / MB / GB / TB.

Migracja:
  * przelicza wartości w atrybutach modeli i egzemplarzy (64 KB -> 65536),
  * zmienia kod i typ pola w szablonach kategorii (etykiety zostają, bez
    jednostki w nawiasie).

Definicje są ZAMROŻONE tutaj, a nie importowane z danych startowych —
migracja musi zawsze robić dokładnie to samo, nawet gdy dane startowe się
zmienią. 1 KB = 1024 B.
"""
import json

# stary kod pola: (nowy kod, mnożnik do bajtów)
ZMIANY = {
    "pamiec_kb": ("pamiec", 1024),
    "cache_kb": ("cache", 1024),
    "pojemnosc_mb": ("pojemnosc", 1024 ** 2),
    "max_ram_mb": ("max_ram", 1024 ** 2),
}


def _przelicz(atrybuty: dict) -> bool:
    zmieniono = False
    for stary, (nowy, mnoznik) in ZMIANY.items():
        if stary not in atrybuty:
            continue
        wartosc = atrybuty.pop(stary)
        zmieniono = True
        if nowy in atrybuty:                 # nowa wartość już jest — nie nadpisujemy
            continue
        try:
            atrybuty[nowy] = int(round(float(wartosc) * mnoznik))
        except (TypeError, ValueError):
            atrybuty[nowy] = wartosc         # coś nieliczbowego: zostawiamy, użytkownik poprawi
    return zmieniono


def migruj(db) -> None:
    for tabela in ("model", "egzemplarz"):
        for id_, tekst in db.execute(f"SELECT id, atrybuty FROM {tabela} WHERE atrybuty IS NOT NULL").fetchall():
            atrybuty = json.loads(tekst)
            if _przelicz(atrybuty):
                db.execute(f"UPDATE {tabela} SET atrybuty = ? WHERE id = ?",
                           (json.dumps(atrybuty, ensure_ascii=False, sort_keys=True) if atrybuty else None, id_))
    for id_, tekst in db.execute("SELECT id, szablon_atrybutow FROM kategoria "
                                 "WHERE szablon_atrybutow IS NOT NULL").fetchall():
        szablon = json.loads(tekst)
        zmieniono = False
        for pole in szablon:
            if pole.get("kod") in ZMIANY:
                pole["kod"] = ZMIANY[pole["kod"]][0]
                pole["typ"] = "pojemnosc"
                pole.pop("jednostka", None)
                zmieniono = True
        if zmieniono:
            db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?",
                       (json.dumps(szablon, ensure_ascii=False), id_))
