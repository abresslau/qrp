-- Verify sym:fact_index_returns on pg

SELECT sym_id, variant, window_id, as_of_date, ret, created_at, updated_at FROM fact_index_returns WHERE FALSE;
