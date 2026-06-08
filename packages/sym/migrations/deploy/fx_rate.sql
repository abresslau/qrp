-- Deploy sym:fx_rate to pg
-- requires: currency

BEGIN;

-- Observed FX rates in a USD-centered star: one rate per (base, quote, as_of_date, source).
-- USD-base is preferred; inverses and crosses are DERIVED (v_fx / v_fx_daily / convert()),
-- never stored. Canonical direction is INLINED (a CHECK cannot call a rank-lookup function):
-- USD is always the base (rank 0); any non-USD cross sorts alphabetically (base < quote).
-- This makes a redundant inverse, a both-direction cross, a USD-as-quote row, and a self-pair
-- all impossible by construction. A future non-USD pivot would be a deliberate migration.
-- Immutable + source-tagged; corrections are out of scope (v1) -- append-only by convention.
CREATE TABLE fx_rate (
    base_currency   CHAR(3)     NOT NULL REFERENCES currency (code),
    quote_currency  CHAR(3)     NOT NULL REFERENCES currency (code),
    as_of_date      DATE        NOT NULL,
    rate            NUMERIC     NOT NULL,
    source          TEXT        NOT NULL,
    inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fx_rate_pk PRIMARY KEY (base_currency, quote_currency, as_of_date, source),
    CONSTRAINT fx_rate_rate_positive CHECK (rate > 0),
    CONSTRAINT fx_rate_canonical_direction CHECK (
        base_currency <> quote_currency
        AND (base_currency = 'USD' OR (quote_currency <> 'USD' AND base_currency < quote_currency))
    )
);

-- Resolver access: a currency's USD series, and all currencies for a date. Stored rows are
-- USD-base, so the currency of interest is quote_currency.
CREATE INDEX idx_fx_rate_quote_date ON fx_rate (quote_currency, as_of_date);

COMMENT ON TABLE fx_rate IS 'Observed FX rates (immutable, source-tagged), USD-centered star. USD-base preferred; inverses/crosses derived (v_fx, v_fx_daily, convert()), never stored. Canonical direction inlined: USD always base, else base<quote. Corrections out of scope (v1) -- append-only by convention.';

COMMIT;
