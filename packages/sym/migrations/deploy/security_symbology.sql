-- Deploy sym:security_symbology to pg
-- requires: securities

BEGIN;

-- Needed for the temporal-uniqueness EXCLUDE constraint below (equality on
-- text/char columns combined with range overlap in one GiST index).
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Effective-dated symbology (FR-2, FR-3). Narrow shape: one row per
-- (identifier kind, value) with a validity interval, so ticker/exchange drift
-- is captured as valid-time history rather than overwritten. valid_to NULL =
-- currently effective (open-ended). Effective-dated, not bitemporal.
CREATE TABLE security_symbology (
    symbology_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    composite_figi  CHAR(12)    NOT NULL,
    symbol_type     TEXT        NOT NULL,
    symbol_value    TEXT        NOT NULL,
    mic             CHAR(4),
    country_iso     CHAR(2),
    valid_from      DATE        NOT NULL,
    valid_to        DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT security_symbology_figi_chk        CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT security_symbology_type_chk        CHECK (symbol_type IN ('ticker', 'isin', 'cusip', 'sedol', 'local_code')),
    CONSTRAINT security_symbology_country_iso_chk CHECK (country_iso IS NULL OR country_iso ~ '^[A-Z]{2}$'),
    CONSTRAINT security_symbology_validity_chk    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT security_symbology_securities_fk   FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    CONSTRAINT security_symbology_exchange_fk     FOREIGN KEY (mic) REFERENCES exchange (mic),
    -- The same identifier (type + value, scoped to MIC for exchange-local
    -- symbols) may not resolve to two rows over overlapping time. Guarantees an
    -- identifier lookup on any effective date returns exactly one CompositeFIGI.
    CONSTRAINT security_symbology_no_overlap EXCLUDE USING gist (
        symbol_type            WITH =,
        symbol_value           WITH =,
        coalesce(mic::text, '') WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

CREATE INDEX idx_security_symbology_composite_figi ON security_symbology (composite_figi);
CREATE INDEX idx_security_symbology_lookup         ON security_symbology (symbol_type, symbol_value);
CREATE INDEX idx_security_symbology_mic            ON security_symbology (mic);

CREATE TRIGGER security_symbology_set_updated_at
    BEFORE UPDATE ON security_symbology
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  security_symbology              IS 'Effective-dated identifiers (ticker/ISIN/CUSIP/SEDOL/local) resolving to a CompositeFIGI.';
COMMENT ON COLUMN security_symbology.symbol_type  IS 'Identifier kind: ticker | isin | cusip | sedol | local_code.';
COMMENT ON COLUMN security_symbology.mic          IS 'Listing exchange for exchange-scoped symbols (ticker/local_code); NULL for global ids (ISIN/CUSIP/SEDOL).';
COMMENT ON COLUMN security_symbology.valid_to     IS 'Exclusive upper bound of validity; NULL = currently effective.';

COMMIT;
