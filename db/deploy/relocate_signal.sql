-- Deploy qrp:relocate_signal to pg
-- requires: signal

BEGIN;

-- signal relocated to its OWN database + Sqitch project `signal` (db/signal/). Data copied
-- there first; this drops the now-redundant schema from the sym database. QRP's signal read
-- API uses signal_dsn(); the signal COMPUTE reads sym read-only over a separate connection.
-- (As with relocate_macro: a bare `sqitch verify` of the qrp project will flag the original
-- `signal` change afterwards — expected under the incremental migration; deploy --verify
-- replay still passes.)
DROP SCHEMA IF EXISTS signal CASCADE;

COMMIT;
