-- Deploy sym:fact_price_extremes to pg
-- requires: fact_returns

-- 52-week price extremes (Story 3.2-ext). A loader-written table (NOT a materialized
-- view) on the same rails as fact_returns: filled in load_returns' per-figi pass from
-- the adjusted close series. NOT a windowed return (so it is not in fact_returns /
-- return_window) — it is the trailing 365-calendar-day high/low of the adjusted close,
-- the session each was set, and how far the current close sits off each. Rows carry
-- input_hash (incremental dirty-set) and gated (AR-9: held NULL when the as-of or an
-- extreme date references an unreviewed prices_review flag).
BEGIN;

CREATE TABLE fact_price_extremes (
    composite_figi  CHAR(12)    NOT NULL,
    as_of_date      DATE        NOT NULL,
    high_52w        NUMERIC,
    low_52w         NUMERIC,
    high_52w_date   DATE,
    low_52w_date    DATE,
    pct_off_high    NUMERIC,
    pct_off_low     NUMERIC,
    input_hash      TEXT        NOT NULL,
    gated           BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_price_extremes_pk PRIMARY KEY (composite_figi, as_of_date),
    CONSTRAINT fact_price_extremes_securities_fk
        FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi)
);

-- Cross-sectional access: "all securities for one as_of_date" (e.g. near-52w-high screen).
CREATE INDEX idx_fact_price_extremes_as_of_date ON fact_price_extremes (as_of_date);
-- Published cross-section excludes gated rows (mirrors idx_fact_returns_published).
CREATE INDEX idx_fact_price_extremes_published
    ON fact_price_extremes (as_of_date) WHERE NOT gated;

CREATE TRIGGER fact_price_extremes_set_updated_at
    BEFORE UPDATE ON fact_price_extremes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE fact_price_extremes IS 'Materialized 52-week (trailing 365d) high/low of the adjusted close + pct-off, per (composite_figi, as_of_date). Loader-written in the returns pass; input_hash dirty-set; gated rows (AR-9) held NULL.';

COMMIT;
