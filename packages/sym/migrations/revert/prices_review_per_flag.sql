-- Revert sym:prices_review_per_flag from pg
-- NOTE: fails if multi-flag rows exist for one (figi, date) — resolve or delete
-- the extra flags first; the narrow PK cannot represent them.

BEGIN;

ALTER TABLE prices_review DROP CONSTRAINT prices_review_pk;
ALTER TABLE prices_review ADD CONSTRAINT prices_review_pk
    PRIMARY KEY (composite_figi, session_date);

COMMIT;
