# SPDX-License-Identifier: GPL-3.0-or-later
"""NORNICA / VOLE — punkt startowy.

Użycie:
    python nornica.py [--jezyk en|pl] [--baza ŚCIEŻKA] [--konsola] [--bez-powitania]

--konsola        tylko przygotowanie bazy i podsumowanie w terminalu, bez okna
--bez-powitania  pomija ekran powitalny
"""
from __future__ import annotations

import argparse
import sys

import konfiguracja
from baza import dane_startowe
from baza.migracje import biezaca_wersja, migruj
from baza.polaczenie import otworz_baze
from baza.repozytoria import ustawienia
from i18n.tlumacz import JEZYKI, t, ustaw_jezyk
from wyjatki import BladNornicy


def _policz(polaczenie, tabela: str) -> int:
    return polaczenie.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    # Pomoc argparse to narzędzie deweloperskie etapu 1 — celowo bez tłumaczeń.
    parser = argparse.ArgumentParser(prog="nornica")
    parser.add_argument("--jezyk", choices=JEZYKI)
    parser.add_argument("--baza")
    parser.add_argument("--konsola", action="store_true")
    parser.add_argument("--bez-powitania", action="store_true")
    argumenty = parser.parse_args(argv)

    try:
        konfiguracja.przygotuj_katalogi()
        import dziennik
        dziennik.wlacz(konfiguracja.plik_dziennika())
        sciezka = argumenty.baza or konfiguracja.sciezka_bazy()
        polaczenie = otworz_baze(sciezka)
        zastosowane, kopia = migruj(polaczenie, konfiguracja.katalog_kopii())
        dodane = dane_startowe.wypelnij(polaczenie)

        # Język: z argumentu (i zapamiętany), w przeciwnym razie z ustawień.
        if argumenty.jezyk:
            ustawienia.zapisz(polaczenie, "jezyk", argumenty.jezyk)
        ustaw_jezyk(ustawienia.pobierz(polaczenie, "jezyk"))

        if not argumenty.konsola:
            from gui.okno_glowne import OknoGlowne
            okno = OknoGlowne(polaczenie, pokaz_powitanie=not argumenty.bez_powitania)
            okno.mainloop()
            polaczenie.close()
            return 0

        print(f"{t('aplikacja.nazwa')} — {t('aplikacja.opis')}")
        print(t("konsola.baza", sciezka=sciezka))
        print(t("konsola.wersja_schematu", wersja=biezaca_wersja(polaczenie)))
        if zastosowane:
            print(t("konsola.migracje_zastosowane", lista=", ".join(map(str, zastosowane))))
        else:
            print(t("konsola.migracje_brak"))
        if kopia:
            print(t("konsola.kopia", sciezka=kopia))
        print(t("konsola.dane_startowe", liczba=dodane))
        print(t("konsola.podsumowanie",
                kategorie=_policz(polaczenie, "kategoria"),
                statusy=_policz(polaczenie, "status"),
                zlacza=_policz(polaczenie, "zlacze_typ"),
                waluty=_policz(polaczenie, "waluta")))
        polaczenie.close()
        return 0
    except BladNornicy as blad:
        print(blad.komunikat(), file=sys.stderr)
        _okno_bledu(blad.komunikat())
        return 1


def _okno_bledu(tekst: str) -> None:
    """Błąd startu pokazany także w okienku — program uruchomiony z menu
    systemu nie ma widocznego terminala."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        korzen = tk.Tk()
        korzen.withdraw()
        messagebox.showerror(t("aplikacja.nazwa"), tekst, parent=korzen)
        korzen.destroy()
    except Exception:   # noqa: BLE001 — brak ekranu: zostaje komunikat w terminalu
        pass


if __name__ == "__main__":
    sys.exit(main())
