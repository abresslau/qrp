-- Revert sym:rename_symbology_pk from pg

BEGIN;

ALTER TABLE security_symbology RENAME COLUMN sym_id TO symbology_id;

COMMIT;
