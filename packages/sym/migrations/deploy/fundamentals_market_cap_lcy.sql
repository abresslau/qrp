-- Deploy sym:fundamentals_market_cap_lcy to pg
-- requires: fundamentals_market_cap_usd

BEGIN;

-- Rename market_cap -> market_cap_lcy (Local CurrencY) so it pairs explicitly with
-- market_cap_usd. Postgres updates the dependent CHECK + index column references on rename.
ALTER TABLE fundamentals RENAME COLUMN market_cap TO market_cap_lcy;

COMMENT ON COLUMN fundamentals.market_cap_lcy IS 'Market cap in the local (native) currency = close_raw x shares_outstanding at as_of_date. Pairs with market_cap_usd.';

COMMIT;
