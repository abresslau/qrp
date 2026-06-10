-- Revert sym:prices_review_per_flag from pg

BEGIN;

-- Mechanical revert: the narrow PK cannot represent multi-flag rows — keep the
-- LATEST flag per (figi, date), drop the rest (data loss is inherent to the
-- narrower model being restored; created_at picks the most recent finding).
DELETE FROM prices_review a
 USING prices_review b
 WHERE a.composite_figi = b.composite_figi
   AND a.session_date = b.session_date
   AND (a.created_at, a.ctid) < (b.created_at, b.ctid);

ALTER TABLE prices_review DROP CONSTRAINT prices_review_pk;
ALTER TABLE prices_review ADD CONSTRAINT prices_review_pk
    PRIMARY KEY (composite_figi, session_date);

COMMIT;
