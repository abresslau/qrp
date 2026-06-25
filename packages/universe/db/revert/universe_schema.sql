-- Revert universe:universe_schema from pg

BEGIN;

DROP TABLE IF EXISTS universe.universe_accuracy_check;
DROP TABLE IF EXISTS universe.universe_monitor_log;
DROP TABLE IF EXISTS universe.membership_proposal;
DROP TABLE IF EXISTS universe.universe_membership;
DROP TABLE IF EXISTS universe.universe_member_resolution;
DROP TABLE IF EXISTS universe.membership_event;
DROP TABLE IF EXISTS universe.universe;
DROP FUNCTION IF EXISTS universe.set_updated_at();
DROP SCHEMA IF EXISTS universe;

COMMIT;
