# SPDX-License-Identifier: GPL-3.0-or-later
"""Eksport HTML: jeden samodzielny plik — podsumowanie kolekcji i tabele,
z miniaturami zdjęć głównych osadzonymi w pliku. Nadaje się do wysłania
innemu kolekcjonerowi i do wydruku (style @media print).

Każda wartość przechodzi przez html.escape — nazwa w rodzaju „<Amiga>”
albo „Atari & Co” nie zepsuje strony.
"""
from __future__ import annotations

import base64
from decimal import Decimal
from html import escape
from pathlib import Path

from i18n.tlumacz import t
from raporty.dane import KWOTA, LICZBA, Tabela
from wersja import WERSJA

_DZIESIETNY = {"pl": ",", "en": "."}

STYL = """
:root { --tlo:#F2F0EA; --panel:#FFFFFF; --tusz:#2A2925; --opis:#6E6A60; --linia:#D9D5CB; --akcent:#2F6B4F; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px; background: var(--tlo); color: var(--tusz);
       font: 14px/1.45 "DejaVu Sans", "Segoe UI", Arial, sans-serif; }
header { border-bottom: 3px solid var(--akcent); margin-bottom: 24px; padding-bottom: 12px; }
h1 { margin: 0; font-size: 26px; letter-spacing: .02em; }
.opis { color: var(--opis); }
.podsumowanie { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 28px; }
.blok { background: var(--panel); border: 1px solid var(--linia); border-radius: 6px; padding: 12px 16px; min-width: 180px; }
.blok h3 { margin: 0 0 6px; font-size: 13px; text-transform: uppercase; color: var(--opis); letter-spacing: .04em; }
.liczba { font-size: 28px; font-weight: bold; }
.blok table { border-collapse: collapse; }
.blok td { padding: 1px 12px 1px 0; }
h2 { font-size: 18px; margin: 32px 0 8px; }
.przewijanie { overflow-x: auto; }
table.dane { border-collapse: collapse; background: var(--panel); width: 100%; font-size: 12.5px; }
table.dane th { background: #E4E1D8; text-align: left; padding: 6px 8px; position: sticky; top: 0; }
table.dane td { padding: 5px 8px; border-top: 1px solid var(--linia); vertical-align: top; }
table.dane tr:nth-child(even) td { background: #FAF9F6; }
td.num { text-align: right; white-space: nowrap; }
td.dlugi { min-width: 280px; }
td.kod { font-weight: bold; white-space: nowrap; }
img.miniatura { width: 64px; height: auto; border-radius: 3px; display: block; }
footer { margin-top: 32px; color: var(--opis); font-size: 12px; }
@media print {
  body { background: #fff; padding: 0; font-size: 11px; }
  .blok { border-color: #bbb; }
  table.dane { font-size: 9.5px; }
  table.dane th { position: static; }
  tr { page-break-inside: avoid; }
}
"""


def _komorka(wartosc, typ: str, jezyk: str) -> str:
    if wartosc is None or wartosc == "":
        return "<td></td>"
    if typ == KWOTA and isinstance(wartosc, Decimal):
        return f'<td class="num">{escape(f"{wartosc:.2f}".replace(".", _DZIESIETNY.get(jezyk, ".")))}</td>'
    if typ == LICZBA:
        return f'<td class="num">{escape(str(wartosc))}</td>'
    return f"<td>{escape(str(wartosc))}</td>"


