-- Verify sym:universe_monitor_log on pg

SELECT monitor_run_id, universe_id, run_at, source, joiners, leavers, proposed,
       applied, status, detail, created_at
  FROM universe_monitor_log
 WHERE FALSE;
