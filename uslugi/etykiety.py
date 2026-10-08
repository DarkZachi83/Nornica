# SPDX-License-Identifier: GPL-3.0-or-later
"""Etykiety z kodami QR: macierz kodu, formaty naklejek, arkusze PDF.

Kod QR zawiera sam kod inwentarzowy (np. NOR-000123) albo kod lokalizacji
(LOC-0012). Czytnik USB „wpisuje” go jak klawiatura, a program rozpozna,
czy to egzemplarz, czy pudełko (etap 7).

Tryby zapisu (ten sam układ etykiety):
  * obraz (domyślny) — najprostszy możliwy PDF: na stronie jeden obraz JPEG,
    zapisany własnym kodem (zapisz_pdf_z_obrazow). Zgłoszenie z Linuksa:
    drukarka wysuwała pustą kartkę i dla PDF wektorowego, i dla PDF z obrazem
    zapisanego przez reportlab — a zrzut ekranu drukowała bez problemu,
  * png — plik PNG na stronę: dokładnie ta droga, która zadziałała,
  * wektor — reportlab, czcionka osadzona; najostrzejszy, gdy drukarka go przyjmie.

Wymiary formatów A4 pochodzą z kart katalogowych producentów naklejek.
Drukarki różnią się marginesami, dlatego okno ma przesunięcie X/Y do
kalibracji — przed drukiem na naklejkach warto zrobić próbę na zwykłej kartce
i przyłożyć ją do arkusza pod światło.
"""
from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from baza.repozytoria import egzemplarze, lokalizacje
from wyjatki import BladNornicy

MM = 72 / 25.4      # punkty PDF na milimetr


