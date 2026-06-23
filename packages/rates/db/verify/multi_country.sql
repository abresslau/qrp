-- Verify rates:multi_country on pg
BEGIN;

SELECT country, currency FROM rates.curve_point WHERE FALSE;
SELECT country, currency FROM rates.curve_point_review WHERE FALSE;
-- the PK must include country
SELECT 1 / (CASE WHEN EXISTS (
    SELECT 1 FROM pg_index i
      JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
     WHERE i.indrelid = 'rates.curve_point'::regclass AND i.indisprimary AND a.attname = 'country'
) THEN 1 ELSE 0 END);

ROLLBACK;
