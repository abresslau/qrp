-- Deploy sym:universe_member_resolution to pg
-- requires: universe

BEGIN;

-- Frozen member -> CompositeFIGI resolutions (Story U1.3). A member's identity is
-- resolved once (ISIN-first via OpenFIGI) and frozen by the PK -- a later ticker
-- recycle can't re-point it. Unresolvable members are RETAINED here with
-- status='unresolved' (never dropped -- survivorship). No FK on composite_figi:
-- a resolved FIGI need not yet exist in `securities` (ingestion is U4); identity
-- is recorded regardless (retain-and-flag). Frozen => no updated_at.
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

COMMENT ON TABLE  universe_member_resolution                   IS 'Frozen member->CompositeFIGI resolutions (Story U1.3). Resolved once and immutable; unresolved members retained (survivorship). composite_figi has no securities FK (ingestion is U4).';
COMMENT ON COLUMN universe_member_resolution.resolution_status IS 'resolved | unresolved | unpriced (unpriced set by ingestion when resolved but no prices yet).';

COMMIT;
