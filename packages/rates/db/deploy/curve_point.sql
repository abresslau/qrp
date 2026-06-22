-- Deploy rates:curve_point to pg

BEGIN;

-- The `rates` package's own database (NOT sym, NOT macro, NOT the qrp gateway database):
-- fixed-income yield curves. v1 stores the Bank of England's daily-published UK curves
-- VERBATIM (the published fitted grid is the observation; we do NOT re-bootstrap from raw
-- gilts) and derives prices/spreads on read. Idempotent.
--
-- BoE publishes (probed 2026-06-22): curve_set glc (gilt) + ois (SONIA/OIS); basis nominal,
-- real, inflation (gilt only — ois is nominal); rate_type spot + forward (NO par — BoE does
-- not publish par on these files); tenor in years (0.083..40); value in % per annum (real can
-- be NEGATIVE). as_of_date = the curve's STATED date from the file, never the ingest date.
CREATE SCHEMA IF NOT EXISTS rates;

-- One row per (curve_set, basis, rate_type, tenor, as_of_date). Two vintages in one row:
--   `value`       = latest estimate   (updated on a BoE restatement; what reads default to)
--   `first_value` = first-published   (immutable after first insert; the PIT / backtest read)
-- This mirrors the FX restatement intent + macro's `last_changed_at` marker, without exploding
-- rows. A backtest asks "what did we know on day D" by reading first_value.
CREATE TABLE IF NOT EXISTS rates.curve_point (
    curve_set           TEXT        NOT NULL,   -- 'glc' (gilt) | 'ois' (| 'blc' later)
    basis               TEXT        NOT NULL,   -- 'nominal' | 'real' | 'inflation' (RPI-based, lagged)
    rate_type           TEXT        NOT NULL,   -- 'spot' | 'forward'
    tenor               NUMERIC     NOT NULL,   -- maturity in YEARS (tenor-as-data; new tenors accepted)
    as_of_date          DATE        NOT NULL,   -- the curve's stated date (canonical as_of_date)
    value               NUMERIC     NOT NULL,   -- latest estimate, % per annum
    first_value         NUMERIC     NOT NULL,   -- first-published, % per annum (immutable)
    source              TEXT        NOT NULL DEFAULT 'boe',
    first_published_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- re-stamped only when `value` changes
    CONSTRAINT curve_point_pk PRIMARY KEY (curve_set, basis, rate_type, tenor, as_of_date),
    CONSTRAINT curve_point_set_chk       CHECK (curve_set IN ('glc', 'ois', 'blc')),
    CONSTRAINT curve_point_basis_chk     CHECK (basis IN ('nominal', 'real', 'inflation')),
    CONSTRAINT curve_point_rate_type_chk CHECK (rate_type IN ('spot', 'forward')),
    CONSTRAINT curve_point_tenor_chk     CHECK (tenor > 0 AND tenor <= 60),
    -- % per annum; allow negative (real yields went sub-zero post-2015) but band out gross corruption.
    CONSTRAINT curve_point_value_chk     CHECK (value > -10 AND value < 30),
    CONSTRAINT curve_point_first_chk     CHECK (first_value > -10 AND first_value < 30)
);

CREATE INDEX IF NOT EXISTS idx_curve_point_asof
    ON rates.curve_point (as_of_date);
CREATE INDEX IF NOT EXISTS idx_curve_point_series
    ON rates.curve_point (curve_set, basis, rate_type, as_of_date, tenor);

COMMENT ON TABLE rates.curve_point IS
    'BoE daily UK yield-curve grid, stored verbatim (immutable first_value + restated value). '
    'Short end anchors to Bank Rate (macro.observation, read on demand). Derive prices/spreads on read.';
COMMENT ON COLUMN rates.curve_point.basis IS
    'nominal | real | inflation. The inflation curve is RPI-based with the linker indexation lag — '
    'NEVER consume it as CPI expectations.';

-- Stewardship queue: a day-over-day move beyond the plausibility band lands here instead of in
-- curve_point (never a silent bad print). Operator reviews + promotes (out of v1 ingest).
CREATE TABLE IF NOT EXISTS rates.curve_point_review (
    curve_set    TEXT        NOT NULL,
    basis        TEXT        NOT NULL,
    rate_type    TEXT        NOT NULL,
    tenor        NUMERIC     NOT NULL,
    as_of_date   DATE        NOT NULL,
    value        NUMERIC     NOT NULL,
    prev_value   NUMERIC,
    reason       TEXT        NOT NULL,
    source       TEXT        NOT NULL DEFAULT 'boe',
    flagged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT curve_point_review_pk PRIMARY KEY (curve_set, basis, rate_type, tenor, as_of_date)
);

COMMIT;