# ---------------------------------------------------------------------------
# Kod QR
# ---------------------------------------------------------------------------
def macierz_qr(tekst: str) -> list[list[bool]]:
    """Macierz modułów kodu QR (bez marginesu). Poziom korekcji M — kod
    przeżyje drobne zarysowanie naklejki."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError:
        raise BladNornicy("blad.brak_qrcode") from None
    kod = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    kod.add_data(tekst)
    kod.make(fit=True)
    return [list(wiersz) for wiersz in kod.get_matrix()]


# ---------------------------------------------------------------------------
# Formaty naklejek
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Format:
    kod: str
    nazwa: str                     # nazwa handlowa — nie tłumaczona
    rodzaj: str                    # "a4" (arkusz) | "rolka" (drukarka etykiet: strona = etykieta)
    szerokosc: float               # wymiary etykiety, mm
    wysokosc: float
    kolumny: int = 1
    wiersze: int = 1
    lewy: float = 0.0              # margines arkusza, mm
    gorny: float = 0.0
    odstep_x: float = 0.0          # przerwa między etykietami, mm
    odstep_y: float = 0.0

    @property
    def na_stronie(self) -> int:
        return self.kolumny * self.wiersze

    @property
    def strona(self) -> tuple[float, float]:
        return (210.0, 297.0) if self.rodzaj == "a4" else (self.szerokosc, self.wysokosc)

    def etykieta(self, numer: int) -> tuple[float, float]:
        """Lewy górny róg etykiety o numerze 0..na_stronie-1 (mm od lewego górnego rogu strony)."""
        kolumna, wiersz = numer % self.kolumny, numer // self.kolumny
        return (self.lewy + kolumna * (self.szerokosc + self.odstep_x),
                self.gorny + wiersz * (self.wysokosc + self.odstep_y))


FORMATY: dict[str, Format] = {f.kod: f for f in (
    # --- arkusze A4 ---------------------------------------------------------
    Format("avery_3474", "Avery Zweckform 3474", "a4", 70, 37, 3, 8, 0, 0.5),
    Format("avery_l7160", "Avery L7160", "a4", 63.5, 38.1, 3, 7, 7.2, 15.15, 2.5, 0),
    Format("avery_l7159", "Avery L7159", "a4", 63.5, 33.9, 3, 8, 7.2, 12.9, 2.5, 0),
    Format("avery_l7163", "Avery L7163", "a4", 99.1, 38.1, 2, 7, 4.65, 15.15, 2.5, 0),
    Format("avery_l7651", "Avery L7651", "a4", 38.1, 21.2, 5, 13, 4.7, 10.7, 2.5, 0),
    Format("avery_3657", "Avery Zweckform 3657", "a4", 48.5, 25.4, 4, 10, 8, 21.5, 0, 0),
    # --- drukarki etykiet: jedna etykieta = jedna strona PDF ------------------
    Format("brother_dk11209", "Brother DK-11209", "rolka", 62, 29),
    Format("brother_dk11204", "Brother DK-11204", "rolka", 54, 17),
    Format("brother_dk22205", "Brother DK-22205 (62 × 30 mm)", "rolka", 62, 30),
    Format("dymo_11354", "Dymo 11354", "rolka", 57, 32),
    Format("dymo_11355", "Dymo 11355", "rolka", 51, 19),
    Format("dymo_99012", "Dymo 99012", "rolka", 89, 36),
)}


def format_wlasny(szerokosc: float, wysokosc: float, kolumny: int, wiersze: int,
                  lewy: float, gorny: float, odstep_x: float, odstep_y: float) -> Format:
    """Format podany przez użytkownika: arkusz A4 albo, przy 1×1 bez marginesów, rolka."""
    rolka = kolumny == 1 and wiersze == 1 and lewy == 0 and gorny == 0
    f = Format("wlasny", "", "rolka" if rolka else "a4", szerokosc, wysokosc, kolumny, wiersze,
               lewy, gorny, odstep_x, odstep_y)
    sprawdz_format(f)
    return f


def sprawdz_format(f: Format) -> None:
    """Etykiety muszą mieścić się na stronie (z tolerancją 0,5 mm)."""
    if min(f.szerokosc, f.wysokosc) <= 5 or f.kolumny < 1 or f.wiersze < 1:
        raise BladNornicy("blad.zly_format_etykiet")
    szer_strony, wys_strony = f.strona
    prawa = f.lewy + f.kolumny * f.szerokosc + (f.kolumny - 1) * f.odstep_x
    dolna = f.gorny + f.wiersze * f.wysokosc + (f.wiersze - 1) * f.odstep_y
    if prawa > szer_strony + 0.5 or dolna > wys_strony + 0.5:
        raise BladNornicy("blad.zly_format_etykiet")


# ---------------------------------------------------------------------------
# Treść etykiet
# ---------------------------------------------------------------------------
@dataclass
class Etykieta:
    kod: str
    nazwa: str
    dopisek: str = ""              # druga linia: kategoria albo ścieżka lokalizacji


def etykiety_egzemplarzy(db: sqlite3.Connection, identyfikatory: list[int]) -> list[Etykieta]:
    from i18n.tlumacz import nazwa
    wynik = []
    for egz_id in identyfikatory:
        e = egzemplarze.pobierz(db, egz_id)
        if e is not None and e["kod_inwentarzowy"]:
            wynik.append(Etykieta(e["kod_inwentarzowy"], egzemplarze.nazwa_wyswietlana(e),
                                  nazwa(e["kategoria_nazwy"])))
    return wynik


def etykiety_lokalizacji(db: sqlite3.Connection, identyfikatory: list[int]) -> list[Etykieta]:
    sciezki = lokalizacje.sciezki(db)
    wynik = []
    for lok_id in identyfikatory:
        l = lokalizacje.pobierz(db, lok_id)
        if l is not None and l["kod_etykiety"]:
            sciezka = sciezki.get(lok_id, l["nazwa"])
            dopisek = sciezka.rsplit(" › ", 1)[0] if " › " in sciezka else ""
            wynik.append(Etykieta(l["kod_etykiety"], l["nazwa"], dopisek))
    return wynik


def zakres(db: sqlite3.Connection, lok_id: int | None, z_lokalizacjami: bool) -> list[Etykieta]:
    """Etykiety dla lokalizacji z podlokalizacjami (lok_id) albo całej kolekcji (None).
    Egzemplarze według efektywnej lokalizacji — z częściami zamontowanymi w środku."""
    if lok_id is None:
        lokacje = [l["id"] for l in lokalizacje.wszystkie(db)]
        egz = [w[0] for w in db.execute("SELECT id FROM egzemplarz")]
    else:
        lokacje = [lok_id, *lokalizacje.potomkowie(db, lok_id)]
        znaki = ", ".join("?" * len(lokacje))
        egz = [w[0] for w in db.execute(
            f"SELECT egzemplarz_id FROM v_egzemplarz_lokalizacja WHERE lokalizacja_id IN ({znaki})", lokacje)]
    etykiety = etykiety_lokalizacji(db, lokacje) if z_lokalizacjami else []
    return etykiety + sorted(etykiety_egzemplarzy(db, egz), key=lambda e: e.kod)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
_CZCIONKI = {
    "linux": ["/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
    "win": ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/calibri.ttf"],
    "darwin": ["/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"],
}


def _pliki_czcionek() -> tuple[str | None, str | None]:
    """Ścieżki (zwykła, pogrubiona) czcionki TTF z polskimi znakami albo (None, None)."""
    system = "win" if sys.platform.startswith("win") else sys.platform if sys.platform == "darwin" else "linux"
    for sciezka in _CZCIONKI[system]:
        if Path(sciezka).exists():
            pogrubiona = sciezka.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace(
                "arial.ttf", "arialbd.ttf").replace("Arial.ttf", "Arial Bold.ttf").replace(
                "Regular", "Bold")
            return sciezka, pogrubiona if Path(pogrubiona).exists() else sciezka
    return None, None


def _czcionki() -> tuple[str, str]:
    """(zwykła, pogrubiona). Czcionki wbudowane w PDF (Helvetica) nie mają polskich
    liter — „ł” czy „ą” wyszłyby jako czarne kwadraty — więc szukamy czcionki TTF
    w systemie i osadzamy ją w pliku."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "NornicaSans" in pdfmetrics.getRegisteredFontNames():
        return "NornicaSans", "NornicaSans-Bold"
    zwykla, gruba = _pliki_czcionek()
    if zwykla is None:
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("NornicaSans", zwykla))
    pdfmetrics.registerFont(TTFont("NornicaSans-Bold", gruba))
    return "NornicaSans", "NornicaSans-Bold"


