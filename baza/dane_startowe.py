# SPDX-License-Identifier: GPL-3.0-or-later
"""Dane startowe: kategorie, statusy, waluty, typy złączy, ustawienia.

Wypełnianie jest idempotentne: istniejące wpisy (po kodzie) są pomijane,
więc zmiany wprowadzone przez użytkownika nie zostaną nadpisane.

Wyjątek: szablony atrybutów kategorii startowych są UZUPEŁNIANE. Pole dodane
w nowej wersji programu (np. taktowanie procesora) trafia do istniejącej
bazy przy najbliższym starcie, wstawione za polem, które poprzedza je
w kodzie. Pola już obecne — także dopisane przez użytkownika — zostają
nietknięte.

Szablon atrybutów kategorii to lista pól formularza:
  {"kod": ..., "typ": "text|int|real|bool|enum|pojemnosc", "nazwy": {"en", "pl"},
  (pojemnosc: wartość w bajtach, jednostka do wyboru w formularzu)
   "jednostka": opcjonalnie, "wartosci": lista dla typu enum}
Wartości techniczne (np. "FPM", "VGA") nie są tłumaczone.
"""
from __future__ import annotations

import json
import sqlite3

from baza.polaczenie import transakcja


def _n(en: str, pl: str) -> dict[str, str]:
    return {"en": en, "pl": pl}


def _pole(kod, typ, en, pl, jednostka=None, wartosci=None) -> dict:
    pole = {"kod": kod, "typ": typ, "nazwy": _n(en, pl)}
    if jednostka:
        pole["jednostka"] = jednostka
    if wartosci:
        pole["wartosci"] = list(wartosci)
    return pole


# ---------------------------------------------------------------------------
# Statusy techniczne
# ---------------------------------------------------------------------------
STATUSY = [
    ("dziala",       _n("Working", "Działa")),
    ("uszkodzony",   _n("Faulty", "Uszkodzony")),
    ("w_naprawie",   _n("In repair", "W naprawie")),
    ("nietestowany", _n("Untested", "Nietestowany")),
    ("zapasowy",     _n("Spare", "Zapasowy")),
    ("na_czesci",    _n("For parts", "Na części")),
]

# ---------------------------------------------------------------------------
# Waluty (ISO 4217): kod, nazwy, miejsca dziesiętne, historyczna
# ---------------------------------------------------------------------------
WALUTY = [
    ("PLN", _n("Polish zloty", "Złoty polski"), 2, 0),
    ("PLZ", _n("Polish zloty (before 1995 redenomination)",
               "Złoty polski (przed denominacją 1995)"), 2, 1),
    ("EUR", _n("Euro", "Euro"), 2, 0),
    ("USD", _n("US dollar", "Dolar amerykański"), 2, 0),
    ("GBP", _n("Pound sterling", "Funt szterling"), 2, 0),
    ("CHF", _n("Swiss franc", "Frank szwajcarski"), 2, 0),
    ("CZK", _n("Czech koruna", "Korona czeska"), 2, 0),
    ("SEK", _n("Swedish krona", "Korona szwedzka"), 2, 0),
    ("JPY", _n("Japanese yen", "Jen japoński"), 0, 0),
    ("DEM", _n("Deutsche Mark", "Marka niemiecka"), 2, 1),
]

