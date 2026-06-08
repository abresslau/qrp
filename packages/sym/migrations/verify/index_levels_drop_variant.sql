-- Verify sym:index_levels_drop_variant on pg

SELECT level FROM index_levels WHERE FALSE;
SELECT ret FROM fact_index_returns WHERE FALSE;
