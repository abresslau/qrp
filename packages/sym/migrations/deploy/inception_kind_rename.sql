-- Deploy sym:inception_kind_rename to pg
-- requires: trailing_kind_prior_quarter

BEGIN;

-- 'ipo' is equity-specific; an index/fund has an *inception* (base) date, not an IPO.
-- Rename the kind and the two since-inception window codes/labels. window_ids 18/27
-- are unchanged, so fact_returns rows (FK on window_id) are untouched.
ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;

UPDATE return_window SET kind = 'inception' WHERE kind = 'ipo';
UPDATE return_window SET code = 'SI_ANN', label = 'Since inception annualized' WHERE window_id = 18;
UPDATE return_window SET code = 'SI',     label = 'Since inception'            WHERE window_id = 27;

ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'session', 'trailing', 'inception', 'period'));

COMMIT;
