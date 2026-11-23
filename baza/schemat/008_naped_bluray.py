"""NORNICA / VOLE — migracja 008: Blu-ray i HD DVD w rodzajach napędów optycznych.

Lista „Rodzaj napędu” kończyła się na DVD±RW. Wbudowane pole „rodzaj_napedu”
kategorii „napedy_optyczne” dostaje brakujące wartości na końcu listy.

Wartość, którą użytkownik dopisał już sam (wartosci_wlasne) i która jest teraz
wbudowana, znika z listy własnej — inaczej byłaby na liście dwa razy.
Wpisane w egzemplarzach i modelach wartości zostają bez zmian.

Wartości są ZAMROŻONE tutaj, a nie importowane z danych startowych.
"""
import json

NOWE = ["DVD-RAM", "HD DVD", "BD-ROM", "BD-ROM/DVD±RW (combo)", "BD-R/RE"]


def migruj(db) -> None:
    for id_, tekst in db.execute("SELECT id, szablon_atrybutow FROM kategoria "
                                 "WHERE kod = 'napedy_optyczne' AND szablon_atrybutow IS NOT NULL").fetchall():
        szablon = json.loads(tekst)
        zmieniono = False
        for pole in szablon:
            if pole.get("kod") != "rodzaj_napedu" or pole.get("typ") != "enum":
                continue
            wartosci = list(pole.get("wartosci", []))
            for wartosc in NOWE:
                if wartosc not in wartosci:
                    wartosci.append(wartosc)
                    zmieniono = True
            pole["wartosci"] = wartosci
            if pole.get("wartosci_wlasne"):
                wbudowane = {w.casefold() for w in wartosci}
                wlasne = [w for w in pole["wartosci_wlasne"] if w.casefold() not in wbudowane]
                if wlasne != pole["wartosci_wlasne"]:
                    zmieniono = True
                    if wlasne:
                        pole["wartosci_wlasne"] = wlasne
                    else:
                        del pole["wartosci_wlasne"]
        if zmieniono:
            db.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?",
                       (json.dumps(szablon, ensure_ascii=False), id_))