def _bez_polskich(tekst: str) -> str:
    """Ostatnia deska ratunku, gdy w systemie nie ma żadnej czcionki TTF."""
    import unicodedata
    tekst = tekst.replace("ł", "l").replace("Ł", "L")
    return "".join(z for z in unicodedata.normalize("NFD", tekst) if not unicodedata.combining(z))


def _przytnij(tekst: str, mierz, czcionka: str, rozmiar: float, szerokosc: float) -> str:
    if mierz(tekst, czcionka, rozmiar) <= szerokosc:
        return tekst
    while tekst and mierz(tekst + "…", czcionka, rozmiar) > szerokosc:
        tekst = tekst[:-1]
    return tekst.rstrip() + "…"


def _zawin(tekst: str, mierz, czcionka: str, rozmiar: float, szerokosc: float, linii: int) -> list[str]:
    """Zawija tekst po słowach do zadanej liczby linii; ostatnia w razie potrzeby z „…”."""
    wynik, biezaca = [], ""
    slowa = tekst.split()
    for i, slowo in enumerate(slowa):
        proba = f"{biezaca} {slowo}".strip()
        if mierz(proba, czcionka, rozmiar) <= szerokosc or not biezaca:
            biezaca = proba
            continue
        wynik.append(biezaca)
        biezaca = slowo
        if len(wynik) == linii - 1:            # ostatnia linia: reszta tekstu, przycięta
            biezaca = " ".join(slowa[i:])
            break
    wynik.append(biezaca)
    return [_przytnij(linia, mierz, czcionka, rozmiar, szerokosc) for linia in wynik[:linii]]


