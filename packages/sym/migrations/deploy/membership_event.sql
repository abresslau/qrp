-- Deploy sym:membership_event to pg
-- requires: universe

BEGIN;

-- Append-only membership change-event log (Story U1.2, AR-6/AR-10). This is the
-- *truth* for universe membership; the universe_membership interval table
-- (U1.4) is a projection of it. Rows are NEVER updated -- a correction is a new
-- change='correct' event, not a mutation -- so there is deliberately no
-- updated_at column / trigger here.
CREATE TABLE membership_event (
    event_id                  BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id               TEXT        NOT NULL,
    raw_identifier            TEXT        NOT NULL,
    change                    TEXT        NOT NULL,
    effective_date            DATE        NOT NULL,
    effective_date_precision  TEXT        NOT NULL DEFAULT 'exact',
    source                    TEXT        NOT NULL,
    provenance                JSONB,
    recorded_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT membership_event_universe_fk  FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT membership_event_change_chk   CHECK (change IN ('join', 'leave', 'correct')),
    CONSTRAINT membership_event_precision_chk CHECK (effective_date_precision IN ('exact', 'poll_bounded')),
    -- Dedupe: the same change for the same member on the same date is one event,
    -- regardless of how many sources report it (idempotent append). Two sources
    -- reporting different effective dates are different rows -> both kept.
    CONSTRAINT membership_event_dedupe_uq    UNIQUE (universe_id, raw_identifier, change, effective_date)
);

-- Projection reads all events for a universe in order (U1.4).
CREATE INDEX idx_membership_event_universe ON membership_event (universe_id, effective_date, event_id);

COMMENT ON TABLE  membership_event                          IS 'Append-only membership change-event log (Story U1.2, AR-6/AR-10). The truth; universe_membership is its projection. Immutable -- corrections are change=correct events, never mutations.';
COMMENT ON COLUMN membership_event.change                   IS 'join | leave | correct (a corrective event reversing/adjusting an earlier one).';
COMMENT ON COLUMN membership_event.effective_date_precision IS 'exact (dated source) | poll_bounded (snapshot diff; uncertain within the polling gap).';
COMMENT ON COLUMN membership_event.provenance               IS 'Source-specific provenance (e.g. fetch time, file/URL, corroboration status).';

COMMIT;
