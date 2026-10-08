-- =====================================================================
-- NORNICA / VOLE — migracja 001: schemat początkowy
--
-- Zasady:
--  * identyfikatory po polsku, bez polskich znaków,
--  * nazwy wyświetlane (słowniki) w JSON: {"en": "...", "pl": "..."},
--  * nazwane ograniczenia CHECK i komunikaty RAISE to klucze tłumaczeń
--    z przedrostkiem "blad." — program tłumaczy je w chwili wyświetlenia,
--  * znaczniki czasu w UTC z milisekundami, przeliczane na czas lokalny
--    w GUI i raportach,
--  * klucze obce do słowników i hierarchii: jawne ON DELETE RESTRICT
--    (celowa blokada; przed usunięciem program sam liczy zależności
--    i pokazuje czytelny komunikat — patrz baza/zaleznosci.py),
--  * nazwy i kody z COLLATE NOCASE (porównania i sortowanie bez wielkości
--    liter w zakresie ASCII; polskie litery sortuje kolacja NORNICA
--    rejestrowana w Pythonie — patrz baza/polaczenie.py).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Ustawienia programu (język, domyślna waluta, prefiks kodów...)
-- ---------------------------------------------------------------------
CREATE TABLE ustawienia (
  klucz   TEXT PRIMARY KEY,
  wartosc TEXT
);

-- Liczniki kodów inwentarzowych i etykiet lokalizacji. Numer nigdy nie
-- wraca do puli, nawet po usunięciu rekordu: wydrukowana etykieta nie
-- może po latach wskazywać innego sprzętu.
CREATE TABLE licznik (
  nazwa    TEXT PRIMARY KEY,
  wartosc  INTEGER NOT NULL DEFAULT 0 CHECK (wartosc >= 0)
);
INSERT INTO licznik (nazwa, wartosc) VALUES ('egzemplarz', 0), ('lokalizacja', 0);

