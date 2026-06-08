-- Verify sym:validation_logs on pg

SELECT universe_id, composite_figi, has_name, has_symbology, has_gics, has_prices,
       has_fundamentals, is_complete, missing, severity, reason, checked_at
  FROM universe_member_completeness WHERE FALSE;
SELECT run_id, run_at, universe_id, checks, passed, warned, failed, status, detail, created_at
  FROM validation_run_log WHERE FALSE;