def _tabela_html(tabela: Tabela, jezyk: str) -> str:
    z_miniaturami = bool(tabela.miniatury) and any(tabela.miniatury)
    naglowki = ([f"<th>{escape(t('eksport.kolumna.zdjecie', jezyk))}</th>"] if z_miniaturami else []) + \
               [f"<th>{escape(k.naglowek)}</th>" for k in tabela.kolumny]
    wiersze = []
    for i, wiersz in enumerate(tabela.wiersze):
        komorki = []
        if z_miniaturami:
            dane = tabela.miniatury[i] if i < len(tabela.miniatury) else None
            komorki.append(f'<td><img class="miniatura" alt="" src="data:image/png;base64,'
                           f'{base64.b64encode(dane).decode()}"></td>' if dane else "<td></td>")
        for k, (wartosc, kolumna) in enumerate(zip(wiersz, tabela.kolumny)):
            komorka = _komorka(wartosc, kolumna.typ, jezyk)
            if kolumna.szerokosc >= 40 and komorka.startswith("<td>"):   # długi tekst: szersza kolumna, niższy wiersz
                komorka = komorka.replace("<td>", '<td class="dlugi">', 1)
            if k == 0 and tabela.kod in ("egzemplarze", "lokalizacje"):
                komorka = komorka.replace("<td>", '<td class="kod">', 1)
            komorki.append(komorka)
        wiersze.append(f"<tr>{''.join(komorki)}</tr>")
    pusto = f'<p class="opis">{escape(t("eksport.pusto", jezyk))}</p>' if not tabela.wiersze else ""
    return (f'<section><h2>{escape(tabela.nazwa)} ({len(tabela.wiersze)})</h2>{pusto}'
            f'<div class="przewijanie"><table class="dane"><thead><tr>{"".join(naglowki)}</tr></thead>'
            f'<tbody>{"".join(wiersze)}</tbody></table></div></section>' if tabela.wiersze
            else f'<section><h2>{escape(tabela.nazwa)} (0)</h2>{pusto}</section>')


def _blok_liczb(tytul: str, liczby: dict) -> str:
    wiersze = "".join(f"<tr><td>{escape(str(k))}</td><td class='num'><b>{v}</b></td></tr>"
                      for k, v in sorted(liczby.items(), key=lambda p: -p[1]))
    return f'<div class="blok"><h3>{escape(tytul)}</h3><table>{wiersze}</table></div>'


def zapisz(tabele: list[Tabela], podsumowanie: dict, sciezka: Path, jezyk: str, zakres: str) -> Path:
    j = jezyk
    bloki = [f'<div class="blok"><h3>{escape(t("eksport.tabela.egzemplarze", j))}</h3>'
             f'<div class="liczba">{podsumowanie["egzemplarze"]}</div></div>']
    if podsumowanie["statusy"]:
        bloki.append(_blok_liczb(t("pole.status", j), podsumowanie["statusy"]))
    if podsumowanie["kategorie"]:
        bloki.append(_blok_liczb(t("pole.kategoria", j), podsumowanie["kategorie"]))
    if podsumowanie["wartosc"]:
        wartosc = "".join(
            f"<tr><td>{escape(waluta)}</td><td class='num'><b>"
            f"{escape(f'{kwota:,.2f}'.replace(',', ' ').replace('.', _DZIESIETNY.get(j, '.')))}</b></td></tr>"
            for waluta, kwota in sorted(podsumowanie["wartosc"].items()))
        bloki.append(f'<div class="blok"><h3>{escape(t("eksport.wartosc", j))}</h3><table>{wartosc}</table></div>')
    tresc = f"""<!DOCTYPE html>
<html lang="{escape(j)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(t("eksport.tytul", j, nazwa=t("aplikacja.nazwa", j)))}</title>
<style>{STYL}</style>
</head>
<body>
<header>
<h1>{escape(t("eksport.tytul", j, nazwa=t("aplikacja.nazwa", j)))}</h1>
<div class="opis">{escape(zakres)} · {escape(t("eksport.wygenerowano", j, data=podsumowanie["wygenerowano"]))}</div>
</header>
<div class="podsumowanie">{"".join(bloki)}</div>
{"".join(_tabela_html(tabela, j) for tabela in tabele)}
<footer>{escape(t("aplikacja.nazwa", j))} {escape(WERSJA)} — {escape(t("aplikacja.opis", j))}</footer>
</body>
</html>
"""
    Path(sciezka).write_text(tresc, encoding="utf-8")
    return Path(sciezka)
