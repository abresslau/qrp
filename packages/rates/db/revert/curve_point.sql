-- Revert rates:curve_point from pg

BEGIN;

DROP TABLE IF EXISTS rates.curve_point_review;
DROP TABLE IF EXISTS rates.curve_point;

COMMIT;
