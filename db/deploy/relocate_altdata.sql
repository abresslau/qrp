-- Deploy qrp:relocate_altdata to pg
-- requires: altdata

BEGIN;

-- altdata relocated to its own database + Sqitch project `altdata` (db/altdata/). Data copied
-- there first; drop the redundant schema from the sym database.
DROP SCHEMA IF EXISTS altdata CASCADE;

COMMIT;
