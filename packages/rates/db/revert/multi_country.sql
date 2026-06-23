-- Revert rates:multi_country from pg
BEGIN;

DROP INDEX IF EXISTS rates.idx_curve_point_series_tenor;
DROP INDEX IF EXISTS rates.idx_curve_point_country_series;

DELETE FROM rates.curve_point WHERE country <> 'GB';
DELETE FROM rates.curve_point_review WHERE country <> 'GB';

ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_pk;
ALTER TABLE rates.curve_point
    ADD CONSTRAINT curve_point_pk PRIMARY KEY (curve_set, basis, rate_type, tenor, as_of_date);
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_rate_type_chk;
ALTER TABLE rates.curve_point
    ADD CONSTRAINT curve_point_rate_type_chk CHECK (rate_type IN ('spot', 'forward'));
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_value_chk;
ALTER TABLE rates.curve_point ADD CONSTRAINT curve_point_value_chk CHECK (value > -10 AND value < 30);
ALTER TABLE rates.curve_point DROP CONSTRAINT IF EXISTS curve_point_first_chk;
ALTER TABLE rates.curve_point ADD CONSTRAINT curve_point_first_chk CHECK (first_value > -10 AND first_value < 30);
ALTER TABLE rates.curve_point
    ADD CONSTRAINT curve_point_set_chk CHECK (curve_set IN ('glc', 'ois', 'blc'));

ALTER TABLE rates.curve_point_review DROP CONSTRAINT IF EXISTS curve_point_review_pk;
ALTER TABLE rates.curve_point_review
    ADD CONSTRAINT curve_point_review_pk PRIMARY KEY (curve_set, basis, rate_type, tenor, as_of_date);

ALTER TABLE rates.curve_point DROP COLUMN IF EXISTS country;
ALTER TABLE rates.curve_point DROP COLUMN IF EXISTS currency;
ALTER TABLE rates.curve_point_review DROP COLUMN IF EXISTS country;
ALTER TABLE rates.curve_point_review DROP COLUMN IF EXISTS currency;

COMMIT;
