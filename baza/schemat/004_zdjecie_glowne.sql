-- =====================================================================
-- NORNICA / VOLE — migracja 004: zdjęcie główne egzemplarza
--
-- Zdjęcie pokazywane na karcie egzemplarza. Wybiera je użytkownik spośród
-- zdjęć widocznych przy egzemplarzu (własnych, modelu, kategorii).
-- Usunięcie zasobu czyści wybór (SET NULL) — karta pokazuje wtedy obrazek
-- zastępczy, a nie błąd.
-- =====================================================================
ALTER TABLE egzemplarz ADD COLUMN zdjecie_glowne_id INTEGER REFERENCES zasob(id) ON DELETE SET NULL;
CREATE INDEX ix_egz_zdjecie_glowne ON egzemplarz(zdjecie_glowne_id);
