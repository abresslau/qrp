-- Revert sym:fx_views_precedence from pg

BEGIN;

-- Restore the pre-precedence v_fx_daily (tie-break by date only).
CREATE OR REPLACE VIEW v_fx_daily AS
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

COMMENT ON VIEW v_fx_daily IS 'Dense Mon-Fri USD-base series, forward-filled per weekday from the last observed rate (is_filled/days_stale flagged). Computed on read; no synthetic rows stored. Outage cap applied by the resolver.';

COMMIT;
