-- Revert sym:index_levels_drop_variant from pg

BEGIN;

ALTER TABLE fact_index_returns DROP CONSTRAINT fact_index_returns_pk;
ALTER TABLE fact_index_returns ADD COLUMN variant TEXT NOT NULL DEFAULT 'PR';
ALTER TABLE fact_index_returns ALTER COLUMN variant DROP DEFAULT;
ALTER TABLE fact_index_returns ADD CONSTRAINT fact_index_returns_variant_chk
    CHECK (variant IN ('PR', 'NTR', 'GTR'));
ALTER TABLE fact_index_returns ADD CONSTRAINT fact_index_returns_pk
    PRIMARY KEY (sym_id, variant, window_id, as_of_date);

ALTER TABLE index_levels DROP CONSTRAINT index_levels_pk;
ALTER TABLE index_levels ADD COLUMN variant TEXT NOT NULL DEFAULT 'PR';
ALTER TABLE index_levels ALTER COLUMN variant DROP DEFAULT;
ALTER TABLE index_levels ADD CONSTRAINT index_levels_variant_chk
    CHECK (variant IN ('PR', 'NTR', 'GTR'));
ALTER TABLE index_levels ADD CONSTRAINT index_levels_pk PRIMARY KEY (sym_id, session_date, variant);

COMMIT;
