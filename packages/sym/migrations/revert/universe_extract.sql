-- Revert sym:universe_extract from pg
-- Recreates the 7 universe tables in the sym database (schema only; data lives in the universe DB)
-- and re-adds the two soft-reference FKs from universe_benchmark / universe_member_completeness.

BEGIN;

-- Self-contained: universe_membership's no-overlap EXCLUDE needs btree_gist for the
-- `universe_id WITH =` / `composite_figi WITH =` equality operators. The extract deploy
-- leaves the extension in place, but don't depend on that — re-assert it here.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE universe (
    universe_id     TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    kind            TEXT        NOT NULL,
    config          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    pit_valid_from  DATE,
    source_pref     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_id_format_chk CHECK (universe_id ~ '^[a-z0-9][a-z0-9_-]*$'),
    CONSTRAINT universe_kind_chk      CHECK (kind IN ('custom_list', 'index', 'criteria'))
);
CREATE TRIGGER universe_set_updated_at
    BEFORE UPDATE ON universe FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
    CONSTRAINT membership_event_dedupe_uq    UNIQUE (universe_id, raw_identifier, change, effective_date)
);
CREATE INDEX idx_membership_event_universe ON membership_event (universe_id, effective_date, event_id);

CREATE TABLE universe_member_resolution (
    universe_id       TEXT        NOT NULL,
    raw_identifier    TEXT        NOT NULL,
    composite_figi    CHAR(12),
    share_class_figi  CHAR(12),
    resolution_status TEXT        NOT NULL,
    detail            TEXT,
    resolved_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_member_resolution_pk          PRIMARY KEY (universe_id, raw_identifier),
    CONSTRAINT universe_member_resolution_universe_fk FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT universe_member_resolution_status_chk  CHECK (resolution_status IN ('resolved', 'unresolved', 'unpriced')),
    CONSTRAINT universe_member_resolution_figi_chk    CHECK (composite_figi IS NULL OR composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT universe_member_resolution_resolved_chk CHECK (resolution_status <> 'resolved' OR composite_figi IS NOT NULL)
);
CREATE INDEX idx_universe_member_resolution_figi ON universe_member_resolution (composite_figi);

CREATE TABLE universe_membership (
    universe_id     TEXT        NOT NULL,
    composite_figi  CHAR(12)    NOT NULL,
    raw_identifier  TEXT,
    valid_from      DATE        NOT NULL,
    valid_to        DATE,
    source          TEXT,
    CONSTRAINT universe_membership_universe_fk  FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT universe_membership_figi_chk     CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT universe_membership_validity_chk CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT universe_membership_no_overlap EXCLUDE USING gist (
        universe_id WITH =, composite_figi WITH =, daterange(valid_from, valid_to, '[)') WITH &&)
);
CREATE INDEX idx_universe_membership_figi ON universe_membership (composite_figi);
CREATE INDEX idx_universe_membership_asof ON universe_membership (universe_id, valid_from, valid_to);

CREATE TABLE membership_proposal (
    proposal_id              BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id              TEXT        NOT NULL,
    raw_identifier           TEXT        NOT NULL,
    change                   TEXT        NOT NULL,
    effective_date           DATE        NOT NULL,
    effective_date_precision TEXT        NOT NULL DEFAULT 'poll_bounded',
    source                   TEXT        NOT NULL,
    first_seen_date          DATE        NOT NULL,
    last_seen_date           DATE        NOT NULL,
    seen_count               INTEGER     NOT NULL DEFAULT 1,
    corroborating_sources    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    status                   TEXT        NOT NULL DEFAULT 'pending',
    reason                   TEXT,
    decided_at               TIMESTAMPTZ,
    decided_by               TEXT,
    detail                   TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT membership_proposal_universe_fk FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT membership_proposal_change_chk CHECK (change IN ('join', 'leave', 'correct')),
    CONSTRAINT membership_proposal_status_chk CHECK (status IN ('pending', 'confirmed', 'rejected')),
    CONSTRAINT membership_proposal_precision_chk CHECK (effective_date_precision IN ('exact', 'poll_bounded')),
    CONSTRAINT membership_proposal_seen_chk CHECK (seen_count >= 1),
    CONSTRAINT membership_proposal_dedupe_uq UNIQUE (universe_id, raw_identifier, change, effective_date)
);
CREATE INDEX idx_membership_proposal_pending ON membership_proposal (universe_id, status) WHERE status = 'pending';
CREATE TRIGGER membership_proposal_set_updated_at
    BEFORE UPDATE ON membership_proposal FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE universe_monitor_log (
    monitor_run_id BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id    TEXT        NOT NULL,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source         TEXT,
    joiners        INTEGER     NOT NULL DEFAULT 0,
    leavers        INTEGER     NOT NULL DEFAULT 0,
    proposed       INTEGER     NOT NULL DEFAULT 0,
    applied        INTEGER     NOT NULL DEFAULT 0,
    status         TEXT        NOT NULL,
    detail         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_monitor_log_universe_fk FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT universe_monitor_log_status_chk CHECK (status IN ('success', 'gated', 'error')),
    CONSTRAINT universe_monitor_log_counts_chk CHECK (joiners >= 0 AND leavers >= 0 AND proposed >= 0 AND applied >= 0)
);
CREATE INDEX idx_universe_monitor_log_universe ON universe_monitor_log (universe_id, run_at DESC);

CREATE TABLE universe_accuracy_check (
    check_id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id       TEXT        NOT NULL,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of_date        DATE        NOT NULL,
    reference_source  TEXT        NOT NULL,
    maintained_count  INTEGER     NOT NULL,
    reference_count   INTEGER     NOT NULL,
    missing           INTEGER     NOT NULL,
    extra             INTEGER     NOT NULL,
    divergence        NUMERIC     NOT NULL,
    threshold         NUMERIC     NOT NULL,
    alarm             BOOLEAN     NOT NULL,
    detail            JSONB,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_accuracy_check_universe_fk FOREIGN KEY (universe_id) REFERENCES universe (universe_id),
    CONSTRAINT universe_accuracy_check_counts_chk CHECK (maintained_count >= 0 AND reference_count >= 0 AND missing >= 0 AND extra >= 0)
);
CREATE INDEX idx_universe_accuracy_check_universe ON universe_accuracy_check (universe_id, checked_at DESC);

ALTER TABLE universe_benchmark ADD CONSTRAINT universe_benchmark_universe_fk
    FOREIGN KEY (universe_id) REFERENCES universe (universe_id);
ALTER TABLE universe_member_completeness ADD CONSTRAINT universe_member_completeness_universe_fk
    FOREIGN KEY (universe_id) REFERENCES universe (universe_id);

COMMIT;
