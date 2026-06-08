-- Deploy sym:v_prices_adjusted to pg
-- requires: price_storage

-- The middle layer of the three-layer returns engine (AR-7): a deterministic view
-- that derives split-adjusted prices from raw prices + EXPLICIT split factors. No
-- stored adjusted column (FR-5/AR-7); factors come ONLY from corporate_actions
-- (AR-6 -- never reverse-engineered from price ratios).
BEGIN;

-- Exact NUMERIC product aggregate for cumulative split factors. (exp(sum(ln()))
-- would be float and turn a 4:1 split into 3.9999...; this is exact + deterministic.)
CREATE AGGREGATE product(numeric) (
    sfunc = numeric_mul,
    stype = numeric,
    initcond = '1'
);

-- adj_close = close_raw / (product of split ratios with ex_date AFTER this session).
-- Strictly-after: a price on/after the ex-date already reflects that split, so the
-- back-adjusted series is continuous across the split.
CREATE VIEW v_prices_adjusted AS
SELECT
    p.composite_figi,
    p.session_date,
    p.currency_code,
    p.close AS close_raw,
    f.split_factor,
    p.close / f.split_factor AS adj_close
FROM prices_raw p
CROSS JOIN LATERAL (
    SELECT COALESCE(product(ca.value), 1) AS split_factor
    FROM corporate_actions ca
    WHERE ca.composite_figi = p.composite_figi
      AND ca.action_type = 'split'
      AND ca.ex_date > p.session_date
) f;

COMMENT ON VIEW v_prices_adjusted IS 'Deterministic split-adjusted prices derived from prices_raw + explicit split factors (AR-7). adj_close = close_raw / product(future split ratios). No stored adjusted column; factors from corporate_actions only (AR-6). TR reinvestment is layered in Story 3.5.';

COMMIT;
