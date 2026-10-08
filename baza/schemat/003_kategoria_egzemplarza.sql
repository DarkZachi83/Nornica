-- =====================================================================
-- NORNICA / VOLE — migracja 003: kategoria egzemplarza bez modelu
--
-- Egzemplarz brał kategorię wyłącznie z modelu. Składak opisany samą
-- nazwą własną nie miał więc kategorii, a bez niej nie ma szablonu
-- atrybutów (przeznaczenie, system operacyjny...) ani miejsca w filtrach.
--
-- Reguła: dokładnie jedno z dwóch — albo model (kategoria z modelu),
-- albo kategoria wpisana wprost. Dwa źródła naraz mogłyby sobie
-- przeczyć, więc wyzwalacze na to nie pozwalają.
-- =====================================================================
ALTER TABLE egzemplarz ADD COLUMN kategoria_id INTEGER REFERENCES kategoria(id) ON DELETE RESTRICT;
CREATE INDEX ix_egz_kategoria ON egzemplarz(kategoria_id);

CREATE TRIGGER tr_egz_kategoria_ins
BEFORE INSERT ON egzemplarz FOR EACH ROW
WHEN (NEW.model_id IS NULL) = (NEW.kategoria_id IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'blad.egzemplarz_kategoria');
END;

CREATE TRIGGER tr_egz_kategoria_upd
BEFORE UPDATE OF model_id, kategoria_id ON egzemplarz FOR EACH ROW
WHEN (NEW.model_id IS NULL) = (NEW.kategoria_id IS NULL)
BEGIN
  SELECT RAISE(ABORT, 'blad.egzemplarz_kategoria');
END;

-- Efektywna kategoria egzemplarza, niezależnie od źródła.
CREATE VIEW v_egzemplarz_kategoria AS
SELECT e.id AS egzemplarz_id, coalesce(m.kategoria_id, e.kategoria_id) AS kategoria_id
FROM egzemplarz e
LEFT JOIN model m ON m.id = e.model_id;
