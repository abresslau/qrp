-- Deploy sym:index_levels_drop_variant to pg
-- requires: fact_index_returns

BEGIN;

-- Simplify: treat each published index series as its OWN index (instrument).
-- ^GSPC (S&P 500) and ^SP500TR (S&P 500 Total Return) are already distinct
-- instruments (distinct sym_id + Yahoo xref), so the per-row `variant` dimension
-- was redundant — the instrument name already distinguishes price vs total-return.
-- Drop it from both level + returns stores; each instrument has exactly one series,
-- so (sym_id, session_date) / (sym_id, window_id, as_of_date) is a clean key.
ALTER TABLE index_levels DROP CONSTRAINT index_levels_pk;
ALTER TABLE index_levels DROP COLUMN variant;          -- also drops index_levels_variant_chk
ALTER TABLE index_levels ADD CONSTRAINT index_levels_pk PRIMARY KEY (sym_id, session_date);

ALTER TABLE fact_index_returns DROP CONSTRAINT fact_index_returns_pk;
ALTER TABLE fact_index_returns DROP COLUMN variant;    -- also drops fact_index_returns_variant_chk
ALTER TABLE fact_index_returns ADD CONSTRAINT fact_index_returns_pk
    PRIMARY KEY (sym_id, window_id, as_of_date);

COMMIT;
