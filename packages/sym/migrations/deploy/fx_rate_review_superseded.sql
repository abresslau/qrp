-- Deploy sym:fx_rate_review_superseded to pg
-- requires: fx_rate_review

BEGIN;

-- 'superseded' (Story S.1 review): when load_fx successfully INSERTS a rate
-- for a key that has an OPEN rejection row (the band un-wedged after an
-- earlier accept), the queued rejection is moot — the loader closes it as
-- superseded so a multi-day peg-break queue DRAINS instead of generating
-- daily WARN noise the operator must hand-reject.
ALTER TABLE fx_rate_review DROP CONSTRAINT fx_rate_review_resolution_chk;
ALTER TABLE fx_rate_review ADD CONSTRAINT fx_rate_review_resolution_chk
    CHECK (resolution IS NULL OR resolution IN ('accepted', 'rejected', 'superseded'));

COMMENT ON COLUMN fx_rate_review.relative_move IS
    'RATIO (not percent): abs(rate/prior - 1); NULL when no prior or rate <= 0.';
COMMENT ON COLUMN fx_rate_review.prior_rate IS
    'The band seed the rejected observation was compared against (NULL on a first observation).';
COMMENT ON COLUMN fx_rate_review.resolution IS
    'accepted (steward vouched; insert attempted) | rejected (vendor garbage) | superseded (a later load stored a rate for this key — queue item moot).';

COMMIT;