def _rysuj_etykiete(plotno, etykieta: Etykieta, x: float, y_gora: float, f: Format) -> None:
    """Etykieta: kod QR po lewej, tekst po prawej. Współrzędne w punktach,
    y_gora = górna krawędź etykiety (y liczone od dołu strony, jak w PDF).
    Płótno dostarcza czcionki i pomiar tekstu — układ jest wspólny dla trybów."""
    zwykla, gruba = plotno.czcionki
    mierz = plotno.szerokosc_tekstu
    szer, wys = f.szerokosc * MM, f.wysokosc * MM
    wciecie = min(2.0 * MM, wys * 0.08)
    # --- kod QR: kwadrat o boku wysokości etykiety minus wcięcia
    macierz = macierz_qr(etykieta.kod)
    margines_modulow = 2          # strefa ciszy; norma mówi 4, ale wokół i tak jest biała naklejka
    bok = min(wys - 2 * wciecie, szer * 0.42)
    modul = bok / (len(macierz) + 2 * margines_modulow)
    x0 = x + wciecie + margines_modulow * modul
    y0 = y_gora - wciecie - margines_modulow * modul
    plotno.kod_qr(macierz, x0, y0, modul)
    # --- tekst
    tx = x + wciecie + bok + wciecie
    szer_tekstu = x + szer - wciecie - tx
    if szer_tekstu < 8 * MM:
        return                    # bardzo wąska etykieta: sam kod QR
    # Kod to najważniejszy napis — nigdy nie jest ucinany: czcionka maleje, aż się zmieści
    rozmiar_kodu = max(6.0, min(11.0, wys * 0.22))
    while rozmiar_kodu > 4.5 and mierz(etykieta.kod, gruba, rozmiar_kodu) > szer_tekstu:
        rozmiar_kodu -= 0.25
    rozmiar = max(5.0, min(rozmiar_kodu * 0.85, 9.0))
    nazwa, dopisek = etykieta.nazwa, etykieta.dopisek
    if plotno.bez_polskich:
        nazwa, dopisek = _bez_polskich(nazwa), _bez_polskich(dopisek)
    # ile linii tekstu zmieści się pod kodem: nazwa do 2 linii, potem dopisek
    miejsce = (wys - 2 * wciecie - rozmiar_kodu * 1.25) / (rozmiar * 1.25)
    linii_nazwy = 2 if miejsce >= 2.5 else 1
    linie = [(gruba, rozmiar_kodu, etykieta.kod)]
    linie += [(zwykla, rozmiar, l) for l in _zawin(nazwa, mierz, zwykla, rozmiar, szer_tekstu, linii_nazwy)]
    if dopisek and miejsce >= len(linie) - 1 + 1.2:
        linie.append((zwykla, rozmiar * 0.9, dopisek))
    wysokosc_tekstu = sum(r * 1.25 for _, r, _ in linie)
    y = y_gora - (wys - wysokosc_tekstu) / 2
    for czcionka, wielkosc, tekst in linie:
        y -= wielkosc * 1.1
        plotno.tekst(tx, y, _przytnij(tekst, mierz, czcionka, wielkosc, szer_tekstu), czcionka, wielkosc)
        y -= wielkosc * 0.15


# ---------------------------------------------------------------------------
# Płótna: ten sam układ etykiety, różne sposoby zapisu
# ---------------------------------------------------------------------------
TRYBY = ("obraz", "obraz600", "png", "wektor")
DPI_TRYBU = {"obraz": 300, "obraz600": 600, "png": 300}


def _przebiegi(wiersz: list[bool]):
    """Ciągi sąsiednich ciemnych modułów w wierszu: (początek, długość)."""
    k = 0
    while k < len(wiersz):
        if wiersz[k]:
            poczatek = k
            while k < len(wiersz) and wiersz[k]:
                k += 1
            yield poczatek, k - poczatek
        else:
            k += 1


