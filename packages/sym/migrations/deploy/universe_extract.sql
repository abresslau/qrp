-- Deploy sym:universe_extract to pg
-- requires: universe_accuracy_check

BEGIN;

-- The universe/membership subsystem has been extracted into the `universe` peer package + its own
-- database (DB-per-package topology). The 7 membership tables' rows were copied there and every
-- consumer (sym cli/eod/ingest/validate, backtest, signals, the API explorer/coverage, the data
-- monitor, indices links, fundamentals) now reads the universe DB. Drop the now-orphaned tables
-- from the sym database. `universe_benchmark` + the sym-side `universe_member_completeness`
-- validate-output table STAY in sym — their `universe_id` becomes a SOFT reference (a cross-DB FK
-- to the universe DB is impossible), so drop those FKs first. Revert recreates the schema (empty) —
-- the data lives in the universe database.

ALTER TABLE universe_benchmark DROP CONSTRAINT universe_benchmark_universe_fk;
ALTER TABLE universe_member_completeness DROP CONSTRAINT universe_member_completeness_universe_fk;

DROP TABLE membership_event;
DROP TABLE universe_member_resolution;
DROP TABLE universe_membership;
DROP TABLE membership_proposal;
DROP TABLE universe_monitor_log;
DROP TABLE universe_accuracy_check;
DROP TABLE universe;

COMMIT;
