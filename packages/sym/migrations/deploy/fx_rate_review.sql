-- Deploy sym:fx_rate_review to pg
-- requires: fx_rate

BEGIN;

-- Durable FX plausibility rejections (Story S.1 — FX NFR4's prices_review
-- analog). load_fx rejections previously lived only in an in-memory list:
-- printed once, then gone — and a GENUINE move beyond the band (peg break)
-- wedged the band forever with no visible queue item. A row here is the
-- operator's review surface; ACCEPTING it inserts the rate into fx_rate (the
-- steward vouches), which un-wedges the band naturally on the next load.
CREATE TABLE fx_rate_review (
    review_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quote_currency CHAR(3)     NOT NULL,
    as_of_date     DATE        NOT NULL,
    rate           NUMERIC     NOT NULL,
    prior_rate     NUMERIC,
    relative_move  NUMERIC,
    source         TEXT        NOT NULL,
    reason         TEXT        NOT NULL,
    reviewed       BOOLEAN     NOT NULL DEFAULT FALSE,
    resolution     TEXT,
    reviewed_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fx_rate_review_reason_chk
        CHECK (reason IN ('non_positive', 'band_exceeded')),
    CONSTRAINT fx_rate_review_resolution_chk
        CHECK (resolution IS NULL OR resolution IN ('accepted', 'rejected')),
    CONSTRAINT fx_rate_review_reviewed_chk CHECK (reviewed = (resolution IS NOT NULL))
);

-- One OPEN row per rejected observation: daily re-runs refresh, never duplicate.
-- Closing frees the key (a later recurrence re-queues fresh).
CREATE UNIQUE INDEX uq_fx_rate_review_open
    ON fx_rate_review (quote_currency, as_of_date, source) WHERE NOT reviewed;

COMMENT ON TABLE fx_rate_review IS
    'FX plausibility rejections awaiting stewarding (S.1). accept => rate inserted into fx_rate (un-wedges the band); reject => vendor garbage, closed.';

COMMIT;
