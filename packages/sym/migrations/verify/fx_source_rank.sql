-- Verify sym:fx_source_rank on pg

BEGIN;

-- Asserts the tier ordering + unknown fallthrough; 1/0 forces a verify failure if wrong.
SELECT CASE
    WHEN fx_source_rank('frankfurter') = 10
     AND fx_source_rank('ecb') = 20
     AND fx_source_rank('fawazahmed0') = 30
     AND fx_source_rank('something_else') = 100
    THEN 1 ELSE 1 / 0 END;

ROLLBACK;
