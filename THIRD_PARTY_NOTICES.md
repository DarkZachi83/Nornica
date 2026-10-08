# Licencje komponentów zewnętrznych / Third-party notices

NORNICA / VOLE jest wydana na licencji **GPL-3.0-or-later** (plik `LICENSE`).
Program korzysta z poniższych komponentów na ich własnych licencjach —
wszystkie są zgodne z GPL-3.0.

## Dołączone do programu / Bundled

| Komponent | Wersja | Licencja | Plik |
|---|---|---|---|
| [jsQR](https://github.com/cozmo/jsQR) — odczyt kodów QR na stronie telefonu | 1.4.0 | Apache-2.0 | `zasoby/www/jsQR.js`, licencja: `zasoby/www/LICENSE-jsQR.txt` |

## Biblioteki instalowane osobno / Installed separately

| Biblioteka | Licencja | Do czego |
|---|---|---|
| Python, tkinter (Tcl/Tk) | PSF-2.0, licencja Tcl/Tk (BSD) | środowisko i interfejs |
| [Pillow](https://python-pillow.org/) | MIT-CMU | miniatury i podgląd zdjęć |
| [qrcode](https://github.com/lincolnloop/python-qrcode) | BSD-3-Clause (część z pyqrnative: MIT) | kody QR |
| [ReportLab](https://www.reportlab.com/) | BSD | PDF wektorowy |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | MIT | eksport .xlsx |
| [xlwt](https://github.com/python-excel/xlwt) | BSD | eksport .xls |
| [cryptography](https://cryptography.io/) | Apache-2.0 OR BSD-3-Clause | szyfrowane połączenie z telefonem |

Czcionki (DejaVu Sans, Arial itp.) nie są dołączone — program korzysta
z czcionek zainstalowanych w systemie i osadza ich podzbiór w plikach PDF
w trybie wektorowym.

## Dane z The Retro Web / The Retro Web data

Funkcja „The Retro Web…” w oknie modelu kopiuje do opisu i parametrów modelu
dane tekstowe z serwisu [The Retro Web](https://theretroweb.com), udostępniane
na licencji [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
([warunki serwisu](https://theretroweb.com/info/legal)). Każdy taki model ma
link do strony źródłowej i dopisek o licencji. Zdjęcia, BIOS-y i dokumenty
z serwisu nie są kopiowane. Strony wzorcowe do testów (`testy/dane/trw/`)
pochodzą z tego serwisu — szczegóły w `testy/dane/trw/ZRODLO.md`.

## Znaki towarowe / Trademarks

„QR Code” jest zastrzeżonym znakiem towarowym DENSO WAVE INCORPORATED.
Nazwy sprzętu (Atari, Commodore, Amiga, IBM i inne) użyte w dokumentacji
i przykładach należą do ich właścicieli i służą wyłącznie do opisu.
