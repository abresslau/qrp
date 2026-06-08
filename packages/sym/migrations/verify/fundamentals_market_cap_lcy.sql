-- Verify sym:fundamentals_market_cap_lcy on pg

BEGIN;

SELECT market_cap_lcy, market_cap_usd FROM fundamentals WHERE FALSE;

ROLLBACK;
