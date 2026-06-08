-- Deploy sym:trailing_kind_prior_quarter to pg
-- requires: cumulative_multiyear_windows

BEGIN;

-- Return-window taxonomy v2:
--  (1) `kind` is an internal base-date *strategy*, not a financial category. The
--      rolling/multiyear split was only about lookback unit (months vs years) and
--      annualization (already a separate flag), so both collapse into `trailing`.
--  (2) Add the discrete prior-period kind `period` and the PQ window (last completed
--      calendar quarter — both endpoints in the past).
-- Drop the CHECK first so the relabel + insert are valid, then re-add the final set.
ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;

UPDATE return_window SET kind = 'trailing' WHERE kind IN ('rolling', 'multiyear');

INSERT INTO return_window (window_id, code, label, kind, annualized) VALUES
    (28, 'PQ', 'Last completed quarter', 'period', false);

ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'session', 'trailing', 'ipo', 'period'));

COMMIT;
