-- Deploy qrp:relocate_optimiser to pg
-- requires: optimiser

BEGIN;

-- optimiser relocated to its own database + Sqitch project `optimiser` (db/optimiser/). Data
-- copied there first; drop the redundant schema from the sym database.
DROP SCHEMA IF EXISTS optimiser CASCADE;

COMMIT;
