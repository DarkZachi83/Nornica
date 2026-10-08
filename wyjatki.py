# SPDX-License-Identifier: GPL-3.0-or-later
"""Wyjątki programu.

Wyjątek niesie KLUCZ tłumaczenia i pola, a nie gotowy napis. Tekst powstaje
dopiero w chwili wyświetlenia, w języku obowiązującym w tamtym momencie.
"""
from i18n.tlumacz import t


class BladNornicy(Exception):
    def __init__(self, klucz: str, **pola):
        super().__init__(klucz)
        self.klucz = klucz
        self.pola = pola

    def komunikat(self, jezyk: str | None = None) -> str:
        return t(self.klucz, jezyk, **self.pola)