-- ---------------------------------------------------------------------
-- Słowniki
-- ---------------------------------------------------------------------
CREATE TABLE kategoria (
  id                INTEGER PRIMARY KEY,
  kod               TEXT UNIQUE,              -- stały kod dla danych startowych; NULL dla własnych
  rodzic_id         INTEGER REFERENCES kategoria(id) ON DELETE RESTRICT,
  rodzaj            TEXT NOT NULL CHECK (rodzaj IN
                    ('komputer_fabryczny','skladak','czesc','akcesorium')),
  nazwy             TEXT NOT NULL CHECK (json_valid(nazwy)),
  szablon_atrybutow TEXT CHECK (szablon_atrybutow IS NULL OR json_valid(szablon_atrybutow)),
  kolejnosc         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE producent (
  id     INTEGER PRIMARY KEY,
  nazwa  TEXT NOT NULL UNIQUE COLLATE NOCASE,
  uwagi  TEXT
);

CREATE TABLE status (
  id         INTEGER PRIMARY KEY,
  kod        TEXT UNIQUE,
  nazwy      TEXT NOT NULL CHECK (json_valid(nazwy)),
  kolejnosc  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE waluta (
  kod            TEXT PRIMARY KEY CHECK (length(kod) = 3),   -- ISO 4217
  nazwy          TEXT NOT NULL CHECK (json_valid(nazwy)),
  miejsca_dzies  INTEGER NOT NULL DEFAULT 2 CHECK (miejsca_dzies BETWEEN 0 AND 4),
  historyczna    INTEGER NOT NULL DEFAULT 0 CHECK (historyczna IN (0, 1))
);

CREATE TABLE lokalizacja (
  id            INTEGER PRIMARY KEY,
  rodzic_id     INTEGER REFERENCES lokalizacja(id) ON DELETE RESTRICT,
  nazwa         TEXT NOT NULL COLLATE NOCASE,
  typ           TEXT CHECK (typ IN ('pokoj','regal','polka','pudelko','szuflada','inne')),
  kod_etykiety  TEXT UNIQUE COLLATE NOCASE,  -- np. 'LOC-0012', do skanera
  uwagi         TEXT
);

CREATE TABLE zlacze_typ (
  id         INTEGER PRIMARY KEY,
  kod        TEXT UNIQUE,                    -- 'isa16', 'socket7', 'db9_joystick'...
  rodzaj     TEXT NOT NULL CHECK (rodzaj IN ('port','slot','gniazdo','interfejs')),
  nazwy      TEXT NOT NULL CHECK (json_valid(nazwy)),
  kolejnosc  INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- Katalog modeli: „co to jest”
-- ---------------------------------------------------------------------
CREATE TABLE model (
  id             INTEGER PRIMARY KEY,
  kategoria_id   INTEGER NOT NULL REFERENCES kategoria(id) ON DELETE RESTRICT,
  producent_id   INTEGER REFERENCES producent(id) ON DELETE RESTRICT,
  nazwa          TEXT NOT NULL COLLATE NOCASE,
  numer_czesci   TEXT COLLATE NOCASE,
  rok_od         INTEGER,
  rok_do         INTEGER,
  opis           TEXT,
  atrybuty       TEXT CHECK (atrybuty IS NULL OR json_valid(atrybuty)),
  zrodlo_url     TEXT,                       -- strona w The Retro Web
  zaimportowano  TEXT,                       -- data importu; NULL = wpis ręczny
  utworzono      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  zmieniono      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  CONSTRAINT model_lata CHECK (rok_od IS NULL OR rok_do IS NULL OR rok_do >= rok_od)
);

-- Zwykłe UNIQUE(producent_id, nazwa, numer_czesci) przepuściłoby duplikaty,
-- bo w SQL każdy NULL jest różny od innego NULL. Indeks na wyrażeniach
-- zamienia NULL na wartość stałą i blokuje powtórki. Kolumna `nazwa`
-- dziedziczy NOCASE z definicji; wynik funkcji ifnull() kolacji nie
-- dziedziczy, więc przy numerze części jest ona podana jawnie.
CREATE UNIQUE INDEX ux_model_tozsamosc
  ON model (ifnull(producent_id, 0), nazwa, ifnull(numer_czesci, '') COLLATE NOCASE);

CREATE TABLE model_zlacze (
  model_id       INTEGER NOT NULL REFERENCES model(id) ON DELETE CASCADE,
  zlacze_typ_id  INTEGER NOT NULL REFERENCES zlacze_typ(id) ON DELETE RESTRICT,
  rola           TEXT NOT NULL CHECK (rola IN ('posiada','wymaga')),
  ilosc          INTEGER NOT NULL DEFAULT 1 CHECK (ilosc >= 1),
  PRIMARY KEY (model_id, zlacze_typ_id, rola)
);

-- ---------------------------------------------------------------------
-- Egzemplarze: „co konkretnie mam”
-- ilosc = 1  -> sztuka (może mieć numer seryjny, być zamontowana)
-- ilosc > 1  -> partia identycznych części o wspólnym statusie
-- ---------------------------------------------------------------------
CREATE TABLE egzemplarz (
  id                INTEGER PRIMARY KEY,
  kod_inwentarzowy  TEXT UNIQUE COLLATE NOCASE,  -- 'NOR-000123', z licznika
  model_id          INTEGER REFERENCES model(id) ON DELETE RESTRICT,
  nazwa_wlasna      TEXT COLLATE NOCASE,     -- dla składaków
  numer_seryjny     TEXT COLLATE NOCASE,
  rewizja           TEXT,
  status_id         INTEGER NOT NULL REFERENCES status(id) ON DELETE RESTRICT,
  stan_wizualny     TEXT CHECK (stan_wizualny IN
                    ('idealny','bardzo_dobry','dobry','zuzyty','slaby')),
  -- RESTRICT, a nie SET NULL: usunięcie komputera nie może po cichu
  -- wysypać jego części „w nicość” bez lokalizacji. Program najpierw
  -- demontuje części (przenosząc je w wybrane miejsce), potem usuwa.
  rodzic_id         INTEGER REFERENCES egzemplarz(id) ON DELETE RESTRICT,
  pozycja_montazu   TEXT,                    -- 'ISA #3', 'IDE Primary Master'
  lokalizacja_id    INTEGER REFERENCES lokalizacja(id) ON DELETE RESTRICT,
  ilosc             INTEGER NOT NULL DEFAULT 1 CHECK (ilosc >= 1),
  atrybuty          TEXT CHECK (atrybuty IS NULL OR json_valid(atrybuty)),
  -- dane prywatne (domyślnie pomijane w eksporcie)
  data_nabycia      TEXT,
  zrodlo_nabycia    TEXT,
  cena_minor        INTEGER CHECK (cena_minor IS NULL OR cena_minor >= 0),  -- grosze, centy
  waluta_kod        TEXT REFERENCES waluta(kod) ON DELETE RESTRICT,
  -- --------------------------------------
  uwagi             TEXT,
  utworzono         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  zmieniono         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  CONSTRAINT egzemplarz_model_lub_nazwa
    CHECK (model_id IS NOT NULL OR nazwa_wlasna IS NOT NULL),
  CONSTRAINT zamontowany_bez_lokalizacji
    CHECK (rodzic_id IS NULL OR lokalizacja_id IS NULL),
  CONSTRAINT partia_bez_seryjnego_i_montazu
    CHECK (ilosc = 1 OR (numer_seryjny IS NULL AND rodzic_id IS NULL)),
  CONSTRAINT cena_wymaga_waluty
    CHECK (cena_minor IS NULL OR waluta_kod IS NOT NULL)
);

CREATE TABLE egzemplarz_zlacze (             -- modyfikacje względem modelu
  egzemplarz_id  INTEGER NOT NULL REFERENCES egzemplarz(id) ON DELETE CASCADE,
  zlacze_typ_id  INTEGER NOT NULL REFERENCES zlacze_typ(id) ON DELETE RESTRICT,
  rola           TEXT NOT NULL CHECK (rola IN ('posiada','wymaga')),
  ilosc          INTEGER NOT NULL CHECK (ilosc >= 0),   -- 0 = usunięte względem modelu
  PRIMARY KEY (egzemplarz_id, zlacze_typ_id, rola)
);

-- ---------------------------------------------------------------------
-- Zasoby: oryginały w folderze danych, miniatury w bazie
-- ---------------------------------------------------------------------
CREATE TABLE zasob (
  id            INTEGER PRIMARY KEY,
  typ           TEXT NOT NULL CHECK (typ IN
                ('instrukcja','sterownik','bios','rom','dokumentacja','zdjecie','notatka','link')),
  tytul         TEXT NOT NULL,
  url           TEXT,
  plik_sciezka  TEXT,                        -- względna, w folderze danych programu
  plik_sha256   TEXT,
  plik_rozmiar  INTEGER,
  miniatura     BLOB,
  tresc         TEXT,
  wersja        TEXT,
  dodano        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  CONSTRAINT zasob_ma_tresc
    CHECK (url IS NOT NULL OR plik_sciezka IS NOT NULL OR tresc IS NOT NULL)
);

CREATE TABLE zasob_powiazanie (
  zasob_id       INTEGER NOT NULL REFERENCES zasob(id) ON DELETE CASCADE,
  kategoria_id   INTEGER REFERENCES kategoria(id)  ON DELETE CASCADE,
  model_id       INTEGER REFERENCES model(id)      ON DELETE CASCADE,
  egzemplarz_id  INTEGER REFERENCES egzemplarz(id) ON DELETE CASCADE,
  CONSTRAINT zasob_jedno_powiazanie
    CHECK ((kategoria_id IS NOT NULL) + (model_id IS NOT NULL)
           + (egzemplarz_id IS NOT NULL) = 1)
);

-- ---------------------------------------------------------------------
-- Historia: tylko testy i naprawy (naprawa ma podtyp)
-- ---------------------------------------------------------------------
CREATE TABLE zdarzenie (
  id             INTEGER PRIMARY KEY,
  egzemplarz_id  INTEGER NOT NULL REFERENCES egzemplarz(id) ON DELETE CASCADE,
  data           TEXT NOT NULL DEFAULT CURRENT_DATE,
  typ            TEXT NOT NULL CHECK (typ IN ('test','naprawa')),
  podtyp         TEXT CHECK (podtyp IN ('naprawa','modyfikacja')),
  wynik          TEXT CHECK (wynik IN ('ok','czesciowo','blad')),
  opis           TEXT,
  CONSTRAINT zdarzenie_podtyp CHECK ((typ = 'naprawa') = (podtyp IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- Pamięć podręczna wyszukiwań w źródłach zewnętrznych
-- ---------------------------------------------------------------------
CREATE TABLE cache_wyszukiwania (
  id         INTEGER PRIMARY KEY,
  zrodlo     TEXT NOT NULL,                  -- 'theretroweb'
  zapytanie  TEXT NOT NULL,
  wynik      TEXT CHECK (wynik IS NULL OR json_valid(wynik)),
  pobrano    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
  UNIQUE (zrodlo, zapytanie)
);

-- =====================================================================
-- Indeksy (SQLite nie zakłada ich samodzielnie na kluczach obcych)
-- =====================================================================
CREATE INDEX ix_kat_rodzic       ON kategoria(rodzic_id);
CREATE INDEX ix_lok_rodzic       ON lokalizacja(rodzic_id);
CREATE INDEX ix_model_kategoria  ON model(kategoria_id);
CREATE INDEX ix_model_producent  ON model(producent_id);
CREATE INDEX ix_egz_model        ON egzemplarz(model_id);
CREATE INDEX ix_egz_lokalizacja  ON egzemplarz(lokalizacja_id);
CREATE INDEX ix_egz_status       ON egzemplarz(status_id);
CREATE INDEX ix_egz_rodzic       ON egzemplarz(rodzic_id);
CREATE INDEX ix_egz_seryjny      ON egzemplarz(numer_seryjny);
CREATE INDEX ix_egz_waluta       ON egzemplarz(waluta_kod);
CREATE INDEX ix_mzl_typ          ON model_zlacze(zlacze_typ_id);
CREATE INDEX ix_ezl_typ          ON egzemplarz_zlacze(zlacze_typ_id);
CREATE INDEX ix_zdarzenie_egz    ON zdarzenie(egzemplarz_id, data);
CREATE UNIQUE INDEX ix_zasob_sha ON zasob(plik_sha256) WHERE plik_sha256 IS NOT NULL;

CREATE UNIQUE INDEX ux_zp_kat ON zasob_powiazanie(zasob_id, kategoria_id)  WHERE kategoria_id  IS NOT NULL;
CREATE UNIQUE INDEX ux_zp_mod ON zasob_powiazanie(zasob_id, model_id)      WHERE model_id      IS NOT NULL;
CREATE UNIQUE INDEX ux_zp_egz ON zasob_powiazanie(zasob_id, egzemplarz_id) WHERE egzemplarz_id IS NOT NULL;
CREATE INDEX ix_zp_kat ON zasob_powiazanie(kategoria_id);
CREATE INDEX ix_zp_mod ON zasob_powiazanie(model_id);
CREATE INDEX ix_zp_egz ON zasob_powiazanie(egzemplarz_id);

-- =====================================================================
-- Wyzwalacze
-- =====================================================================

-- Automatyczny znacznik zmiany. Warunek WHEN chroni przed zapętleniem
-- i pozwala jawnie ustawić datę (np. przy imporcie z innej bazy).
CREATE TRIGGER tr_egzemplarz_zmieniono
AFTER UPDATE ON egzemplarz FOR EACH ROW
WHEN NEW.zmieniono IS OLD.zmieniono
BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.id;
END;

CREATE TRIGGER tr_model_zmieniono
AFTER UPDATE ON model FOR EACH ROW
WHEN NEW.zmieniono IS OLD.zmieniono
BEGIN
  UPDATE model SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.id;
END;

-- ---------------------------------------------------------------------
-- Zmiana w rekordach zależnych podbija `zmieniono` rodzica: złącza,
-- powiązania zasobów, edycja zasobu, testy i naprawy, montaż części.
-- Rekord „zmienia się”, gdy zmienia się cokolwiek, co do niego należy.
-- ---------------------------------------------------------------------
CREATE TRIGGER tr_mzl_ins AFTER INSERT ON model_zlacze BEGIN
  UPDATE model SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.model_id;
END;
CREATE TRIGGER tr_mzl_upd AFTER UPDATE ON model_zlacze BEGIN
  UPDATE model SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.model_id, NEW.model_id);
END;
CREATE TRIGGER tr_mzl_del AFTER DELETE ON model_zlacze BEGIN
  UPDATE model SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.model_id;
END;

CREATE TRIGGER tr_ezl_ins AFTER INSERT ON egzemplarz_zlacze BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.egzemplarz_id;
END;
CREATE TRIGGER tr_ezl_upd AFTER UPDATE ON egzemplarz_zlacze BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.egzemplarz_id, NEW.egzemplarz_id);
END;
CREATE TRIGGER tr_ezl_del AFTER DELETE ON egzemplarz_zlacze BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.egzemplarz_id;
END;

CREATE TRIGGER tr_zp_ins AFTER INSERT ON zasob_powiazanie BEGIN
  UPDATE model      SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.model_id;
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.egzemplarz_id;
END;
CREATE TRIGGER tr_zp_upd AFTER UPDATE ON zasob_powiazanie BEGIN
  UPDATE model      SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.model_id, NEW.model_id);
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.egzemplarz_id, NEW.egzemplarz_id);
END;
CREATE TRIGGER tr_zp_del AFTER DELETE ON zasob_powiazanie BEGIN
  UPDATE model      SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.model_id;
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.egzemplarz_id;
END;

-- Edycja zasobu (np. nowa wersja sterownika) dotyczy wszystkich powiązanych.
CREATE TRIGGER tr_zasob_upd AFTER UPDATE ON zasob BEGIN
  UPDATE model SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now'))
    WHERE id IN (SELECT model_id FROM zasob_powiazanie WHERE zasob_id = NEW.id);
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now'))
    WHERE id IN (SELECT egzemplarz_id FROM zasob_powiazanie WHERE zasob_id = NEW.id);
END;

CREATE TRIGGER tr_zdarzenie_ins AFTER INSERT ON zdarzenie BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.egzemplarz_id;
END;
CREATE TRIGGER tr_zdarzenie_upd AFTER UPDATE ON zdarzenie BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.egzemplarz_id, NEW.egzemplarz_id);
END;
CREATE TRIGGER tr_zdarzenie_del AFTER DELETE ON zdarzenie BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.egzemplarz_id;
END;

-- Montaż i demontaż zmieniają konfigurację urządzenia nadrzędnego.
CREATE TRIGGER tr_montaz_ins AFTER INSERT ON egzemplarz
WHEN NEW.rodzic_id IS NOT NULL BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = NEW.rodzic_id;
END;
CREATE TRIGGER tr_montaz_upd AFTER UPDATE OF rodzic_id ON egzemplarz
WHEN OLD.rodzic_id IS NOT NEW.rodzic_id BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id IN (OLD.rodzic_id, NEW.rodzic_id);
END;
CREATE TRIGGER tr_montaz_del AFTER DELETE ON egzemplarz
WHEN OLD.rodzic_id IS NOT NULL BEGIN
  UPDATE egzemplarz SET zmieniono = (strftime('%Y-%m-%d %H:%M:%f', 'now')) WHERE id = OLD.rodzic_id;
END;

-- Partia (ilosc > 1) nie może być rodzicem zamontowanych części.
CREATE TRIGGER tr_egz_rodzic_partia_ins
BEFORE INSERT ON egzemplarz FOR EACH ROW
WHEN NEW.rodzic_id IS NOT NULL
 AND (SELECT ilosc FROM egzemplarz WHERE id = NEW.rodzic_id) > 1
BEGIN
  SELECT RAISE(ABORT, 'blad.partia_jako_rodzic');
END;

CREATE TRIGGER tr_egz_rodzic_partia_upd
BEFORE UPDATE OF rodzic_id ON egzemplarz FOR EACH ROW
WHEN NEW.rodzic_id IS NOT NULL
 AND (SELECT ilosc FROM egzemplarz WHERE id = NEW.rodzic_id) > 1
BEGIN
  SELECT RAISE(ABORT, 'blad.partia_jako_rodzic');
END;

-- Egzemplarz z zamontowanymi częściami nie może stać się partią.
CREATE TRIGGER tr_egz_partia_z_dziecmi
BEFORE UPDATE OF ilosc ON egzemplarz FOR EACH ROW
WHEN NEW.ilosc > 1 AND EXISTS (SELECT 1 FROM egzemplarz WHERE rodzic_id = NEW.id)
BEGIN
  SELECT RAISE(ABORT, 'blad.partia_z_zamontowanymi');
END;

-- Najprostszy cykl (rekord rodzicem samego siebie). Dłuższe cykle
-- (A w B, B w A) sprawdza warstwa usług: SQLite nie pozwala na
-- rekurencyjne CTE wewnątrz wyzwalaczy.
CREATE TRIGGER tr_egz_cykl
BEFORE UPDATE OF rodzic_id ON egzemplarz FOR EACH ROW
WHEN NEW.rodzic_id = NEW.id
BEGIN
  SELECT RAISE(ABORT, 'blad.cykl_montazu');
END;

CREATE TRIGGER tr_lok_cykl
BEFORE UPDATE OF rodzic_id ON lokalizacja FOR EACH ROW
WHEN NEW.rodzic_id = NEW.id
BEGIN
  SELECT RAISE(ABORT, 'blad.cykl_drzewa');
END;

CREATE TRIGGER tr_kat_cykl
BEFORE UPDATE OF rodzic_id ON kategoria FOR EACH ROW
WHEN NEW.rodzic_id = NEW.id
BEGIN
  SELECT RAISE(ABORT, 'blad.cykl_drzewa');
END;

-- =====================================================================
-- Widoki
-- =====================================================================

-- Efektywna lokalizacja: część zamontowana dziedziczy miejsce po
-- egzemplarzu najwyżej w drzewie montażu.
-- UWAGA dla zapytań: widok zwraca wiersz dla każdego egzemplarza, ale
-- lokalizacja_id może być NULL (korzeń drzewa nie ma przydzielonego
-- miejsca, np. „leży na biurku”). Egzemplarze w uszkodzonym drzewie
-- (cykl) nie mają korzenia i w widoku nie występują wcale — wyłapuje je
-- kontrola spójności. Limit głębokości chroni przed nieskończoną pętlą.
CREATE VIEW v_egzemplarz_lokalizacja AS
WITH RECURSIVE w_gore(egzemplarz_id, biezacy_id, glebokosc) AS (
  SELECT id, id, 0 FROM egzemplarz
  UNION ALL
  SELECT w.egzemplarz_id, e.rodzic_id, w.glebokosc + 1
  FROM w_gore w
  JOIN egzemplarz e ON e.id = w.biezacy_id
  WHERE e.rodzic_id IS NOT NULL AND w.glebokosc < 64
)
SELECT w.egzemplarz_id, k.id AS korzen_id, k.lokalizacja_id
FROM w_gore w
JOIN egzemplarz k ON k.id = w.biezacy_id
WHERE k.rodzic_id IS NULL;

-- Pełna ścieżka lokalizacji: 'Regał A › Półka 2 › Pudełko #12'
CREATE VIEW v_lokalizacja_sciezka AS
WITH RECURSIVE sciezka(lokalizacja_id, biezacy_id, tekst, glebokosc) AS (
  SELECT id, rodzic_id, nazwa, 0 FROM lokalizacja
  UNION ALL
  SELECT s.lokalizacja_id, l.rodzic_id, l.nazwa || ' › ' || s.tekst, s.glebokosc + 1
  FROM sciezka s
  JOIN lokalizacja l ON l.id = s.biezacy_id
  WHERE s.glebokosc < 32
)
SELECT lokalizacja_id, tekst AS sciezka
FROM sciezka
WHERE biezacy_id IS NULL;
