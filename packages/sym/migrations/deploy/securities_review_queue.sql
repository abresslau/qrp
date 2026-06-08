-- Deploy sym:securities_review_queue to pg
-- requires: updated_at_trigger

BEGIN;

-- Holds identifier inputs that failed to resolve to a single CompositeFIGI
-- (FR-4 review surface). Intentionally decoupled from securities (no FK): these
-- rows describe inputs that have NO clean security yet. Fed by ingestion seeing
-- a ticker resolve to zero/multiple FIGIs and by OpenFIGI no-match/ambiguous.
CREATE TABLE securities_review_queue (
    review_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_key    TEXT        NOT NULL,
    source_input  JSONB       NOT NULL,
    candidates    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    status        TEXT        NOT NULL,
    detail        TEXT,
    resolved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT securities_review_queue_status_chk
        CHECK (status IN ('no_figi_found', 'ambiguous_figi', 'share_class_conflict')),
    CONSTRAINT securities_review_queue_candidates_chk
        CHECK (jsonb_typeof(candidates) = 'array')
);

-- At most one OPEN review per distinct unresolved input: a re-run must not
-- re-queue an input that is still pending (not auto-retried while queued).
-- Once resolved_at is set the key frees up, so a later recurrence can re-queue.
CREATE UNIQUE INDEX uq_securities_review_queue_open
    ON securities_review_queue (source_key)
    WHERE resolved_at IS NULL;

-- Supports "list/skip open items" scans by the assignment run.
CREATE INDEX idx_securities_review_queue_open
    ON securities_review_queue (created_at)
    WHERE resolved_at IS NULL;

CREATE TRIGGER securities_review_queue_set_updated_at
    BEFORE UPDATE ON securities_review_queue
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  securities_review_queue              IS 'FIGI-assignment issues awaiting steward resolution (FR-4). Decoupled from securities.';
COMMENT ON COLUMN securities_review_queue.source_key   IS 'Canonical dedupe key for the unresolved input, e.g. ''ticker:AAPL@XNAS'' or ''isin:US0378331005''.';
COMMENT ON COLUMN securities_review_queue.source_input IS 'Full raw identifier context from the resolution attempt.';
COMMENT ON COLUMN securities_review_queue.candidates   IS 'JSON array of candidate FIGI matches (for ambiguous_figi / share_class_conflict).';
COMMENT ON COLUMN securities_review_queue.status       IS 'Issue category: no_figi_found | ambiguous_figi | share_class_conflict.';
COMMENT ON COLUMN securities_review_queue.resolved_at  IS 'NULL while queued/unresolved; set when a steward resolves the item.';

COMMIT;