class _PlotnoWektorowe:
    """PDF wektorowy (reportlab): najostrzejszy i najmniejszy. Czcionka TTF
    osadzona, kod QR jako JEDNA ścieżka. Nie każda drukarka sobie z nim radzi."""

    def __init__(self, sciezka: str, strona_pt: tuple[float, float]):
        try:
            from reportlab.pdfgen.canvas import Canvas
        except ImportError:
            raise BladNornicy("blad.brak_reportlab") from None
        self.czcionki = _czcionki()
        self.bez_polskich = self.czcionki[0].startswith("Helvetica")
        self.pdf = Canvas(sciezka, pagesize=strona_pt)
        self.pdf.setTitle("NORNICA / VOLE")

    @staticmethod
    def szerokosc_tekstu(tekst: str, czcionka: str, rozmiar: float) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(tekst, czcionka, rozmiar)

    def kod_qr(self, macierz, x0: float, y_gora: float, modul: float) -> None:
        sciezka = self.pdf.beginPath()
        for r, wiersz in enumerate(macierz):
            for k, dlugosc in _przebiegi(wiersz):
                # nakładka 0,1 pt między wierszami: bez białych szczelin po rasteryzacji
                sciezka.rect(x0 + k * modul, y_gora - (r + 1) * modul, dlugosc * modul, modul + 0.1)
        self.pdf.setFillColorRGB(0, 0, 0)
        # Reguła NIEZEROWA: domyślna w reportlab parzysto-nieparzysta wycina nakładki
        # między wierszami — wychodzą białe linie, przez które kod się nie skanuje.
        from reportlab.pdfgen.canvas import FILL_NON_ZERO   # stała z biblioteki, nie przepisana z pamięci
        self.pdf.drawPath(sciezka, stroke=0, fill=1, fillMode=FILL_NON_ZERO)

    def tekst(self, x: float, y: float, tekst: str, czcionka: str, rozmiar: float) -> None:
        self.pdf.setFillColorRGB(0, 0, 0)
        self.pdf.setFont(czcionka, rozmiar)
        self.pdf.drawString(x, y, tekst)

    def obrys(self, x: float, y: float, szer: float, wys: float) -> None:
        self.pdf.setLineWidth(0.25)
        self.pdf.setStrokeColorRGB(0.6, 0.6, 0.6)
        self.pdf.rect(x, y, szer, wys, stroke=1, fill=0)

    def nowa_strona(self) -> None:
        self.pdf.showPage()

    def zakoncz(self) -> list[Path]:
        self.pdf.showPage()
        self.pdf.save()
        return [Path(self.pdf._filename)]


class _PlotnoRastrowe:
    """Każda strona to obraz w rozdzielczości drukarki, rysowany przez Pillow.
    Zapis: najprostszy możliwy PDF (zapisz_pdf_z_obrazow) albo pliki PNG.
    Moduły kodu QR mają całkowitą liczbę pikseli — ostre krawędzie."""

    def __init__(self, strona_pt: tuple[float, float], dpi: int):
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        except ImportError:
            raise BladNornicy("blad.brak_pillow_raster") from None
        self.strona_pt = strona_pt
        self.dpi = dpi
        self.skala = dpi / 72.0
        self.rozmiar_px = (round(strona_pt[0] * self.skala), round(strona_pt[1] * self.skala))
        self.pliki_czcionek = _pliki_czcionek()
        self.czcionki = ("zwykla", "gruba")
        self.bez_polskich = self.pliki_czcionek[0] is None
        self._czcionki: dict = {}
        self.strony: list = []
        self._nowy_obraz()

    def _nowy_obraz(self) -> None:
        from PIL import Image, ImageDraw
        self.obraz = Image.new("RGB", self.rozmiar_px, (255, 255, 255))
        self.rysik = ImageDraw.Draw(self.obraz)

    def _px(self, x: float, y: float) -> tuple[float, float]:
        """Punkty (y od dołu) -> piksele obrazu (y od góry)."""
        return x * self.skala, (self.strona_pt[1] - y) * self.skala

    def _czcionka(self, nazwa: str, piksele: int):
        from PIL import ImageFont
        klucz = (nazwa, piksele)
        if klucz not in self._czcionki:
            zwykla, gruba = self.pliki_czcionek
            plik = gruba if nazwa == "gruba" else zwykla
            self._czcionki[klucz] = (ImageFont.truetype(plik, piksele) if plik
                                     else ImageFont.load_default(piksele))
        return self._czcionki[klucz]

    def szerokosc_tekstu(self, tekst: str, czcionka: str, rozmiar: float) -> float:
        """Szerokość w punktach — mierzona tą samą czcionką, którą będzie rysowany tekst."""
        piksele = max(6, round(rozmiar * self.skala))
        return self._czcionka(czcionka, piksele).getlength(tekst) / self.skala

    def kod_qr(self, macierz, x0: float, y_gora: float, modul: float) -> None:
        modul_px = max(1, int(modul * self.skala))
        lewo, gora = (round(v) for v in self._px(x0, y_gora))
        for r, wiersz in enumerate(macierz):
            for k, dlugosc in _przebiegi(wiersz):
                self.rysik.rectangle((lewo + k * modul_px, gora + r * modul_px,
                                      lewo + (k + dlugosc) * modul_px - 1, gora + (r + 1) * modul_px - 1),
                                     fill=(0, 0, 0))

    def tekst(self, x: float, y: float, tekst: str, czcionka: str, rozmiar: float) -> None:
        piksele = max(6, round(rozmiar * self.skala))
        self.rysik.text(self._px(x, y), tekst, font=self._czcionka(czcionka, piksele), fill=(0, 0, 0), anchor="ls")

    def obrys(self, x: float, y: float, szer: float, wys: float) -> None:
        lewo, dol = self._px(x, y)
        prawo, gora = self._px(x + szer, y + wys)
        self.rysik.rectangle((lewo, gora, prawo, dol), outline=(150, 150, 150),
                             width=max(1, round(0.25 * self.skala)))

    def nowa_strona(self) -> None:
        self.strony.append(self.obraz)
        self._nowy_obraz()

    def zakoncz_pdf(self, sciezka: Path) -> list[Path]:
        self.strony.append(self.obraz)
        zapisz_pdf_z_obrazow(sciezka, self.strony, self.strona_pt)
        return [Path(sciezka)]

    def zakoncz_png(self, sciezka: Path) -> list[Path]:
        """Strona = plik PNG z zapisaną rozdzielczością (dpi), żeby przeglądarka
        obrazów wydrukowała go w rzeczywistym rozmiarze."""
        self.strony.append(self.obraz)
        baza = Path(sciezka).with_suffix("")
        wynik = []
        for i, strona in enumerate(self.strony, 1):
            plik = baza.with_name(f"{baza.name}_{i:02d}.png") if len(self.strony) > 1 else baza.with_suffix(".png")
            strona.convert("L").save(plik, dpi=(self.dpi, self.dpi), optimize=True)
            wynik.append(plik)
        return wynik


