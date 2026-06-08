-- Deploy sym:rename_symbology_pk to pg
-- requires: security_symbology

-- Shorten the security_symbology surrogate primary key symbology_id -> sym_id.
-- A column rename is a metadata-only operation (no table rewrite, no data loss);
-- it keeps the identity sequence, PK, and all referencing constraints intact.
BEGIN;

ALTER TABLE security_symbology RENAME COLUMN symbology_id TO sym_id;

COMMIT;