# ---------------------------------------------------------------------------
# Typy złączy: kod, rodzaj, nazwa EN, nazwa PL
# ---------------------------------------------------------------------------
ZLACZA = [
    # porty
    ("com_db9",        "port", "Serial port COM (DB9)",       "Port szeregowy COM (DB9)"),
    ("com_db25",       "port", "Serial port COM (DB25)",      "Port szeregowy COM (DB25)"),
    ("lpt_db25",       "port", "Parallel port LPT (DB25)",    "Port równoległy LPT (DB25)"),
    ("gameport_da15",  "port", "Game port (DA15)",            "Port gier (DA15)"),
    ("db9_joystick",   "port", "Joystick port (Atari DB9)",   "Port joysticka (Atari DB9)"),
    ("ps2",            "port", "PS/2",                        "PS/2"),
    ("din5_klawiatura", "port", "AT keyboard (DIN-5)",        "Klawiatura AT (DIN-5)"),
    ("usb_a",          "port", "USB-A",                       "USB-A"),
    ("vga_de15",       "port", "VGA (DE15)",                  "VGA (DE15)"),
    ("rgbi_de9",       "port", "CGA/EGA RGBI (DE9)",          "CGA/EGA RGBI (DE9)"),
    ("rgb_amiga_db23", "port", "Amiga RGB (DB23)",            "Amiga RGB (DB23)"),
    ("scart",          "port", "SCART",                       "SCART"),
    ("kompozyt_rca",   "port", "Composite video (RCA)",       "Wideo kompozytowe (RCA)"),
    ("iec_commodore",  "port", "Commodore serial IEC (DIN-6)", "Szeregowy IEC Commodore (DIN-6)"),
    ("sio_atari",      "port", "Atari SIO",                   "Atari SIO"),
    ("c64_uzytkownika", "port", "C64 user port",              "Port użytkownika C64"),
    ("c64_kartridz",   "port", "C64 cartridge port",          "Port kartridża C64"),
    ("magnetofon_c64", "port", "Datasette port",              "Port magnetofonu (Datasette)"),
    ("midi_din5",      "port", "MIDI (DIN-5)",                "MIDI (DIN-5)"),
    ("rj45",           "port", "Ethernet (RJ45)",             "Ethernet (RJ45)"),
    ("bnc",            "port", "Ethernet 10BASE2 (BNC)",      "Ethernet 10BASE2 (BNC)"),
    # sloty
    ("isa8",           "slot", "ISA 8-bit",                   "ISA 8-bit"),
    ("isa16",          "slot", "ISA 16-bit",                  "ISA 16-bit"),
    ("eisa",           "slot", "EISA",                        "EISA"),
    ("vlb",            "slot", "VESA Local Bus",              "VESA Local Bus"),
    ("pci",            "slot", "PCI",                         "PCI"),
    ("agp",            "slot", "AGP",                         "AGP"),
    ("pcie_x1",        "slot", "PCI Express x1",              "PCI Express x1"),
    ("pcie_x16",       "slot", "PCI Express x16",             "PCI Express x16"),
    ("zorro_ii",       "slot", "Zorro II",                    "Zorro II"),
    ("zorro_iii",      "slot", "Zorro III",                   "Zorro III"),
    ("a1200_trapdoor", "slot", "A1200 trapdoor (150-pin)",    "Złącze klapki A1200 (150-pin)"),
    ("pcmcia",         "slot", "PCMCIA",                      "PCMCIA"),
    # gniazda
    ("dip40",          "gniazdo", "DIP-40",                   "DIP-40"),
    ("plcc68",         "gniazdo", "PLCC-68",                  "PLCC-68"),
    ("pga132",         "gniazdo", "PGA-132",                  "PGA-132"),
    ("socket3",        "gniazdo", "Socket 3",                 "Socket 3"),
    ("socket7",        "gniazdo", "Socket 7",                 "Socket 7"),
    ("super7",         "gniazdo", "Super Socket 7",           "Super Socket 7"),
    ("socket370",      "gniazdo", "Socket 370",               "Socket 370"),
    ("slot1",          "gniazdo", "Slot 1",                   "Slot 1"),
    ("slot_a",         "gniazdo", "Slot A",                   "Slot A"),
    ("socket_a",       "gniazdo", "Socket A (462)",           "Socket A (462)"),
    ("simm30",         "gniazdo", "SIMM 30-pin",              "SIMM 30-pin"),
    ("simm72",         "gniazdo", "SIMM 72-pin",              "SIMM 72-pin"),
    ("dimm168",        "gniazdo", "DIMM 168-pin (SDR)",       "DIMM 168-pin (SDR)"),
    ("dimm184",        "gniazdo", "DIMM 184-pin (DDR)",       "DIMM 184-pin (DDR)"),
    # interfejsy wewnętrzne
    ("ide40",          "interfejs", "IDE/ATA 40-pin",         "IDE/ATA 40-pin"),
    ("ide44",          "interfejs", "IDE/ATA 44-pin (2.5\")", "IDE/ATA 44-pin (2,5\")"),
    ("fdd34",          "interfejs", "Floppy 34-pin",          "Stacja dyskietek 34-pin"),
    ("st506",          "interfejs", "ST-506 MFM/RLL (34+20)", "ST-506 MFM/RLL (34+20)"),
    ("scsi50",         "interfejs", "SCSI 50-pin",            "SCSI 50-pin"),
    ("scsi68",         "interfejs", "SCSI 68-pin",            "SCSI 68-pin"),
    ("sata",           "interfejs", "SATA",                   "SATA"),
    ("zasilanie_molex", "interfejs", "Molex power",           "Zasilanie Molex"),
    ("zasilanie_berg", "interfejs", "Berg (floppy) power",    "Zasilanie Berg (stacja dyskietek)"),
    ("zasilanie_at",   "interfejs", "AT power (P8/P9)",       "Zasilanie AT (P8/P9)"),
    ("zasilanie_atx20", "interfejs", "ATX power 20-pin",      "Zasilanie ATX 20-pin"),
    ("zasilanie_sata", "interfejs", "SATA power (15-pin)",    "Zasilanie SATA (15-pin)"),
]

