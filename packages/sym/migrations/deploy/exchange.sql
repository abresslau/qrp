-- Deploy sym:exchange to pg
-- requires: currency

BEGIN;

-- MIC-keyed exchange reference (FR-12), distinct from the trading calendar.
-- timezone is an IANA name used for exchange-local business-day math; every
-- row's currency_code resolves against the currency reference.
CREATE TABLE exchange (
    mic            CHAR(4)     PRIMARY KEY,
    name           TEXT        NOT NULL,
    country        TEXT        NOT NULL,
    country_iso    CHAR(2)     NOT NULL,
    timezone       TEXT        NOT NULL,
    currency_code  CHAR(3)     NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT exchange_mic_format_chk     CHECK (mic ~ '^[A-Z0-9]{4}$'),
    CONSTRAINT exchange_country_iso_chk    CHECK (country_iso ~ '^[A-Z]{2}$'),
    CONSTRAINT exchange_currency_fk        FOREIGN KEY (currency_code) REFERENCES currency (code)
);

CREATE INDEX idx_exchange_currency_code ON exchange (currency_code);

CREATE TRIGGER exchange_set_updated_at
    BEFORE UPDATE ON exchange
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
