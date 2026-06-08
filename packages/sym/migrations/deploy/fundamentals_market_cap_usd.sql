-- Deploy sym:fundamentals_market_cap_usd to pg
-- requires: fundamentals
-- requires: fx_rate

BEGIN;

-- USD value of each fundamentals row's market_cap, at the row's as_of_date FX. A derived,
-- point-in-time snapshot (recomputed by recompute_market_cap_usd from market_cap x FX);
-- NULL when no USD-base rate resolves for the currency on/before the date (within the FX
-- outage cap). For arbitrary-date USD market cap use sym.marketcap.market_cap(figi, d, 'USD').
ALTER TABLE fundamentals ADD COLUMN market_cap_usd NUMERIC;

COMMENT ON COLUMN fundamentals.market_cap_usd IS 'market_cap restated to USD at the as_of_date FX (USD-base resolver, <=date within the outage cap). Derived snapshot; recompute via recompute_market_cap_usd after fundamentals+FX loads; NULL if no FX covers the currency/date.';

COMMIT;
