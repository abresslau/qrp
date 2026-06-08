-- Verify sym:universe_benchmark on pg

SELECT universe_id, sym_id, role, is_primary, created_at FROM universe_benchmark WHERE FALSE;
