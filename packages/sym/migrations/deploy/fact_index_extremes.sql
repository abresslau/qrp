-- Deploy sym:fact_index_extremes to pg
-- requires: fact_index_returns

-- 52-week extremes for benchmark indexes (Story 3.2-ext) — the index sibling of
-- fact_price_extremes, mirroring the fact_returns <-> fact_index_returns split.
-- Computed in recompute_index_returns' per-series pass from index_levels.level as the
-- trailing 365-calendar-day high/low. No gate column: index levels carry no
-- prices_review flag, so index extremes never gate.
BEGIN;

CREATE TABLE fact_index_extremes (
    sym_id          BIGINT      NOT NULL,
    as_of_date      DATE        NOT NULL,
    high_52w        NUMERIC,
    low_52w         NUMERIC,
    high_52w_date   DATE,
    low_52w_date    DATE,
    pct_off_high    NUMERIC,
    pct_off_low     NUMERIC,
    input_hash      TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_index_extremes_pk PRIMARY KEY (sym_id, as_of_date),
    CONSTRAINT fact_index_extremes_sym_fk FOREIGN KEY (sym_id) REFERENCES instrument (sym_id)
);

CREATE INDEX idx_fact_index_extremes_as_of_date ON fact_index_extremes (as_of_date);

CREATE TRIGGER fact_index_extremes_set_updated_at
    BEFORE UPDATE ON fact_index_extremes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE fact_index_extremes IS 'Materialized 52-week (trailing 365d) high/low of the index level + pct-off, per (sym_id, as_of_date). Loader-written in the benchmark-returns pass; input_hash dirty-set; no gate (index levels are unflagged).';

COMMIT;
