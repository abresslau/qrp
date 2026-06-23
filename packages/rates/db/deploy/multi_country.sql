-- Deploy rates:multi_country to pg
-- requires: curve_point

-- Generalise the curve store from UK-only to ALL FX-matrix countries (euro area broken down BY
-- country). Adds a `country` (ISO-3166 alpha-2 sovereign issuer) dimension to the PK + a `currency`
-- attribute, broadens the rate_type set (add par/yield — most CBs publish yields/par, not spot), and
-- widens the value band for EM / deep history. Existing UK rows backfill to country='GB'/currency='GBP'.
BEGIN;

ALTER TABLE rates.curve_point ADD COLUMN IF NOT EXISTS country  CHAR(2);
ALTER TABLE rates.curve_point ADD COLUMN IF NOT EXISTS currency CHAR(3);
UPDATE rates.curve_point SET country = 'GB'  WHERE country  IS NULL;
UPDATE rates.curve_point SET currency = 'GBP' WHERE currency IS NULL;
ALTER TABLE rates.curve_point ALTER COLUMN country SET NOT NULL;

-- re-key on country
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_pk;
ALTER TABLE rates.curve_point
    ADD CONSTRAINT curve_point_pk PRIMARY KEY (country, curve_set, basis, rate_type, tenor, as_of_date);

-- curve_set is now free per country (e.g. 'govt', plus the UK's 'glc'/'ois'); drop the UK-only CHECK.
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_set_chk;
-- most central banks publish par / market yields, not Svensson spot — broaden rate_type.
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_rate_type_chk;
ALTER TABLE rates.curve_point
    ADD CONSTRAINT curve_point_rate_type_chk CHECK (rate_type IN ('spot', 'forward', 'par', 'yield'));
-- widen the plausible band (EM + deep history run higher than UK gilts).
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_value_chk;
ALTER TABLE rates.curve_point ADD CONSTRAINT curve_point_value_chk CHECK (value > -10 AND value < 60);
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_first_chk;
ALTER TABLE rates.curve_point ADD CONSTRAINT curve_point_first_chk CHECK (first_value > -10 AND first_value < 60);

-- Two complementary covering indexes (the UK's glc/nominal/spot alone is >1M rows):
--  * as_of_date before tenor — for "the whole curve on a date" (curve / movie reads).
--  * tenor before as_of_date — for "one tenor's full history" (spread series / compare-tenor).
-- The second is load-bearing: a spread leg filters `tenor = ANY(...)` across all dates, and without
-- a tenor-leading index that is a multi-million-row seqscan (≈3s/leg → 16s/spreads page).
CREATE INDEX IF NOT EXISTS idx_curve_point_country_series
    ON rates.curve_point (country, curve_set, basis, rate_type, as_of_date, tenor);
CREATE INDEX IF NOT EXISTS idx_curve_point_series_tenor
    ON rates.curve_point (country, curve_set, basis, rate_type, tenor, as_of_date);

-- review queue mirrors the key
ALTER TABLE rates.curve_point_review ADD COLUMN IF NOT EXISTS country  CHAR(2);
ALTER TABLE rates.curve_point_review ADD COLUMN IF NOT EXISTS currency CHAR(3);
UPDATE rates.curve_point_review SET country = 'GB' WHERE country IS NULL;
ALTER TABLE rates.curve_point_review ALTER COLUMN country SET NOT NULL;
ALTER TABLE rates.curve_point_review DROP CONSTRAINT IF EXISTS curve_point_review_pk;
ALTER TABLE rates.curve_point_review
    ADD CONSTRAINT curve_point_review_pk PRIMARY KEY (country, curve_set, basis, rate_type, tenor, as_of_date);

COMMENT ON COLUMN rates.curve_point.country IS 'ISO-3166 alpha-2 sovereign issuer (EUR fans out: DE/FR/IT/ES/…).';
COMMENT ON COLUMN rates.curve_point.currency IS 'Currency of the issuer (grouping/labels): DE→EUR, GB→GBP, …';

COMMIT;
