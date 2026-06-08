-- Deploy sym:instrument to pg
-- requires: updated_at_trigger

BEGIN;

-- Universal internal instrument identity (Benchmark/sym_id epic, B1). `sym_id` is
-- a stable internal surrogate spanning ALL instrument kinds (equity, index, and
-- future FX/rates/etc.) — the canonical spine going forward. External vendor ids
-- (CompositeFIGI, Yahoo symbol, MSCI code, ISIN, FIGI) hang off it in
-- instrument_xref, so identity never depends on any one vendor (e.g. MSCI indexes
-- have no FIGI/Yahoo symbol). This is ADDITIVE: existing equity/price/returns/
-- universe tables keep composite_figi; each gets a 1:1 instrument row mapped via an
-- xref (backfilled in code). composite_figi is now just one external id among many.
CREATE TABLE instrument (
    sym_id        BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT        NOT NULL,
    name          TEXT,
    currency_code CHAR(3),
    status        TEXT        NOT NULL DEFAULT 'active',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT instrument_kind_chk   CHECK (kind IN ('equity', 'index')),
    CONSTRAINT instrument_status_chk CHECK (status IN ('active', 'delisted', 'suspended'))
);

CREATE TRIGGER instrument_set_updated_at
    BEFORE UPDATE ON instrument
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Open-ended external identifiers. UNIQUE (source, value) guarantees a given
-- vendor id resolves to exactly one instrument (identity integrity).
CREATE TABLE instrument_xref (
    sym_id     BIGINT      NOT NULL,
    source     TEXT        NOT NULL,
    value      TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT instrument_xref_pk        PRIMARY KEY (sym_id, source, value),
    CONSTRAINT instrument_xref_uq        UNIQUE (source, value),
    CONSTRAINT instrument_xref_sym_fk    FOREIGN KEY (sym_id) REFERENCES instrument (sym_id)
);

CREATE INDEX idx_instrument_xref_lookup ON instrument_xref (source, value);

COMMENT ON TABLE  instrument        IS 'Universal internal instrument identity (B1). sym_id = stable internal surrogate across all kinds; vendor ids live in instrument_xref. Additive over the composite_figi-keyed equity tables.';
COMMENT ON COLUMN instrument.kind   IS 'equity | index (extensible via migration: fx, rate, ...).';
COMMENT ON TABLE  instrument_xref   IS 'External identifiers per instrument (composite_figi | yahoo | msci | isin | figi | ...). UNIQUE(source,value): one vendor id -> one instrument.';

COMMIT;
