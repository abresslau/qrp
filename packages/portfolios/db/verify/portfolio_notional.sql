-- Verify portfolios:portfolio_notional on pg

BEGIN;

SELECT notional FROM portfolios.portfolio WHERE FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'portfolios.portfolio'::regclass
           AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%notional%'
    ) THEN
        RAISE EXCEPTION 'notional positivity CHECK missing';
    END IF;
END
$$;

ROLLBACK;
