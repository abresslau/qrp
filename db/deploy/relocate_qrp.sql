-- Deploy qrp:relocate_qrp to pg
-- requires: jobs

BEGIN;

-- The qrp schema (portfolios + job ledger) has been relocated to its own `qrp` database +
-- Sqitch project `qrp_core` (db/qrp_core/). Data copied there first; drop the redundant schema
-- from the sym database. This is the final carve — after it, the sym database holds none of the
-- QRP module schemas (the legacy `qrp` project here is now purely relocation history).
DROP SCHEMA IF EXISTS qrp CASCADE;

COMMIT;
