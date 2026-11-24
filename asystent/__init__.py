# SPDX-License-Identifier: GPL-3.0-or-later
"""Asystent AI: uzupełnianie parametrów modelu danymi znalezionymi w internecie.

Zasada: AI proponuje, człowiek zatwierdza. Asystent nigdy nie pisze do bazy —
zwraca propozycje (wartość, źródło, cytat), które okno wstawia do formularza
modelu; zapis robi użytkownik przyciskiem „Zapisz”.

  ollama.py        — lokalny model językowy (Ollama, tylko ten komputer)
  wyszukiwarki.py  — skąd brać strony: Ollama web search albo SearXNG
  propozycje.py    — zapytanie, polecenie dla modelu, sprawdzenie odpowiedzi

Pakiet nie zależy od interfejsu (pilnuje tego testy/test_architektura.py).
Program działa bez Ollamy — wtedy asystent mówi tylko, czego brakuje.
"""
