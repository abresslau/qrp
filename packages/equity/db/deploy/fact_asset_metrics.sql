-- Deploy equity:fact_asset_metrics to pg

BEGIN;

-- Asset-level risk metrics: per (composite_figi, window_id, as_of_date) annualized volatility and
-- Sharpe of the security's OWN daily returns over the window's (base, as_of] span — the risk-adjusted
-- twin of fact_returns' point-to-point returns. Loader-written in the SAME per-figi pass as
-- fact_returns/fact_price_extremes; input_hash dirty-set; gated rows held NULL (AR-9). vol/sharpe on
-- BOTH pr (split-adjusted) and tr (dividend-reinvested) daily series. n_obs = daily-return count in
-- the window (consumers apply their own floor, e.g. signals.vol_1y keeps its >=60). Values are
-- fractions (0.18 = 18% annualized vol), rf=0 for Sharpe. composite_figi -> securities is SOFT (sym).
CREATE TABLE IF NOT EXISTS equity.fact_asset_metrics (
    composite_figi character(12) NOT NULL,
    window_id integer NOT NULL,
    as_of_date date NOT NULL,
    vol_pr numeric,
    vol_tr numeric,
    sharpe_pr numeric,
    sharpe_tr numeric,
    n_obs integer DEFAULT 0 NOT NULL,
    input_hash text NOT NULL,
    gated boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT fact_asset_metrics_pk PRIMARY KEY (composite_figi, window_id, as_of_date),
    CONSTRAINT fact_asset_metrics_window_fk FOREIGN KEY (window_id)
        REFERENCES equity.return_window(window_id)
);
COMMENT ON TABLE equity.fact_asset_metrics IS
    'Materialized per-window asset-level volatility + Sharpe (annualized x sqrt(252), rf=0) on the '
    'pr and tr daily-return series. Loader-written; input_hash dirty-set; gated rows held NULL; n_obs '
    'lets consumers apply their own min-obs floor. composite_figi -> securities is a SOFT reference.';

CREATE INDEX IF NOT EXISTS idx_fact_asset_metrics_as_of_date_window
    ON equity.fact_asset_metrics USING btree (as_of_date, window_id);
CREATE INDEX IF NOT EXISTS idx_fact_asset_metrics_published
    ON equity.fact_asset_metrics USING btree (as_of_date, window_id) WHERE (NOT gated);

DROP TRIGGER IF EXISTS fact_asset_metrics_set_updated_at ON equity.fact_asset_metrics;
CREATE TRIGGER fact_asset_metrics_set_updated_at BEFORE UPDATE ON equity.fact_asset_metrics
    FOR EACH ROW EXECUTE FUNCTION equity.set_updated_at();

COMMIT;
