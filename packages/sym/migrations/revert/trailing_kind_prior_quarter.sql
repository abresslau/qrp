-- Revert sym:trailing_kind_prior_quarter from pg

BEGIN;

DELETE FROM fact_returns       WHERE window_id = 28;
DELETE FROM fact_index_returns WHERE window_id = 28;
DELETE FROM return_window      WHERE window_id = 28;

ALTER TABLE return_window DROP CONSTRAINT return_window_kind_chk;

-- Restore the prior kind labels (sub-year/1Y were 'rolling'; the *_ANN multi-year
-- and cumulative 2Y..30Y were 'multiyear'); window 27 'IPO' stays 'ipo'.
UPDATE return_window SET kind = 'rolling'
 WHERE code IN ('1W', '1M', '3M', '6M', '9M', '1Y');
UPDATE return_window SET kind = 'multiyear'
 WHERE code IN ('2Y_ANN','3Y_ANN','5Y_ANN','10Y_ANN','20Y_ANN','30Y_ANN',
                '2Y','3Y','5Y','10Y','20Y','30Y');

ALTER TABLE return_window ADD CONSTRAINT return_window_kind_chk
    CHECK (kind IN ('calendar', 'rolling', 'multiyear', 'ipo', 'session'));

COMMIT;
