-- Deploy qrp:relocate_macro to pg
-- requires: macro

BEGIN;

-- macro has been relocated to its OWN database + Sqitch project `macro` (db/macro/), under the
-- DB-per-package + DuckDB-federation topology (supersedes AR-Q4). Its data was copied there
-- first; this drops the now-redundant schema from the sym database. QRP's macro module reads
-- the `macro` database via macro_dsn().
--
-- Note: after this, a bare `sqitch verify` of the `qrp` project will flag the original `macro`
-- change's verify (it selects from macro.series, intentionally gone). That is expected under
-- the incremental migration; `deploy --verify` replay still passes (macro is created, verified,
-- then dropped+verified-absent in order).
DROP SCHEMA IF EXISTS macro CASCADE;

COMMIT;
