-- Deploy sym:currency to pg
-- requires: updated_at_trigger

BEGIN;

-- ISO-4217 currency reference (FR-13). Code is the natural PK; explicit on
-- every monetary row downstream (no implicit USD).
CREATE TABLE currency (
    code        CHAR(3)     PRIMARY KEY,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT currency_code_format_chk CHECK (code ~ '^[A-Z]{3}$')
);

CREATE TRIGGER currency_set_updated_at
    BEFORE UPDATE ON currency
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
