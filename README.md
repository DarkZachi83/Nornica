# VOLE / NORNICA

**A desktop catalogue for a home collection of retro computers** — factory-built
machines, PC builds, spare parts and accessories. Where every item is, what is
inside it, what works and what is waiting for repair.

The interface is available in English (**VOLE**) and Polish (**NORNICA**,
"vole" in Polish) and can be switched while the program is running.

[Polska wersja README](README.pl.md)

![Main window](docs/zrzuty/okno_glowne.png)

## Features

- **Items and locations as a tree** — rooms, racks, shelves, boxes; view the
  collection by location or by assembly.
- **Assemblies** — a PC build is an item made of other items (motherboard,
  cards, drives); install and remove parts, keep a test and repair history.
- **Model catalogue** — manufacturer, production years, specs per category
  (chipset, RAM, capacity…) and connectors (what a device has and what it needs).
- **Your own categories, fields and statuses** — add text, number, yes/no, list
  or capacity fields to any category; subcategories inherit them. Built-in
  entries are read-only and deletion is guarded ("still used by…").
- **QR labels** — every item and location gets a code (`NOR-000001`,
  `LOC-0001`); print A4 label sheets (Avery) or labels for Brother / Dymo printers, as PDF or PNG.
- **Phone as a scanner** — the program starts a local HTTPS server and shows a
  QR code; the phone opens a web page (no app to install), scans labels with the
  live camera and can add photos to an item. Works on Android and iPhone.
- **USB / Bluetooth barcode readers** — the *Scan* field in the toolbar (F2).
- **The Retro Web import** — fill in a PC hardware model (motherboards,
  expansion cards, drives) from [The Retro Web](https://theretroweb.com):
  preview first, then apply to the form. Text data only, CC BY-SA 4.0 with
  attribution kept.
- **Photos, documents and links** for items and models.
- **Export** — `.xlsx`, `.xls`, `.csv`, `.html`.
- **Safe data** — SQLite with atomic, checksummed schema migrations and an
  automatic backup before every upgrade.

| Phone scanner | Label sheet | The Retro Web |
|---|---|---|
| ![Phone](docs/zrzuty/telefon.png) | ![Labels](docs/zrzuty/etykiety.png) | ![The Retro Web](docs/zrzuty/retroweb.png) |

## Requirements

Python 3.10+ with tkinter, SQLite 3.35+ with JSON support (standard in current
Python builds).

**Arch Linux**

    sudo pacman -S python tk python-pillow python-qrcode python-reportlab python-openpyxl python-cryptography
    pip install --user xlwt          # optional, legacy .xls export

**Debian / Ubuntu**

    sudo apt install python3 python3-tk
    pip install -r requirements.txt

**Windows 10/11** — Python from python.org with "tcl/tk and IDLE" ticked, then

    pip install -r requirements.txt

Every library is optional: without it the program still starts and only the
related feature is disabled (with a message saying why).

## Running

    python nornica.py                  # the program
    python nornica.py --jezyk en       # choose the language (remembered)
    python nornica.py --bez-powitania  # skip the splash screen
    python nornica.py --konsola        # prepare the database and print a summary

## Where your data lives

The database, backups, photos and certificates are **never stored in the code
folder**:

- Linux: `~/.local/share/nornica/`
- Windows: `%APPDATA%\Nornica\`

A different place: environment variable `NORNICA_DANE` or `--baza PATH`.
This keeps the repository clean — `.gitignore` additionally blocks database
files, backups and keys in case someone points the data folder here.

## Tests

    pip install -r requirements-dev.txt
    xvfb-run -a -s "-screen 0 1920x1080x24" python -m unittest discover -s testy -t .

About 360 tests: database, migrations, business rules, i18n key parity
(EN/PL), PDF labels (decoded back with zbar), the phone server, The Retro Web
parser (on saved pages) and the GUI. Without a display the GUI tests are
skipped. CI runs them on every push (GitHub Actions).

## Project layout

    nornica.py           entry point
    konfiguracja.py      platform-dependent data paths
    baza/                SQLite: schema migrations, connection, repositories
    uslugi/              business rules: inventory, labels, export, scanner server, The Retro Web
    gui/                 tkinter windows
    raporty/             reports
    i18n/                translator, en.json, pl.json
    zasoby/              icons, splash screen, phone page (jsQR)
    testy/               tests and test data
    narzedzia/           developer scripts

Identifiers are in Polish (the author's language); all user-facing text goes
through translation keys.

## Licence

Copyright © 2026 Rafał Zacharski

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. It is distributed WITHOUT ANY WARRANTY. See [`LICENSE`](LICENSE).

Exceptions: the jsQR library (Apache-2.0, `zasoby/www/`) and the illustration
and project name ([`zasoby/GRAFIKA.md`](zasoby/GRAFIKA.md)). Third-party
licences: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

Migration files in `baza/schemat/` intentionally have no licence header: their
checksums are stored in users' databases and the migration guard refuses to
run after an applied file changes. They are covered by the statement above.
