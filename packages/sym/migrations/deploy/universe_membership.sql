-- Deploy sym:universe_membership to pg
-- requires: universe_member_resolution

BEGIN;

-- Needed for the no-overlap EXCLUDE (equality on text/char + range overlap in
-- one GiST index). Idempotent; already created by security_symbology.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Point-in-time membership (Story U1.4) -- a *projection* of membership_event
-- (the truth), keyed at the CompositeFIGI level so a mid-membership ticker
-- rename stays one continuous interval. valid_to NULL = currently a member.
-- Rebuilt wholesale from the full ordered log, so no updated_at.
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
    -- A FIGI may not be a member of the same universe over two overlapping
    -- intervals: an as-of query returns exactly one membership state per date.
    CONSTRAINT universe_membership_no_overlap EXCLUDE USING gist (
        universe_id    WITH =,
        composite_figi WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

CREATE INDEX idx_universe_membership_figi ON universe_membership (composite_figi);
CREATE INDEX idx_universe_membership_asof ON universe_membership (universe_id, valid_from, valid_to);

COMMENT ON TABLE  universe_membership            IS 'Point-in-time membership (Story U1.4): a projection of membership_event at the CompositeFIGI level. Rebuilt from the full ordered log; the EXCLUDE guarantees no overlapping intervals per (universe, figi).';
COMMENT ON COLUMN universe_membership.valid_to   IS 'Exclusive upper bound; NULL = currently a member.';
COMMENT ON COLUMN universe_membership.raw_identifier IS 'The identifier that opened the interval (informational; a FIGI may span several over a rename).';

COMMIT;
