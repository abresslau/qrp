-- Deploy sym:security_names to pg
-- requires: securities

-- Effective-dated company names. Name is a drifting vendor label (Facebook ->
-- Meta), so it is stored SCD-shaped against the immutable CompositeFIGI -- a
-- rename adds a row, the FIGI is unchanged. Current-only data today (from
-- OpenFIGI), same rationale as gics_scd. valid_to NULL = currently effective.
BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE security_names (
    name_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    composite_figi  CHAR(12)    NOT NULL,
    name            TEXT        NOT NULL,
    source          TEXT        NOT NULL DEFAULT 'openfigi',
    valid_from      DATE        NOT NULL,
    valid_to        DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT security_names_figi_chk     CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT security_names_validity_chk CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT security_names_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    -- One name per security per instant; guarantees a point-in-time name lookup
    -- returns exactly one row.
    CONSTRAINT security_names_no_overlap EXCLUDE USING gist (
        composite_figi WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

CREATE INDEX idx_security_names_composite_figi ON security_names (composite_figi);
CREATE INDEX idx_security_names_name           ON security_names (name);

CREATE TRIGGER security_names_set_updated_at
    BEFORE UPDATE ON security_names FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  security_names          IS 'Effective-dated company names per CompositeFIGI (SCD). A rename adds a row; the FIGI is stable. Current-only data (OpenFIGI).';
COMMENT ON COLUMN security_names.valid_to IS 'Exclusive upper bound of validity; NULL = currently effective.';

COMMIT;
