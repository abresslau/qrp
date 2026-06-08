-- Verify sym:index_levels on pg

SELECT sym_id, session_date, variant, level, source, created_at FROM index_levels WHERE FALSE;
