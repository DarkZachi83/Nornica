# SPDX-License-Identifier: GPL-3.0-or-later
import os

# W testach błąd budowy okna ma przerwać test, a nie zamienić się w okno awaryjne.
os.environ.setdefault("NORNICA_SUROWE_BLEDY", "1")
