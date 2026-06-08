-- Deploy sym:fact_returns to pg
-- requires: v_prices_adjusted

-- The materialized returns layer (AR-7). fact_returns is a LOADER-WRITTEN table
-- (not a materialized view) so refresh is incremental (dirty-set) and rows carry
-- provenance (input_hash). The 20M-row spike (Story 3.3) showed a live full-view
-- scan is ~9 min, so the matrix must be materialized and read cross-sectionally.
BEGIN;

-- Window reference (mirrors src/sym/returns/windows.py). window_id is the stable key.
CREATE TABLE return_window (
    window_id   INTEGER PRIMARY KEY,
    code        TEXT    NOT NULL UNIQUE,
    label       TEXT    NOT NULL,
    kind        TEXT    NOT NULL,
    annualized  BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT return_window_kind_chk CHECK (kind IN ('calendar', 'rolling', 'multiyear', 'ipo'))
);

INSERT INTO return_window (window_id, code, label, kind, annualized) VALUES
    (1,  '1D',      '1 day',                 'calendar',  false),
    (2,  'WTD',     'Week to date',          'calendar',  false),
    (3,  'MTD',     'Month to date',         'calendar',  false),
    (4,  'QTD',     'Quarter to date',       'calendar',  false),
    (5,  'YTD',     'Year to date',          'calendar',  false),
    (6,  '1W',      '1 week',                'rolling',   false),
    (7,  '1M',      '1 month',               'rolling',   false),
    (8,  '3M',      '3 months',              'rolling',   false),
    (9,  '6M',      '6 months',              'rolling',   false),
    (10, '9M',      '9 months',              'rolling',   false),
    (11, '1Y',      '1 year',                'rolling',   false),
    (12, '2Y_ANN',  '2 years annualized',    'multiyear', true),
    (13, '3Y_ANN',  '3 years annualized',    'multiyear', true),
    (14, '5Y_ANN',  '5 years annualized',    'multiyear', true),
    (15, '10Y_ANN', '10 years annualized',   'multiyear', true),
    (16, '20Y_ANN', '20 years annualized',   'multiyear', true),
    (17, '30Y_ANN', '30 years annualized',   'multiyear', true),
    (18, 'IPO_ANN', 'Since IPO annualized',  'ipo',       true);

CREATE TABLE fact_returns (
    composite_figi  CHAR(12)    NOT NULL,
    window_id       INTEGER     NOT NULL,
    asof            DATE        NOT NULL,
    pr              NUMERIC,
    tr              NUMERIC,
    input_hash      TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_returns_pk PRIMARY KEY (composite_figi, window_id, asof),
    CONSTRAINT fact_returns_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    CONSTRAINT fact_returns_window_fk     FOREIGN KEY (window_id) REFERENCES return_window (window_id)
);

-- Cross-sectional access: "all securities for one asof + window" (SM-4, <10s).
CREATE INDEX idx_fact_returns_asof_window ON fact_returns (asof, window_id);

CREATE TRIGGER fact_returns_set_updated_at
    BEFORE UPDATE ON fact_returns FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE fact_returns IS 'Materialized PR/TR matrix (AR-7). Loader-written (not a materialized view); incremental dirty-set refresh; each row stamped input_hash = hash(raw_slice + factor_set + calendar_version).';

COMMIT;