def zapisz_pdf_z_obrazow(sciezka: str | Path, obrazy: list, strona_pt: tuple[float, float]) -> None:
    """Najprostszy możliwy PDF: na każdej stronie jeden obraz JPEG w kolorze.

    Celowo bez reportlab: jej pliki kodują obraz łańcuchem dwóch filtrów
    (ASCII85 + Flate) i zawierają odwołanie do czcionki. Pełne programy PDF
    radzą sobie z tym bez trudu, ale wbudowany interpreter drukarki (druk
    „driverless”, IPP Everywhere — drukarka dostaje PDF bezpośrednio) potrafi
    wysunąć pustą kartkę. Tu: PDF 1.4, jeden filtr DCTDecode (JPEG — ten sam,
    co przy drukowaniu zdjęć), RGB, nieskompresowana treść strony, zero czcionek.
    """
    import io
    szer, wys = strona_pt
    obiekty: list[bytes] = [b"", b""]            # 1: katalog, 2: drzewo stron (uzupełniane na końcu)
    strony_ref = []
    for obraz in obrazy:
        bufor = io.BytesIO()
        # subsampling=0 (4:4:4) i wysoka jakość: bez rozmycia krawędzi modułów QR
        obraz.convert("RGB").save(bufor, format="JPEG", quality=95, subsampling=0, optimize=True)
        jpeg = bufor.getvalue()
        nr_obrazu = len(obiekty) + 1
        obiekty.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                       b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
                       % (obraz.width, obraz.height, len(jpeg)) + jpeg + b"\nendstream")
        tresc = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (szer, wys)
        nr_tresci = len(obiekty) + 1
        obiekty.append(b"<< /Length %d >>\nstream\n" % len(tresc) + tresc + b"\nendstream")
        nr_strony = len(obiekty) + 1
        obiekty.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
                       b"/Resources << /XObject << /Im0 %d 0 R >> /ProcSet [/PDF /ImageC] >> "
                       b"/Contents %d 0 R >>" % (szer, wys, nr_obrazu, nr_tresci))
        strony_ref.append(nr_strony)
    obiekty[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    obiekty[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % n for n in strony_ref), len(strony_ref))
    obiekty.append(b"<< /Producer (NORNICA / VOLE) /Title (NORNICA / VOLE) >>")
    nr_info = len(obiekty)

    wyjscie = io.BytesIO()
    wyjscie.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")       # bajty >127: znak, że plik jest binarny
    przesuniecia = []
    for nr, tresc in enumerate(obiekty, 1):
        przesuniecia.append(wyjscie.tell())
        wyjscie.write(b"%d 0 obj\n" % nr + tresc + b"\nendobj\n")
    poczatek_xref = wyjscie.tell()
    wyjscie.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(obiekty) + 1))
    for przesuniecie in przesuniecia:
        wyjscie.write(b"%010d 00000 n \n" % przesuniecie)
    wyjscie.write(b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                  % (len(obiekty) + 1, nr_info, poczatek_xref))
    Path(sciezka).write_bytes(wyjscie.getvalue())