# ---------------------------------------------------------------------------
# Kategorie z szablonami atrybutów
# ---------------------------------------------------------------------------
_FORMATY_PLYT = ("XT", "Baby AT", "AT", "LPX", "ATX", "Micro ATX", "NLX", "inny / other")

KATEGORIE = [
    # --- komputery fabryczne -------------------------------------------------
    {"kod": "komputery_fabryczne", "rodzic": None, "rodzaj": "komputer_fabryczny",
     "nazwy": _n("Factory computers", "Komputery fabryczne"),
     "szablon": [
         _pole("procesor", "text", "CPU", "Procesor"),
         _pole("taktowanie_mhz", "real", "CPU clock", "Taktowanie procesora", "MHz"),
         _pole("pamiec", "pojemnosc", "RAM", "Pamięć RAM"),
         _pole("wersja_rom", "text", "ROM / OS version", "Wersja ROM / systemu"),
         _pole("norma_tv", "enum", "TV standard", "Norma TV", wartosci=("PAL", "NTSC", "PAL/NTSC")),
         _pole("zasilacz_oryginalny", "bool", "Original PSU", "Oryginalny zasilacz"),
     ]},
    # --- konsole: od Atari 2600 po Xbox 360 -------------------------------------
    # Rodzaj „komputer_fabryczny” = urządzenie fabryczne (etykieta w i18n).
    {"kod": "konsole", "rodzic": None, "rodzaj": "komputer_fabryczny",
     "nazwy": _n("Game consoles", "Konsole do gier"),
     "szablon": [
         _pole("typ_konsoli", "enum", "Console type", "Typ konsoli",
               wartosci=("stacjonarna / home", "przenośna / handheld", "hybrydowa / hybrid",
                         "retro mini / plug & play")),
         _pole("generacja", "enum", "Generation", "Generacja",
               wartosci=("1 (1972–1980)", "2 (1976–1992)", "3 (1983–2003)", "4 (1987–2004)",
                         "5 (1993–2006)", "6 (1998–2013)", "7 (2005–2017)", "8 (2012–)", "9 (2020–)")),
         _pole("procesor", "text", "CPU", "Procesor"),
         _pole("taktowanie_mhz", "real", "CPU clock", "Taktowanie procesora", "MHz"),
         _pole("pamiec", "pojemnosc", "RAM", "Pamięć RAM"),
         _pole("nosnik", "enum", "Media", "Nośnik gier",
               wartosci=("kartridż / cartridge", "kaseta / tape", "dyskietka / floppy", "CD", "GD-ROM",
                         "DVD", "Blu-ray", "HDD / cyfrowa / digital", "wbudowane / built-in")),
         _pole("region", "enum", "Region", "Region",
               wartosci=("PAL", "NTSC-U", "NTSC-J", "NTSC-C", "region free")),
         _pole("przerobka", "text", "Mod / modchip", "Przeróbka / modchip"),
         _pole("zasilacz_oryginalny", "bool", "Original PSU", "Oryginalny zasilacz"),
     ]},
    # --- składaki --------------------------------------------------------------
    {"kod": "skladaki_pc", "rodzic": None, "rodzaj": "skladak",
     "nazwy": _n("PC builds", "Składaki PC"),
     "szablon": [
         _pole("przeznaczenie", "text", "Purpose", "Przeznaczenie"),
         _pole("system_operacyjny", "text", "Operating system", "System operacyjny"),
         _pole("format_obudowy", "enum", "Case form factor", "Format obudowy", wartosci=_FORMATY_PLYT),
     ]},
    # --- części ---------------------------------------------------------------
    {"kod": "czesci", "rodzic": None, "rodzaj": "czesc",
     "nazwy": _n("Parts", "Części"), "szablon": []},
    {"kod": "procesory", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Processors", "Procesory"),
     "szablon": [
         _pole("taktowanie_mhz", "real", "Clock", "Taktowanie", "MHz"),
         _pole("magistrala_mhz", "real", "Bus clock", "Magistrala", "MHz"),
         _pole("napiecie_v", "real", "Core voltage", "Napięcie rdzenia", "V"),
         _pole("rodzina", "text", "Family", "Rodzina"),
         _pole("stepping", "text", "Stepping / S-spec", "Stepping / S-spec"),
     ]},
    {"kod": "pamieci_ram", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Memory modules", "Pamięci RAM"),
     "szablon": [
         _pole("pojemnosc", "pojemnosc", "Capacity", "Pojemność"),
         _pole("technologia", "enum", "Technology", "Technologia",
               wartosci=("DRAM", "FPM", "EDO", "SDRAM", "DDR", "DDR2", "inna / other")),
         _pole("parzystosc", "enum", "Parity", "Parzystość",
               wartosci=("none", "parity", "ECC")),
         _pole("szybkosc", "text", "Speed (ns / PC)", "Szybkość (ns / PC)"),
         _pole("strony", "enum", "Sides", "Strony", wartosci=("SS", "DS")),
     ]},
    {"kod": "plyty_glowne", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Motherboards", "Płyty główne"),
     "szablon": [
         _pole("chipset", "text", "Chipset", "Chipset"),
         _pole("format", "enum", "Form factor", "Format", wartosci=_FORMATY_PLYT),
         _pole("bios", "text", "BIOS", "BIOS"),
         _pole("max_ram", "pojemnosc", "Max RAM", "Maks. RAM"),
         _pole("cache", "pojemnosc", "L2 cache", "Pamięć cache L2"),
     ]},
    {"kod": "karty_graficzne", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Graphics cards", "Karty graficzne"),
     "szablon": [
         _pole("chipset", "text", "Chipset", "Chipset"),
         _pole("pamiec", "pojemnosc", "Video memory", "Pamięć wideo"),
         _pole("standard", "enum", "Standard", "Standard",
               wartosci=("MDA", "Hercules", "CGA", "EGA", "VGA", "SVGA", "2D/3D", "3D")),
     ]},
    {"kod": "karty_dzwiekowe", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Sound cards", "Karty dźwiękowe"),
     "szablon": [
         _pole("chipset", "text", "Chipset", "Chipset"),
         _pole("synteza_fm", "text", "FM synth (OPL)", "Synteza FM (OPL)"),
         _pole("zgodnosc", "text", "Compatibility", "Zgodność"),
         _pole("wavetable", "bool", "Wavetable header", "Złącze wavetable"),
     ]},
    {"kod": "karty_sieciowe", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Network cards", "Karty sieciowe"),
     "szablon": [
         _pole("chipset", "text", "Chipset", "Chipset"),
         _pole("predkosc_mbit", "int", "Speed", "Prędkość", "Mbit/s"),
     ]},
    {"kod": "kontrolery", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Controllers", "Kontrolery"),
     "szablon": [
         _pole("rodzaj_kontrolera", "enum", "Controller type", "Rodzaj kontrolera",
               wartosci=("IDE", "SCSI", "FDD", "MFM/RLL", "Multi I/O", "USB", "inny / other")),
         _pole("chipset", "text", "Chipset", "Chipset"),
     ]},
    {"kod": "karty_inne", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Other expansion cards", "Inne karty rozszerzeń"),
     "szablon": [_pole("funkcja", "text", "Function", "Funkcja")]},
    {"kod": "dyski_twarde", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Hard drives", "Dyski twarde"),
     "szablon": [
         _pole("pojemnosc", "pojemnosc", "Capacity", "Pojemność"),
         _pole("cylindry", "int", "Cylinders", "Cylindry"),
         _pole("glowice", "int", "Heads", "Głowice"),
         _pole("sektory", "int", "Sectors per track", "Sektory na ścieżkę"),
         _pole("format_cali", "enum", "Size", "Rozmiar", wartosci=('5.25"', '3.5"', '2.5"', 'CF')),
     ]},
    {"kod": "napedy_dyskietek", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Floppy drives", "Stacje dyskietek"),
     "szablon": [
         _pole("format_dyskietek", "enum", "Disk format", "Format dyskietek",
               wartosci=('8"', '5.25" DD', '5.25" HD', '3.5" DD', '3.5" HD', '3.5" ED', '3"')),
         _pole("platforma", "text", "Platform", "Platforma"),
     ]},
    {"kod": "napedy_optyczne", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Optical drives", "Napędy optyczne"),
     "szablon": [
         _pole("rodzaj_napedu", "enum", "Drive type", "Rodzaj napędu",
               wartosci=("CD-ROM", "CD-R", "CD-RW", "DVD-ROM", "DVD±RW")),
         _pole("predkosc", "text", "Speed", "Prędkość"),
     ]},
    {"kod": "napedy_tasmowe", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Tape drives", "Napędy taśmowe"),
     "szablon": [_pole("format_tasmy", "text", "Tape format", "Format taśmy")]},
    {"kod": "zasilacze", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Power supplies", "Zasilacze"),
     "szablon": [
         _pole("moc_w", "int", "Power", "Moc", "W"),
         _pole("standard_zasilacza", "enum", "Standard", "Standard",
               wartosci=("AT", "ATX", "zewnętrzny / external", "inny / other")),
         _pole("napiecia", "text", "Output voltages", "Napięcia wyjściowe"),
         _pole("po_recapie", "bool", "Recapped", "Po wymianie kondensatorów"),
     ]},
    {"kod": "uklady_rom", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("ROM chips", "Układy ROM"),
     "szablon": [
         _pole("wersja", "text", "Version", "Wersja"),
         _pole("oznaczenie", "text", "Chip marking", "Oznaczenie układu"),
         _pole("typ_ukladu", "text", "Chip type (e.g. 27C512)", "Typ układu (np. 27C512)"),
     ]},
    {"kod": "obudowy", "rodzic": "czesci", "rodzaj": "czesc",
     "nazwy": _n("Cases", "Obudowy"),
     "szablon": [_pole("format_obudowy", "enum", "Form factor", "Format", wartosci=_FORMATY_PLYT)]},
    # --- akcesoria ------------------------------------------------------------
    {"kod": "akcesoria", "rodzic": None, "rodzaj": "akcesorium",
     "nazwy": _n("Accessories", "Akcesoria"), "szablon": []},
    {"kod": "myszy", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Mice", "Myszy"), "szablon": []},
    {"kod": "joysticki", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Joysticks and gamepads", "Joysticki i pady"),
     "szablon": [_pole("liczba_przyciskow", "int", "Buttons", "Liczba przycisków")]},
    {"kod": "klawiatury", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Keyboards", "Klawiatury"),
     "szablon": [_pole("uklad", "text", "Layout", "Układ klawiszy")]},
    {"kod": "monitory", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Monitors", "Monitory"),
     "szablon": [
         _pole("przekatna_cal", "real", "Diagonal", "Przekątna", '"'),
         _pole("technologia_ekranu", "enum", "Technology", "Technologia",
               wartosci=("CRT", "LCD")),
     ]},
    {"kod": "magnetofony", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Tape recorders", "Magnetofony"), "szablon": []},
    {"kod": "kable_adaptery", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Cables and adapters", "Kable i adaptery"), "szablon": []},
    {"kod": "akcesoria_inne", "rodzic": "akcesoria", "rodzaj": "akcesorium",
     "nazwy": _n("Other accessories", "Inne akcesoria"), "szablon": []},
]

USTAWIENIA = [
    ("jezyk", "en"),
    ("domyslna_waluta", "PLN"),
    ("prefiks_kodu", "NOR"),
    ("prefiks_lokalizacji", "LOC"),
]


def _json(obiekt) -> str:
    return json.dumps(obiekt, ensure_ascii=False)


def scal_szablon(w_bazie: list[dict], w_kodzie: list[dict]) -> list[dict]:
    """Dopisuje do szablonu z bazy pola z kodu, których jeszcze nie ma.

    Nowe pole ląduje za najbliższym poprzedzającym je (w kodzie) polem,
    które istnieje w bazie; gdy takiego nie ma — na początku listy.
    """
    wynik = list(w_bazie)
    obecne = {pole["kod"] for pole in wynik}
    for i, pole in enumerate(w_kodzie):
        if pole["kod"] in obecne:
            continue
        pozycja = 0
        for poprzednie in reversed(w_kodzie[:i]):
            indeksy = [j for j, p in enumerate(wynik) if p["kod"] == poprzednie["kod"]]
            if indeksy:
                pozycja = indeksy[0] + 1
                break
        wynik.insert(pozycja, pole)
        obecne.add(pole["kod"])
    return wynik


def _uzupelnij_szablony(polaczenie: sqlite3.Connection) -> None:
    for kat in KATEGORIE:
        wiersz = polaczenie.execute("SELECT id, szablon_atrybutow FROM kategoria WHERE kod = ?",
                                    (kat["kod"],)).fetchone()
        if wiersz is None:
            continue
        w_bazie = json.loads(wiersz["szablon_atrybutow"] or "[]")
        scalony = scal_szablon(w_bazie, kat["szablon"])
        if len(scalony) != len(w_bazie):
            polaczenie.execute("UPDATE kategoria SET szablon_atrybutow = ? WHERE id = ?",
                               (_json(scalony), wiersz["id"]))


def wypelnij(polaczenie: sqlite3.Connection) -> int:
    """Dodaje brakujące dane startowe. Zwraca liczbę dodanych wierszy."""
    przed = polaczenie.total_changes
    with transakcja(polaczenie):
        for kolejnosc, (kod, nazwy) in enumerate(STATUSY):
            polaczenie.execute(
                "INSERT INTO status (kod, nazwy, kolejnosc) VALUES (?, ?, ?) "
                "ON CONFLICT(kod) DO NOTHING", (kod, _json(nazwy), kolejnosc))

        for kod, nazwy, miejsca, historyczna in WALUTY:
            polaczenie.execute(
                "INSERT INTO waluta (kod, nazwy, miejsca_dzies, historyczna) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(kod) DO NOTHING",
                (kod, _json(nazwy), miejsca, historyczna))

        for kolejnosc, (kod, rodzaj, en, pl) in enumerate(ZLACZA):
            polaczenie.execute(
                "INSERT INTO zlacze_typ (kod, rodzaj, nazwy, kolejnosc) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(kod) DO NOTHING",
                (kod, rodzaj, _json(_n(en, pl)), kolejnosc))

        # Kategorie nadrzędne występują na liście przed podrzędnymi.
        for kolejnosc, kat in enumerate(KATEGORIE):
            polaczenie.execute(
                "INSERT INTO kategoria (kod, rodzic_id, rodzaj, nazwy, szablon_atrybutow, kolejnosc) "
                "VALUES (?, (SELECT id FROM kategoria WHERE kod = ?), ?, ?, ?, ?) "
                "ON CONFLICT(kod) DO NOTHING",
                (kat["kod"], kat["rodzic"], kat["rodzaj"], _json(kat["nazwy"]),
                 _json(kat["szablon"]), kolejnosc))

        _uzupelnij_szablony(polaczenie)

        for klucz, wartosc in USTAWIENIA:
            polaczenie.execute(
                "INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?) "
                "ON CONFLICT(klucz) DO NOTHING", (klucz, wartosc))
    return polaczenie.total_changes - przed
