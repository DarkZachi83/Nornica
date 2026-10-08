# SPDX-License-Identifier: GPL-3.0-or-later
"""Budowanie zawartości drzewa — bez tkintera, więc testowalne bez ekranu.

Identyfikatory węzłów są stałe i pochodzą z bazy: "L12" (lokalizacja),
"E34" (egzemplarz), "BEZ" (egzemplarze bez lokalizacji). Dzięki temu stan
drzewa (rozwinięte węzły, zaznaczenie) przeżywa i odświeżenie danych,
i przebudowę okna po zmianie języka.

Tryby:
  lokalizacje — drzewo miejsc, w nich egzemplarze, w egzemplarzach części,
  montaz      — tylko egzemplarze: komputery na górze, w nich części.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from baza.enumy import etykieta
from baza.polaczenie import klucz_sortowania
from baza.repozytoria.egzemplarze import nazwa_wyswietlana
from i18n.tlumacz import nazwa, t

TRYBY = ("lokalizacje", "montaz")
WEZEL_BEZ_LOKALIZACJI = "BEZ"


@dataclass
class Wezel:
    iid: str
    rodzic: str            # "" = korzeń
    tekst: str
    wartosci: tuple = ()
    tagi: tuple = ()
    klucz: tuple = field(default=(), repr=False)


def iid_lokalizacji(lok_id: int) -> str:
    return f"L{lok_id}"


def iid_egzemplarza(egz_id: int) -> str:
    return f"E{egz_id}"


def rozbierz_iid(iid: str | None) -> tuple[str | None, int | None]:
    """"E34" -> ("E", 34); "BEZ" -> ("BEZ", None)."""
    if not iid:
        return None, None
    if iid == WEZEL_BEZ_LOKALIZACJI:
        return iid, None
    return iid[0], int(iid[1:])


def _tekst_egzemplarza(e) -> str:
    tekst = nazwa_wyswietlana(e)
    if e["ilosc"] > 1:
        tekst = f"{tekst} ×{e['ilosc']}"
    if e["pozycja_montazu"]:
        tekst = f"{tekst}  [{e['pozycja_montazu']}]"
    return tekst


def _pasuje(e, fraza: str) -> bool:
    pola = (nazwa_wyswietlana(e), e["kod_inwentarzowy"], e["numer_seryjny"],
            e["numer_czesci"], e["producent"], e["model_nazwa"])
    return any(fraza in (p or "").casefold() for p in pola)


def zbuduj_wezly(lokalizacje: list, egzemplarze: list, tryb: str,
                 filtr: str = "", jezyk: str | None = None) -> list[Wezel]:
    """Zwraca węzły w kolejności wstawiania (rodzic zawsze przed dzieckiem)."""
    fraza = (filtr or "").strip().casefold()
    lok_po_id = {l["id"]: l for l in lokalizacje}
    egz_po_id = {e["id"]: e for e in egzemplarze}

    # --- rodzic każdego węzła w wybranym trybie --------------------------------
    rodzic: dict[str, str] = {}
    for e in egzemplarze:
        iid = iid_egzemplarza(e["id"])
        if e["rodzic_id"] is not None and e["rodzic_id"] in egz_po_id:
            rodzic[iid] = iid_egzemplarza(e["rodzic_id"])
        elif tryb == "lokalizacje":
            rodzic[iid] = (iid_lokalizacji(e["lokalizacja_id"])
                           if e["lokalizacja_id"] in lok_po_id else WEZEL_BEZ_LOKALIZACJI)
        else:
            rodzic[iid] = ""
    if tryb == "lokalizacje":
        for l in lokalizacje:
            rodzic[iid_lokalizacji(l["id"])] = (iid_lokalizacji(l["rodzic_id"])
                                                if l["rodzic_id"] in lok_po_id else "")
        if any(r == WEZEL_BEZ_LOKALIZACJI for r in rodzic.values()):
            rodzic[WEZEL_BEZ_LOKALIZACJI] = ""

    # --- filtr: trafienia + wszyscy ich przodkowie -----------------------------
    widoczne = set(rodzic)
    if fraza:
        trafienia = {iid_egzemplarza(e["id"]) for e in egzemplarze if _pasuje(e, fraza)}
        if tryb == "lokalizacje":
            trafienia |= {iid_lokalizacji(l["id"]) for l in lokalizacje
                          if fraza in l["nazwa"].casefold()}
        widoczne = set()
        for iid in trafienia:
            krok = 0
            while iid and iid not in widoczne and krok < 128:
                widoczne.add(iid)
                iid = rodzic.get(iid, "")
                krok += 1

    # --- węzły ----------------------------------------------------------------
    wezly: dict[str, Wezel] = {}
    for l in lokalizacje:
        iid = iid_lokalizacji(l["id"])
        if tryb == "lokalizacje" and iid in widoczne:
            wezly[iid] = Wezel(iid, rodzic[iid], l["nazwa"],
                               (l["kod_etykiety"] or "", "",
                                etykieta("lokalizacja.typ", l["typ"], jezyk) if l["typ"] else ""),
                               ("lokalizacja",), (0, klucz_sortowania(l["nazwa"])))
    if WEZEL_BEZ_LOKALIZACJI in widoczne and WEZEL_BEZ_LOKALIZACJI in rodzic:
        wezly[WEZEL_BEZ_LOKALIZACJI] = Wezel(
            WEZEL_BEZ_LOKALIZACJI, "", t("lokalizacja.brak", jezyk), ("", "", ""),
            ("lokalizacja", "bez_lokalizacji"), (1, ()))
    for e in egzemplarze:
        iid = iid_egzemplarza(e["id"])
        if iid in widoczne:
            tekst = _tekst_egzemplarza(e)
            wezly[iid] = Wezel(iid, rodzic[iid], tekst,
                               (e["kod_inwentarzowy"] or "",
                                nazwa(e["status_nazwy"], jezyk),
                                nazwa(e["kategoria_nazwy"], jezyk)),
                               ("egzemplarz", f"status_{e['status_kod']}"),
                               (2, klucz_sortowania(tekst)))

    # --- kolejność: rodzic przed dziećmi, rodzeństwo posortowane --------------
    dzieci: dict[str, list[Wezel]] = {}
    for w in wezly.values():
        dzieci.setdefault(w.rodzic if w.rodzic in wezly else "", []).append(w)
    wynik: list[Wezel] = []

    def zejdz(iid: str, glebokosc: int) -> None:
        for w in sorted(dzieci.get(iid, []), key=lambda w: w.klucz):
            w.rodzic = iid
            wynik.append(w)
            if glebokosc < 128:
                zejdz(w.iid, glebokosc + 1)

    zejdz("", 0)
    return wynik
