-- =====================================================================
-- NORNICA / VOLE — migracja 002: poprawki po trzeciej recenzji schematu
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Wyzwalacze znacznika `zmieniono` odporne na rekursję.
--
-- Poprzednia wersja przy PRAGMA recursive_triggers = ON wpadała w pętlę,
-- gdy rekord dostawał w jednym kroku drugi raz ten sam znacznik (np. dwie
-- części montowane jednym poleceniem do tego samego komputera). SQLite
-- zwraca tę samą wartość 'now' przez cały krok polecenia, więc NEW i OLD
-- są wtedy równe, a wyzwalacz uruchamiał sam siebie bez końca.
--
-- Strażnik w WHERE: gdy znacznik już ma bieżącą wartość, UPDATE nie
-- dotyka żadnego wiersza, więc żaden wyzwalacz nie startuje ponownie.
-- Schemat jest teraz bezpieczny niezależnie od ustawienia PRAGMA.
-- ---------------------------------------------------------------------
DROP TRIGGER tr_egzemplarz_zmieniono;
CREATE TRIGGER tr_egzemplarz_zmieniono
AFTER UPDATE ON egzemplarz FOR EACH ROW
WHEN NEW.zmieniono IS OLD.zmieniono
BEGIN
  UPDATE egzemplarz
     SET zmieniono = strftime('%Y-%m-%d %H:%M:%f', 'now')
   WHERE id = NEW.id
     AND zmieniono IS NOT strftime('%Y-%m-%d %H:%M:%f', 'now');
END;

DROP TRIGGER tr_model_zmieniono;
CREATE TRIGGER tr_model_zmieniono
AFTER UPDATE ON model FOR EACH ROW
WHEN NEW.zmieniono IS OLD.zmieniono
BEGIN
  UPDATE model
     SET zmieniono = strftime('%Y-%m-%d %H:%M:%f', 'now')
   WHERE id = NEW.id
     AND zmieniono IS NOT strftime('%Y-%m-%d %H:%M:%f', 'now');
END;

-- ---------------------------------------------------------------------
-- 2. Wartość zastępcza dla braku producenta: -1 zamiast 0.
-- INTEGER PRIMARY KEY przyjmie 0 wstawione jawnie (np. przy imporcie),
-- liczby ujemnej nie przydzieli nigdy sam. Kod programu nie nadaje
-- ujemnych identyfikatorów.
-- ---------------------------------------------------------------------
DROP INDEX ux_model_tozsamosc;
CREATE UNIQUE INDEX ux_model_tozsamosc
  ON model (ifnull(producent_id, -1), nazwa, ifnull(numer_czesci, '') COLLATE NOCASE);

-- ---------------------------------------------------------------------
-- 3. Indeks pod wyszukiwanie zasobów-sierot i kaskadę przy usuwaniu zasobu.
-- Istniejące indeksy z zasob_id na początku są częściowe (WHERE ...),
-- więc zapytanie „czy zasób ma jakiekolwiek powiązanie” nie mogło z nich
-- skorzystać i przeglądało całą tabelę.
-- ---------------------------------------------------------------------
CREATE INDEX ix_zp_zasob ON zasob_powiazanie(zasob_id);
