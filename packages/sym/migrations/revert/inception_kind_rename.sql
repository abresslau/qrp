-- Revert sym:inception_kind_rename from pg

BEGIN;

ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;

UPDATE return_window SET kind = 'ipo' WHERE kind = 'inception';
UPDATE return_window SET code = 'IPO_ANN', label = 'Since IPO annualized' WHERE window_id = 18;
UPDATE return_window SET code = 'IPO',     label = 'Since IPO'            WHERE window_id = 27;

ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'session', 'trailing', 'ipo', 'period'));

COMMIT;
