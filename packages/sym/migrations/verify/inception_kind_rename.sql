-- Verify sym:inception_kind_rename on pg

BEGIN;

-- No 'ipo' kind remains; the two since-inception codes are present (errors if not).
SELECT 1 / (CASE WHEN (SELECT count(*) FROM return_window WHERE kind = 'ipo') = 0 THEN 1 ELSE 0 END);
SELECT 1 / (CASE WHEN (
    SELECT count(*) FROM return_window WHERE kind = 'inception' AND code IN ('SI', 'SI_ANN')
) = 2 THEN 1 ELSE 0 END);

ROLLBACK;
