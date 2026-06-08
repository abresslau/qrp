-- Deploy sym:session_return_windows to pg
-- requires: fact_returns

BEGIN;

-- New window kind: trading-session-count lookback (5D, 10D) — distinct from the
-- calendar-offset 'rolling' windows. Widen the CHECK, then append the two windows.
ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;
ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'rolling', 'multiyear', 'ipo', 'session'));

-- Appended ids (19/20) keep window_id stable for the 9M+ existing fact_returns rows.
INSERT INTO return_window (window_id, code, label, kind, annualized) VALUES
    (19, '5D',  '5 trading days',  'session', false),
    (20, '10D', '10 trading days', 'session', false);

COMMIT;
