-- Deploy sym:membership_proposal to pg
-- requires: universe

BEGIN;

-- Two-stage membership change staging (Story U3.2, AR-9). A monitor-discovered
-- change that is *surprising* (churn beyond a guard threshold) or not yet
-- corroborated lands here as a PROPOSAL, NOT directly in the append-only event
-- log. A proposal is promoted to a membership_event only when it persists N days
-- or a second source confirms it, or an operator confirms it in `universe review`.
-- This table is mutable staging (seen_count/status transition) — the event log
-- it feeds stays append-only and immutable.
CREATE TABLE membership_proposal (
    proposal_id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id              TEXT        NOT NULL,
    raw_identifier           TEXT        NOT NULL,
    change                   TEXT        NOT NULL,
    effective_date           DATE        NOT NULL,
    effective_date_precision TEXT        NOT NULL DEFAULT 'poll_bounded',
    source                   TEXT        NOT NULL,
    first_seen               DATE        NOT NULL,
    last_seen                DATE        NOT NULL,
    seen_count               INTEGER     NOT NULL DEFAULT 1,
    corroborating_sources    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    status                   TEXT        NOT NULL DEFAULT 'pending',
    reason                   TEXT,
    decided_at               TIMESTAMPTZ,
    decided_by               TEXT,
    detail                   TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT membership_proposal_universe_fk FOREIGN KEY (universe_id)
        REFERENCES universe (universe_id),
    CONSTRAINT membership_proposal_change_chk CHECK (change IN ('join', 'leave', 'correct')),
    CONSTRAINT membership_proposal_status_chk CHECK (status IN ('pending', 'confirmed', 'rejected')),
    CONSTRAINT membership_proposal_precision_chk
        CHECK (effective_date_precision IN ('exact', 'poll_bounded')),
    CONSTRAINT membership_proposal_seen_chk CHECK (seen_count >= 1),
    CONSTRAINT membership_proposal_dedupe_uq
        UNIQUE (universe_id, raw_identifier, change, effective_date)
);

CREATE INDEX idx_membership_proposal_pending
    ON membership_proposal (universe_id, status) WHERE status = 'pending';

CREATE TRIGGER membership_proposal_set_updated_at
    BEFORE UPDATE ON membership_proposal
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  membership_proposal        IS 'Two-stage staging for monitor-discovered membership changes (Story U3.2, AR-9). Mutable; promotes to the append-only membership_event on confirmation/corroboration.';
COMMENT ON COLUMN membership_proposal.status IS 'pending (awaiting persistence/corroboration/operator) | confirmed (appended to the log) | rejected (recorded, not appended).';
COMMENT ON COLUMN membership_proposal.reason IS 'Why gated, e.g. churn_threshold | awaiting_corroboration | awaiting_persistence.';

COMMIT;
