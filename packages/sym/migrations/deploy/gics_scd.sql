-- Deploy sym:gics_scd to pg
-- requires: securities

BEGIN;

-- btree_gist is also pulled in by security_symbology; CREATE ... IF NOT EXISTS
-- is idempotent regardless of deploy order.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- GICS classification in slowly-changing-dimension shape (FR-4, D4). The SCD
-- shape is the deliberate one-way door: a flat table would lose point-in-time
-- sector history forever. Data is current-only and GICS-*approximated* (the
-- financedatabase source supplies the top three level labels; sub-industry and
-- the numeric GICS codes are not available from it, so those columns exist for
-- future point-in-time / coded data but stay NULL today). valid_to NULL =
-- currently effective. Effective-dated, not bitemporal.
CREATE TABLE gics_scd (
    gics_id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    composite_figi       CHAR(12)    NOT NULL,
    sector_code          TEXT,
    sector_name          TEXT,
    industry_group_code  TEXT,
    industry_group_name  TEXT,
    industry_code        TEXT,
    industry_name        TEXT,
    sub_industry_code    TEXT,
    sub_industry_name    TEXT,
    source               TEXT        NOT NULL DEFAULT 'financedatabase',
    valid_from           DATE        NOT NULL,
    valid_to             DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gics_scd_figi_chk      CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT gics_scd_validity_chk  CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT gics_scd_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    -- A security may hold at most one classification over any instant: its
    -- effective-dated rows may not overlap in time. Guarantees a point-in-time
    -- classification lookup returns exactly one row.
    CONSTRAINT gics_scd_no_overlap EXCLUDE USING gist (
        composite_figi WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

-- All four levels queryable and indexed (Story 1.8 AC).
CREATE INDEX idx_gics_scd_composite_figi  ON gics_scd (composite_figi);
CREATE INDEX idx_gics_scd_sector          ON gics_scd (sector_name);
CREATE INDEX idx_gics_scd_industry_group  ON gics_scd (industry_group_name);
CREATE INDEX idx_gics_scd_industry        ON gics_scd (industry_name);
CREATE INDEX idx_gics_scd_sub_industry    ON gics_scd (sub_industry_name);

CREATE TRIGGER gics_scd_set_updated_at
    BEFORE UPDATE ON gics_scd
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  gics_scd                  IS 'Effective-dated GICS-approximated classification per CompositeFIGI (SCD shape, current-only data).';
COMMENT ON COLUMN gics_scd.sub_industry_name IS 'GICS level 4; not supplied by the financedatabase source — NULL until a coded GICS feed is licensed.';
COMMENT ON COLUMN gics_scd.sector_code       IS 'Numeric GICS code; NULL until a coded GICS feed is licensed (financedatabase carries labels only).';
COMMENT ON COLUMN gics_scd.valid_to          IS 'Exclusive upper bound of validity; NULL = currently effective.';

COMMIT;
