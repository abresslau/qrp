-- Verify sym:security_names on pg

BEGIN;

SELECT name_id, composite_figi, name, source, valid_from, valid_to, created_at, updated_at
  FROM security_names WHERE FALSE;

ROLLBACK;
