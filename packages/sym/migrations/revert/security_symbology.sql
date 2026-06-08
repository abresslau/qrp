-- Revert sym:security_symbology from pg

BEGIN;

DROP TABLE IF EXISTS security_symbology;
DROP EXTENSION IF EXISTS btree_gist;

COMMIT;
