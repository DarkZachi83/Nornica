"""NORNICA / VOLE — migracja 007: napięcie rdzenia procesora jako widełki.

Dokumentacja procesorów podaje napięcie rdzenia jako zakres (Core 2 Duo E4300:
1,225–1,325 V), a pole było liczbą dziesiętną — zakresu nie dało się wpisać.
Wbudowane pole „napiecie_v” kategorii „procesory” dostaje typ „zakres”.

Wpisane wartości zostają bez zmian: pojedyncza liczba jest poprawnym zakresem
z jednym końcem. Zmienia się tylko szablon kategorii — i tylko wtedy, gdy pole
nadal jest liczbą dziesiętną (gdyby użytkownik zmienił je sam, zostaje).

Definicje są ZAMROŻONE tutaj, a nie importowane z danych startowych.
"""
import json


def migruj(db) -> None:
    for id_, tekst in db.execute("SELECT id, szablon_atrybutow FROM kategoria "
                                 "WHERE kod = 'procesory' AND szablon_atrybutow IS NOT NULL").fetchall():
        szablon = json.loads(tekst)
        zmieniono = False
        for pole in szablon:
            if pole.get("kod") == "napiecie_v" and pole.get("typ") == "real":
                pole["typ"] = "zakres"
                zmieniono = True
        if zmieniono:
            db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?",
                       (json.dumps(szablon, ensure_ascii=False), id_))
