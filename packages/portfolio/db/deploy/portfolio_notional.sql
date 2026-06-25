-- Deploy portfolio:portfolio_notional to pg
-- requires: portfolios

BEGIN;

-- FR-15 PnL definition (Story Q5.2): the platform is weights-first, so PnL IS the
-- cumulative time-weighted return over a window; an OPTIONAL notional (in the
-- portfolio's base_currency) expresses it in money: pnl = notional * cumulative_return.
-- NULL means the operator chose not to state one — PnL is then served in return space
-- only, never against a fabricated notional.
ALTER TABLE portfolio.portfolio
    ADD COLUMN notional NUMERIC NULL CHECK (notional > 0);

COMMENT ON COLUMN portfolio.portfolio.notional IS
    'Optional reference notional in base_currency. PnL = notional * cumulative '
    'time-weighted return (FR-15 definition, Story Q5.2). NULL = return-space PnL only.';

COMMIT;
