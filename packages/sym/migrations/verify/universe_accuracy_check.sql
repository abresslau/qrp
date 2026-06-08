-- Verify sym:universe_accuracy_check on pg

SELECT check_id, universe_id, checked_at, as_of, reference_source, maintained_count,
       reference_count, missing, extra, divergence, threshold, alarm, detail, created_at
  FROM universe_accuracy_check
 WHERE FALSE;
