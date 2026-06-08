-- Verify sym:fundamentals_market_cap_usd on pg

BEGIN;

SELECT market_cap_usd FROM fundamentals WHERE FALSE;

ROLLBACK;
