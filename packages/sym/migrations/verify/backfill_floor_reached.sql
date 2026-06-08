-- Verify sym:backfill_floor_reached on pg

SELECT floor_reached FROM pipeline_backfill_progress WHERE FALSE;
