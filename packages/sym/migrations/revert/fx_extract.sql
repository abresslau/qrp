-- Revert sym:fx_extract from pg
-- Recreates the fx objects in the sym database (schema only; the data lives in the fx database).
-- Faithful to the original sym migrations fx_rate / fx_rate_review (+ superseded) / fx_source_rank
-- / fx_views (+ precedence), in their final form.

BEGIN;

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
CREATE INDEX idx_fx_rate_quote_date ON fx_rate (quote_currency, as_of_date);

CREATE TABLE fx_rate_review (
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
CREATE UNIQUE INDEX uq_fx_rate_review_open
    ON fx_rate_review (quote_currency, as_of_date, source) WHERE NOT reviewed;

CREATE FUNCTION fx_source_rank(source TEXT) RETURNS INT
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE source
        WHEN 'frankfurter' THEN 10
        WHEN 'ecb'         THEN 20
        WHEN 'fawazahmed0' THEN 30
        ELSE 100
    END
$$;

CREATE VIEW v_fx AS
    SELECT base_currency, quote_currency, as_of_date, rate, source FROM fx_rate
    UNION ALL
    SELECT quote_currency, base_currency, as_of_date, 1 / rate, source FROM fx_rate;

CREATE VIEW v_fx_daily AS
WITH bounds AS (
    SELECT quote_currency, min(as_of_date) AS first_date, max(as_of_date) AS last_date
      FROM fx_rate WHERE base_currency = 'USD'
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
        FROM fx_rate r
       WHERE r.base_currency = 'USD' AND r.quote_currency = w.quote_currency
         AND r.as_of_date <= w.weekday_date
       ORDER BY r.as_of_date DESC, fx_source_rank(r.source) ASC
       LIMIT 1
  ) lo;

COMMIT;
