-- Inwentaryzacja: sprawdzenie telefonem, co naprawdę leży w lokalizacji
-- (razem z podlokalizacjami), w porównaniu z bazą.
--
-- Sesja pamięta nazwę (ścieżkę) lokalizacji z chwili rozpoczęcia — raport
-- zostaje czytelny także po jej usunięciu albo przemianowaniu.

CREATE TABLE inwentaryzacja (
  id                 INTEGER PRIMARY KEY,
  lokalizacja_id     INTEGER REFERENCES lokalizacja(id) ON DELETE SET NULL,
  lokalizacja_nazwa  TEXT NOT NULL,
  rozpoczeto         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  zakonczono         TEXT
);

-- Wynik dla egzemplarza w sesji:
--   na_miejscu      zeskanowany, według bazy leży w sprawdzanej lokalizacji
--   nie_na_miejscu  zeskanowany, według bazy leży gdzie indziej (albo nigdzie)
--   brak            powinien tu być, a nie został zeskanowany (wpisywane na koniec)
-- miejsce_w_bazie: ścieżka lokalizacji według bazy w chwili skanu — raport
-- pokazuje, skąd egzemplarz „przyszedł”, nawet gdy później go przeniesiono.
CREATE TABLE inwentaryzacja_wynik (
  inwentaryzacja_id  INTEGER NOT NULL REFERENCES inwentaryzacja(id) ON DELETE CASCADE,
  egzemplarz_id      INTEGER NOT NULL REFERENCES egzemplarz(id) ON DELETE CASCADE,
  wynik              TEXT NOT NULL CHECK (wynik IN ('na_miejscu', 'nie_na_miejscu', 'brak')),
  miejsce_w_bazie    TEXT,
  kolejnosc          INTEGER NOT NULL,
  skanowano          TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  PRIMARY KEY (inwentaryzacja_id, egzemplarz_id)
);

CREATE INDEX ix_inw_lokalizacja ON inwentaryzacja(lokalizacja_id);
CREATE INDEX ix_inw_wynik_egz ON inwentaryzacja_wynik(egzemplarz_id);
