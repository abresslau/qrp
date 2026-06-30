-- Deploy commodity:return_daily to pg

BEGIN;

-- Derived trailing-window price returns over the continuous front-month `settle` series, materialised
-- by commodity.returns.recompute_commodity_returns (mirrors equity fact_returns / index
-- fact_index_returns; reuses equity.returns.windows). RAW continuous series: returns INCLUDE roll-day
-- discontinuities (the package stores raw and never back-adjusts) — they are NOT roll-adjusted.
-- `window_code` is the equity.returns.windows code (1D / 1M / … / YTD / SI…); `ret` is the window
-- price return (cumulative ratio-1, or CAGR for the *_ANN windows); NULL = insufficient history (or a
-- non-positive settle, which the return rule treats as undefined). as_of_date = the settle trading date.
CREATE TABLE IF NOT EXISTS commodity.return_daily (
    commodity_code TEXT        NOT NULL,
    series_type    TEXT        NOT NULL DEFAULT 'continuous_front',
    window_code    TEXT        NOT NULL,
    as_of_date     DATE        NOT NULL,
    ret            NUMERIC,
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT return_daily_pk PRIMARY KEY (commodity_code, series_type, window_code, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_return_daily_date ON commodity.return_daily (as_of_date);
CREATE INDEX IF NOT EXISTS idx_return_daily_code_date
    ON commodity.return_daily (commodity_code, series_type, as_of_date);

COMMENT ON TABLE commodity.return_daily IS
    'Derived trailing-window price returns over the raw continuous front-month settle (mirrors '
    'fact_returns; includes roll discontinuities — NOT roll-adjusted). Recomputed from price_daily.';

COMMIT;
