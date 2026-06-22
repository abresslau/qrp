-- Verify rates:curve_point on pg

BEGIN;

SELECT curve_set, basis, rate_type, tenor, as_of_date, value, first_value,
       source, first_published_at, last_changed_at
  FROM rates.curve_point WHERE FALSE;

SELECT curve_set, basis, rate_type, tenor, as_of_date, value, prev_value, reason, source, flagged_at
  FROM rates.curve_point_review WHERE FALSE;

ROLLBACK;
