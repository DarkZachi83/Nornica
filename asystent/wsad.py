# SPDX-License-Identifier: GPL-3.0-or-later
"""Tryb wsadowy asystenta: kilka przedmiotów naraz, jedna linia = jeden przedmiot.

    Toshiba THM321000AS-70
    Samsung KMM5322200AW-6 × 3
    OKI MSC23136C-70BS10 x2

Na końcu linii opcjonalna ilość („× 3”, „x3”, „*3”). Asystent przechodzi linie
po kolei; użytkownik przegląda propozycje i dopiero wtedy program tworzy
modele (a na życzenie także egzemplarze w wybranej lokalizacji). Model
o tej samej nazwie i producencie w tej kategorii jest używany ponownie,
nie dublowany.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from asystent.propozycje import NAZWA, PRODUCENT, Wynik
from baza.repozytoria import modele, slowniki
from i18n.tlumacz import t
from uslugi import inwentarz

MAKS_POZYCJI = 30            # jedno przejście asystenta to ok. pół minuty na pozycję
MAKS_ILOSC = 99
_ILOSC = re.compile(r"\s+[x×*]\s*(\d{1,3})\s*$", re.I)


@dataclass
class Pozycja:
    tekst: str                       # linia bez ilości — także zapasowa nazwa modelu
    ilosc: int = 1
    wynik: Wynik | None = None
    blad: Exception | None = None
    zaznaczone: set[str] = field(default_factory=set)
    utworz: bool = True              # czy tworzyć tę pozycję


def parsuj(tekst: str) -> list[Pozycja]:
    """Linie z pola tekstowego -> pozycje. Puste linie i komentarze (#) pomijane."""
    pozycje = []
    for linia in (tekst or "").splitlines():
        linia = linia.strip()
        if not linia or linia.startswith("#"):
            continue
        ilosc = 1
        trafienie = _ILOSC.search(linia)
        if trafienie:
            ilosc = max(1, min(MAKS_ILOSC, int(trafienie.group(1))))
            linia = linia[:trafienie.start()].strip()
        if linia:
            pozycje.append(Pozycja(linia[:200], ilosc))
    return pozycje


def producent_z_linii(db, tekst: str) -> str:
    """Pierwsze słowo linii, jeśli to producent znany w bazie („Toshiba THM…”)."""
    pierwsze = (tekst.split() or [""])[0].casefold()
    for wiersz in slowniki.producenci(db):
        if wiersz["nazwa"].casefold() == pierwsze:
            return wiersz["nazwa"]
    return ""


def dane_modelu(db, pozycja: Pozycja, kategoria_id: int) -> dict:
    """Model z zaznaczonych propozycji; brakujące nazwa/producent — z linii."""
    wynik, kody = pozycja.wynik, pozycja.zaznaczone
    ogolne = {}
    for kod in (PRODUCENT, NAZWA):
        w = wynik.wartosc(kod) if wynik else None
        if w is not None and kod in kody and w.mozna_wstawic:
            ogolne[kod] = w.tekst
    producent = ogolne.get(PRODUCENT) or producent_z_linii(db, pozycja.tekst)
    nazwa = ogolne.get(NAZWA) or pozycja.tekst
    if producent and nazwa.casefold().startswith(producent.casefold() + " "):
        nazwa = nazwa[len(producent):].strip()          # „Toshiba THM…” -> producent + „THM…”
    adresy = list(dict.fromkeys(w.zrodlo.adres for w in (wynik.wartosci if wynik else [])
                                if w.kod in kody and w.zrodlo is not None))
    opis = ""
    if adresy:
        opis = t("asystent.dopisek_opisu", model=wynik.model) + "\n" + "\n".join(adresy)
    return {"kategoria_id": kategoria_id, "producent": producent, "nazwa": nazwa,
            "numer_czesci": pozycja.tekst if pozycja.tekst != nazwa else "",
            "zrodlo_url": adresy[0] if adresy else "", "opis": opis,
            "atrybuty": wynik.atrybuty(kody) if wynik else {}}


def _istniejacy_model(db, dane: dict) -> int | None:
    for wiersz in modele.w_kategorii(db, dane["kategoria_id"]):
        if (wiersz["nazwa"].casefold() == dane["nazwa"].casefold()
                and (wiersz["producent"] or "").casefold() == (dane["producent"] or "").casefold()):
            return wiersz["id"]
    return None


@dataclass
class Podsumowanie:
    modele_nowe: int = 0
    modele_istniejace: int = 0
    egzemplarze: int = 0
    blad: Exception | None = None
    nieudana: str = ""               # linia, na której zapis się przerwał


def utworz(db, pozycje: list[Pozycja], kategoria_id: int, lokalizacja_id: int | None = None,
           status_id: int | None = None, egzemplarze: bool = False) -> Podsumowanie:
    """Zapis zaznaczonych pozycji. Każda pozycja to osobna transakcja (model, potem
    egzemplarze): przy błędzie wcześniejsze zostają, a podsumowanie mówi, gdzie stanęło."""
    wynik = Podsumowanie()
    for pozycja in pozycje:
        if not pozycja.utworz:
            continue
        try:
            dane = dane_modelu(db, pozycja, kategoria_id)
            model_id = _istniejacy_model(db, dane)
            if model_id is None:
                model_id = inwentarz.zapisz_model(db, dane)
                wynik.modele_nowe += 1
            else:
                wynik.modele_istniejace += 1
            if egzemplarze:
                for _ in range(pozycja.ilosc):
                    inwentarz.zapisz_egzemplarz(db, {"model_id": model_id, "status_id": status_id,
                                                     "lokalizacja_id": lokalizacja_id})
                    wynik.egzemplarze += 1
        except Exception as blad:   # noqa: BLE001 — zatrzymanie z informacją, co już zapisano
            wynik.blad, wynik.nieudana = blad, pozycja.tekst
            break
    return wynik
