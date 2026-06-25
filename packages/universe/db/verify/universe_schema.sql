-- Verify universe:universe_schema on pg

BEGIN;

SELECT 1/count(*) FROM pg_namespace WHERE nspname = 'universe';
SELECT universe_id, name, kind FROM universe.universe WHERE false;
SELECT event_id, universe_id, change, effective_date FROM universe.membership_event WHERE false;
SELECT universe_id, raw_identifier, composite_figi, resolution_status
  FROM universe.universe_member_resolution WHERE false;
SELECT universe_id, composite_figi, valid_from, valid_to FROM universe.universe_membership WHERE false;
SELECT proposal_id, universe_id, status FROM universe.membership_proposal WHERE false;
SELECT monitor_run_id, universe_id, status FROM universe.universe_monitor_log WHERE false;
SELECT check_id, universe_id, divergence, alarm FROM universe.universe_accuracy_check WHERE false;

ROLLBACK;
