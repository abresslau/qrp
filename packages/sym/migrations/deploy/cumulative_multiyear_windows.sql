-- Deploy sym:cumulative_multiyear_windows to pg
-- requires: session_return_windows

BEGIN;

-- Cumulative (annualized=false) total-return siblings of the *_ANN multi-year
-- windows, plus a cumulative since-IPO total. Kinds 'multiyear'/'ipo' already
-- pass the CHECK, so no constraint change. Appended ids (21..27) keep window_id
-- stable for existing fact_returns rows.
INSERT INTO return_window (window_id, code, label, kind, annualized) VALUES
    (21, '2Y',  '2 years',    'multiyear', false),
    (22, '3Y',  '3 years',    'multiyear', false),
    (23, '5Y',  '5 years',    'multiyear', false),
    (24, '10Y', '10 years',   'multiyear', false),
    (25, '20Y', '20 years',   'multiyear', false),
    (26, '30Y', '30 years',   'multiyear', false),
    (27, 'IPO', 'Since IPO',  'ipo',       false);

COMMIT;
