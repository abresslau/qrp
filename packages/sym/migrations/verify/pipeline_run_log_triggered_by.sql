-- Verify sym:pipeline_run_log_triggered_by on pg

SELECT triggered_by FROM pipeline_run_log WHERE FALSE;
