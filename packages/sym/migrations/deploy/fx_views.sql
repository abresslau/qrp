-- Deploy sym:fx_views to pg
-- requires: fx_rate

BEGIN;

-- v_fx: both directions as a convenience (observed USD-base rows + their inverse). The
-- USD/USD=1 identity and the as-of/staleness policy live in the Python resolver (single
-- source of truth) -- this view is for ad-hoc DBeaver use, not triangulation.
CREATE VIEW v_fx AS
    SELECT base_currency, quote_currency, as_of_date, rate, source FROM fx_rate
    UNION ALL
    SELECT quote_currency, base_currency, as_of_date, 1 / rate, source FROM fx_rate;

-- v_fx_daily: dense Mon-Fri series per currency, forward-filling each weekday with the
-- last observed rate on/before it (flagged). Computed ON READ -- NO synthetic rows are
-- ever stored (same derive-don't-store principle as v_prices_adjusted). Weekends are not
-- generated (FX does not trade). is_filled / days_stale make a carried value explicit;
-- the outage cap (NULL past N days) is applied by the Python resolver, not here.
CREATE VIEW v_fx_daily AS
WITH bounds AS (
    SELECT quote_currency, min(as_of_date) AS first_date, max(as_of_date) AS last_date
      FROM fx_rate WHERE base_currency = 'USD'
     GROUP BY quote_currency
), weekdays AS (
    SELECT b.quote_currency, g::date AS weekday_date
      FROM bounds b
      CROSS JOIN generate_series(b.first_date, b.last_date, INTERVAL '1 day') AS g
     WHERE extract(isodow FROM g) < 6
)
SELECT w.quote_currency,
       w.weekday_date,
       lo.as_of_date AS observed_date,
       lo.rate,
       (w.weekday_date <> lo.as_of_date) AS is_filled,
       (w.weekday_date - lo.as_of_date) AS days_stale
  FROM weekdays w
  CROSS JOIN LATERAL (
      SELECT r.rate, r.as_of_date
        FROM fx_rate r
       WHERE r.base_currency = 'USD' AND r.quote_currency = w.quote_currency
         AND r.as_of_date <= w.weekday_date
       ORDER BY r.as_of_date DESC
       LIMIT 1
  ) lo;

COMMENT ON VIEW v_fx IS 'Bidirectional FX convenience: observed USD-base rows + their inverse. USD=1 identity + as-of/staleness are in the Python resolver, not here.';
COMMENT ON VIEW v_fx_daily IS 'Dense Mon-Fri USD-base series, forward-filled per weekday from the last observed rate (is_filled/days_stale flagged). Computed on read; no synthetic rows stored. Outage cap applied by the resolver.';

COMMIT;
