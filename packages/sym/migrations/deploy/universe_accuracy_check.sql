-- Deploy sym:universe_accuracy_check to pg
-- requires: universe

BEGIN;

-- Membership accuracy-gate results (Story U3.3, FR14, SM-6-style for membership).
-- Each row records a cross-check of a universe's maintained membership against an
-- INDEPENDENT second source (not a derivative of the same upstream): the symmetric
-- difference and a divergence ratio, with an alarm when divergence exceeds the
-- (proxy-aware) threshold. Catches a *wrong* universe, not merely a stale one.
-- Append-only check record; no updated_at.
CREATE TABLE universe_accuracy_check (
    check_id          BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    universe_id       TEXT        NOT NULL,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of             DATE        NOT NULL,
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
    CONSTRAINT universe_accuracy_check_universe_fk FOREIGN KEY (universe_id)
        REFERENCES universe (universe_id),
    CONSTRAINT universe_accuracy_check_counts_chk
        CHECK (maintained_count >= 0 AND reference_count >= 0 AND missing >= 0 AND extra >= 0)
);

CREATE INDEX idx_universe_accuracy_check_universe
    ON universe_accuracy_check (universe_id, checked_at DESC);

COMMENT ON TABLE  universe_accuracy_check         IS 'Membership accuracy-gate results (Story U3.3, FR14). Cross-check vs an independent source; alarms when a universe is wrong, not just stale.';
COMMENT ON COLUMN universe_accuracy_check.missing IS 'Members in the reference set but not the maintained set.';
COMMENT ON COLUMN universe_accuracy_check.extra   IS 'Members in the maintained set but not the reference set.';
COMMENT ON COLUMN universe_accuracy_check.divergence IS 'Symmetric-difference ratio |A △ B| / |A ∪ B| (Jaccard distance).';

COMMIT;
