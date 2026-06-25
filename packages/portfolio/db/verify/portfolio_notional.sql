-- Verify portfolio:portfolio_notional on pg

BEGIN;

SELECT notional FROM portfolio.portfolio WHERE FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'portfolio.portfolio'::regclass
           AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%notional%'
    ) THEN
        RAISE EXCEPTION 'notional positivity CHECK missing';
    END IF;
END
$$;

ROLLBACK;
