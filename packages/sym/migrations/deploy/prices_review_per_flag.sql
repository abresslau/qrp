-- Deploy sym:prices_review_per_flag to pg
-- requires: prices_review_sweep_flag

BEGIN;

-- One flag per (figi, date, TYPE) — Story S.1. Under the old (figi, date) PK an
-- audit sweep_divergence silently REPLACED an unreviewed price_jump (and vice
-- versa): two different findings about the same bar clobbered each other while
-- both awaited review. They now coexist.
ALTER TABLE prices_review DROP CONSTRAINT prices_review_pk;
ALTER TABLE prices_review ADD CONSTRAINT prices_review_pk
    PRIMARY KEY (composite_figi, session_date, flag_type);

COMMENT ON TABLE prices_review IS
    'Stage-1 anomaly flags, one per (figi, session_date, flag_type) — different findings about one bar coexist (S.1). Stage-2 gate excludes unreviewed-flag dates from fact_returns.';
COMMENT ON COLUMN prices_review.pct_move IS
    'TYPE-SCOPED by design: price_jump = SIGNED split-adjusted day-over-day move; sweep_divergence = UNSIGNED relative divergence vs stored raw; NULL for price_on_non_trading_day.';

COMMIT;
