-- Deploy fx:fx_schema to pg

BEGIN;

-- The `fx` package's own database (NOT sym, NOT the qrp gateway database): USD-centered
-- foreign-exchange rates. Extracted from sym under the DB-per-package topology. Everything
-- lives in the `fx` schema (the rates/commodities/macro house convention). This single
-- migration recreates, in FINAL form, what was six sym migrations (fx_rate, fx_views,
-- fx_source_rank, fx_views_precedence, fx_rate_review, fx_rate_review_superseded) plus the
-- `currency` reference table the FK needs (seeded into this DB — reference data, dup is fine;
-- a cross-DB FK to sym.currency is impossible in Postgres).

CREATE SCHEMA IF NOT EXISTS fx;

-- Shared updated_at trigger (local copy — fx owns its DB; mirrors sym's set_updated_at).
CREATE FUNCTION fx.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ISO-4217 currency reference. Code is the natural PK; the fx_rate FK references it. Seeded
-- in this DB (the rows are copied from sym at migration time / re-seedable from any ISO list).
CREATE TABLE fx.currency (
    code        CHAR(3)     PRIMARY KEY,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT currency_code_format_chk CHECK (code ~ '^[A-Z]{3}$')
);

CREATE TRIGGER currency_set_updated_at
    BEFORE UPDATE ON fx.currency
    FOR EACH ROW EXECUTE FUNCTION fx.set_updated_at();

-- Observed FX rates in a USD-centered star: one rate per (base, quote, as_of_date, source).
-- USD-base is preferred; inverses and crosses are DERIVED (v_fx / v_fx_daily / convert()),
-- never stored. Canonical direction is INLINED (a CHECK cannot call a rank-lookup function):
-- USD is always the base (rank 0); any non-USD cross sorts alphabetically (base < quote).
-- Immutable + source-tagged; corrections are out of scope (v1) -- append-only by convention.
CREATE TABLE fx.fx_rate (
    base_currency   CHAR(3)     NOT NULL REFERENCES fx.currency (code),
    quote_currency  CHAR(3)     NOT NULL REFERENCES fx.currency (code),
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
CREATE INDEX idx_fx_rate_quote_date ON fx.fx_rate (quote_currency, as_of_date);

COMMENT ON TABLE fx.fx_rate IS 'Observed FX rates (immutable, source-tagged), USD-centered star. USD-base preferred; inverses/crosses derived (v_fx, v_fx_daily, convert()), never stored. Canonical direction inlined: USD always base, else base<quote. Corrections out of scope (v1) -- append-only by convention.';

-- Durable FX plausibility rejections (Story S.1). A row here is the operator's review surface;
-- ACCEPTING it inserts the rate into fx.fx_rate (the steward vouches), which un-wedges the band
-- naturally on the next load. resolution allows 'superseded' (folded in from the start here):
-- a later load storing a rate for an open key closes it as moot so a multi-day queue DRAINS.
CREATE TABLE fx.fx_rate_review (
    review_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quote_currency CHAR(3)     NOT NULL,
    as_of_date     DATE        NOT NULL,
    rate           NUMERIC     NOT NULL,
    prior_rate     NUMERIC,
    relative_move  NUMERIC,
    source         TEXT        NOT NULL,
    reason         TEXT        NOT NULL,
    reviewed       BOOLEAN     NOT NULL DEFAULT FALSE,
    resolution     TEXT,
    reviewed_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fx_rate_review_reason_chk
        CHECK (reason IN ('non_positive', 'band_exceeded')),
    CONSTRAINT fx_rate_review_resolution_chk
        CHECK (resolution IS NULL OR resolution IN ('accepted', 'rejected', 'superseded')),
    CONSTRAINT fx_rate_review_reviewed_chk CHECK (reviewed = (resolution IS NOT NULL))
);

-- One OPEN row per rejected observation: daily re-runs refresh, never duplicate.
-- Closing frees the key (a later recurrence re-queues fresh).
CREATE UNIQUE INDEX uq_fx_rate_review_open
    ON fx.fx_rate_review (quote_currency, as_of_date, source) WHERE NOT reviewed;

COMMENT ON TABLE fx.fx_rate_review IS
    'FX plausibility rejections awaiting stewarding (S.1). accept => rate inserted into fx_rate (un-wedges the band); reject => vendor garbage, closed; superseded => a later load stored a rate for this key (queue item moot).';
COMMENT ON COLUMN fx.fx_rate_review.relative_move IS
    'RATIO (not percent): abs(rate/prior - 1); NULL when no prior or rate <= 0.';
COMMENT ON COLUMN fx.fx_rate_review.prior_rate IS
    'The band seed the rejected observation was compared against (NULL on a first observation).';
COMMENT ON COLUMN fx.fx_rate_review.resolution IS
    'accepted (steward vouched; insert attempted) | rejected (vendor garbage) | superseded (a later load stored a rate for this key — queue item moot).';

-- Source trust tier for the canonical read-side pick when two sources hold a rate for the same
-- (pair, as_of_date): lower wins. Mirrors SOURCE_PRECEDENCE in src/fx/source.py.
CREATE FUNCTION fx.fx_source_rank(source TEXT) RETURNS INT
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE source
        WHEN 'frankfurter' THEN 10
        WHEN 'ecb'         THEN 20
        WHEN 'fawazahmed0' THEN 30
        ELSE 100
    END
$$;

COMMENT ON FUNCTION fx.fx_source_rank(TEXT) IS
    'FX source trust tier (lower preferred) for the canonical (pair,date) pick across sources. Mirrors SOURCE_PRECEDENCE in fx.source.';

-- v_fx: both directions as a convenience (observed USD-base rows + their inverse). The
-- USD/USD=1 identity and the as-of/staleness policy live in the Python resolver (single
-- source of truth) -- this view is for ad-hoc DBeaver use, not triangulation.
CREATE VIEW fx.v_fx AS
    SELECT base_currency, quote_currency, as_of_date, rate, source FROM fx.fx_rate
    UNION ALL
    SELECT quote_currency, base_currency, as_of_date, 1 / rate, source FROM fx.fx_rate;

-- v_fx_daily: dense Mon-Fri series per currency, forward-filling each weekday with the last
-- observed rate on/before it (flagged). Multi-source ties broken by fx_source_rank. Computed
-- ON READ -- NO synthetic rows are ever stored. The outage cap is applied by the resolver.
CREATE VIEW fx.v_fx_daily AS
WITH bounds AS (
    SELECT quote_currency, min(as_of_date) AS first_date, max(as_of_date) AS last_date
      FROM fx.fx_rate WHERE base_currency = 'USD'
     GROUP BY quote_currency
), weekdays AS (
    SELECT b.quote_currency, g::date AS weekday_date
      FROM bounds b
      CROSS JOIN generate_series(b.first_date, b.last_date, INTERVAL '1 day') AS g
     WHERE extract(isodow FROM g) < 6
)
SELECT w.quote_currency,
       w.weekday_date,
       lo.as_of_date AS observed_date,
       lo.rate,
       (w.weekday_date <> lo.as_of_date) AS is_filled,
       (w.weekday_date - lo.as_of_date) AS days_stale
  FROM weekdays w
  CROSS JOIN LATERAL (
      SELECT r.rate, r.as_of_date
        FROM fx.fx_rate r
       WHERE r.base_currency = 'USD' AND r.quote_currency = w.quote_currency
         AND r.as_of_date <= w.weekday_date
       ORDER BY r.as_of_date DESC, fx.fx_source_rank(r.source) ASC
       LIMIT 1
  ) lo;

COMMENT ON VIEW fx.v_fx IS 'Bidirectional FX convenience: observed USD-base rows + their inverse. USD=1 identity + as-of/staleness are in the Python resolver, not here.';
COMMENT ON VIEW fx.v_fx_daily IS 'Dense Mon-Fri USD-base series, forward-filled per weekday from the last observed rate (is_filled/days_stale flagged). Multi-source ties broken by fx_source_rank (Frankfurter>ECB>fawazahmed0). Computed on read; no synthetic rows stored. Outage cap applied by the resolver.';

COMMIT;
