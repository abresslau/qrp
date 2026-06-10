-- Revert sym:fx_rate_review_superseded from pg

BEGIN;

-- Re-home superseded rows under 'rejected' so the narrower CHECK can apply.
UPDATE fx_rate_review SET resolution = 'rejected' WHERE resolution = 'superseded';
ALTER TABLE fx_rate_review DROP CONSTRAINT fx_rate_review_resolution_chk;
ALTER TABLE fx_rate_review ADD CONSTRAINT fx_rate_review_resolution_chk
    CHECK (resolution IS NULL OR resolution IN ('accepted', 'rejected'));

COMMIT;