def _rysuj_strony(plotno, etykiety: list[Etykieta], f: Format, start: int,
                  przesuniecie: tuple[float, float], ramki: bool) -> int:
    szer_strony, wys_strony = f.strona
    pozycja = max(0, min(start - 1, f.na_stronie - 1)) if f.rodzaj == "a4" else 0
    strony = 1
    for etykieta in etykiety:
        if pozycja >= f.na_stronie:
            plotno.nowa_strona()
            strony += 1
            pozycja = 0
        lewo_mm, gora_mm = f.etykieta(pozycja)
        x = (lewo_mm + przesuniecie[0]) * MM
        y_gora = (wys_strony - gora_mm - przesuniecie[1]) * MM
        if ramki:
            plotno.obrys(x, y_gora - f.wysokosc * MM, f.szerokosc * MM, f.wysokosc * MM)
        _rysuj_etykiete(plotno, etykieta, x, y_gora, f)
        pozycja += 1
    return strony


def generuj(sciezka: str | Path, etykiety: list[Etykieta], f: Format, start: int = 1,
            przesuniecie: tuple[float, float] = (0.0, 0.0), ramki: bool = False,
            tryb: str = "obraz") -> list[Path]:
    """Zapisuje etykiety i zwraca listę plików.

    tryb: "obraz" (PDF z obrazami 300 dpi), "obraz600", "png" (plik PNG na stronę),
          "wektor" (PDF wektorowy, reportlab);
    start — numer pierwszej wolnej naklejki na arkuszu (napoczęty arkusz A4),
    przesuniecie — korekta położenia w mm (kalibracja drukarki),
    ramki — cienkie obrysy etykiet do wydruku próbnego na zwykłym papierze.
    """
    if not etykiety:
        raise BladNornicy("blad.brak_etykiet")
    sprawdz_format(f)
    szer_strony, wys_strony = f.strona
    strona_pt = (szer_strony * MM, wys_strony * MM)
    if tryb == "wektor":
        plotno = _PlotnoWektorowe(str(sciezka), strona_pt)
        _rysuj_strony(plotno, etykiety, f, start, przesuniecie, ramki)
        return plotno.zakoncz()
    plotno = _PlotnoRastrowe(strona_pt, DPI_TRYBU.get(tryb, 300))
    _rysuj_strony(plotno, etykiety, f, start, przesuniecie, ramki)
    return plotno.zakoncz_png(Path(sciezka)) if tryb == "png" else plotno.zakoncz_pdf(Path(sciezka))


def generuj_pdf(sciezka: str | Path, etykiety: list[Etykieta], f: Format, start: int = 1,
                przesuniecie: tuple[float, float] = (0.0, 0.0), ramki: bool = False,
                tryb: str = "obraz") -> int:
    """Zgodność wstecz: zapis PDF, zwraca liczbę stron."""
    if tryb == "png":
        tryb = "obraz"
    generuj(sciezka, etykiety, f, start, przesuniecie, ramki, tryb)
    na_strone = f.na_stronie if f.rodzaj == "a4" else 1
    pozycja = max(0, min(start - 1, na_strone - 1)) if f.rodzaj == "a4" else 0
    return -(-(pozycja + len(etykiety)) // na_strone)
