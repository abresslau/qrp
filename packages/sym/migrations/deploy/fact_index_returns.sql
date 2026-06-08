-- Deploy sym:fact_index_returns to pg
-- requires: index_levels
-- requires: fact_returns

BEGIN;

-- Materialized benchmark index returns (Benchmark epic, B3). Computed from
-- index_levels as pure level ratios over the same 18 windows as fact_returns (no
-- split/dividend math — an index level already embeds its return treatment via
-- variant). Keyed on sym_id + variant so PR/NTR/GTR returns stay distinct. Alpha
-- (excess return) = a security/universe return minus the benchmark return for the
-- same window + as_of_date, computed at query time.
CREATE TABLE fact_index_returns (
    sym_id      BIGINT      NOT NULL,
    variant     TEXT        NOT NULL,
    window_id   INTEGER     NOT NULL,
    as_of_date  DATE        NOT NULL,
    ret         NUMERIC,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fact_index_returns_pk PRIMARY KEY (sym_id, variant, window_id, as_of_date),
    CONSTRAINT fact_index_returns_sym_fk    FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT fact_index_returns_window_fk FOREIGN KEY (window_id) REFERENCES return_window (window_id),
    CONSTRAINT fact_index_returns_variant_chk CHECK (variant IN ('PR', 'NTR', 'GTR'))
);

CREATE INDEX idx_fact_index_returns_asof ON fact_index_returns (as_of_date, window_id);

CREATE TRIGGER fact_index_returns_set_updated_at
    BEFORE UPDATE ON fact_index_returns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE fact_index_returns IS 'Materialized benchmark index returns (B3), from index_levels level ratios over the 18 windows. Alpha = asset return - benchmark return at the same (window, as_of_date).';

COMMIT;
