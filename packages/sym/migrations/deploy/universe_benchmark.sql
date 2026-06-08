-- Deploy sym:universe_benchmark to pg
-- requires: universe
-- requires: instrument

BEGIN;

-- Link an equity-index universe (its point-in-time constituents, universe_membership)
-- to its benchmark index level series (an `index` instrument). This lets a study
-- pull, as-of any date, BOTH the constituents AND the published index level/return.
-- A universe may link to several benchmark instruments (e.g. price-return AND
-- total-return are separate indexes/sym_ids); one is marked primary.
CREATE TABLE universe_benchmark (
    universe_id TEXT        NOT NULL,
    sym_id      BIGINT      NOT NULL,
    role        TEXT        NOT NULL,
    is_primary  BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_benchmark_pk PRIMARY KEY (universe_id, sym_id),
    CONSTRAINT universe_benchmark_universe_fk FOREIGN KEY (universe_id)
        REFERENCES universe (universe_id),
    CONSTRAINT universe_benchmark_sym_fk FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT universe_benchmark_role_chk
        CHECK (role IN ('price_return', 'total_return', 'net_total_return'))
);

-- At most one primary benchmark per universe.
CREATE UNIQUE INDEX uq_universe_benchmark_primary
    ON universe_benchmark (universe_id) WHERE is_primary;

COMMENT ON TABLE universe_benchmark IS 'Links an index universe (constituents) to its benchmark index level series (instrument). Constituents + benchmark return are then joinable as-of any date.';

COMMIT;
