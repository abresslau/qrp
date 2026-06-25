-- Revert sym:index_extract from pg
-- Recreate the index objects in sym (EMPTY — the data lives in the indices database). Matches the live
-- sym schema just before the drop: post the index_levels_drop_variant simplification (no `variant`
-- column), and with sym_id -> instrument FKs intact + universe_id a SOFT reference (its universe FK
-- was already dropped by sym:universe_extract). set_updated_at() still exists in sym.

BEGIN;

CREATE TABLE index_levels (
    sym_id       bigint      NOT NULL,
    session_date date        NOT NULL,
    level        numeric     NOT NULL,
    source       text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT index_levels_pk        PRIMARY KEY (sym_id, session_date),
    CONSTRAINT index_levels_sym_fk    FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT index_levels_level_chk CHECK (level > 0)
);
CREATE INDEX idx_index_levels_date ON index_levels (session_date);

CREATE TABLE fact_index_returns (
    sym_id      bigint      NOT NULL,
    window_id   integer     NOT NULL,
    as_of_date  date        NOT NULL,
    ret         numeric,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_index_returns_pk PRIMARY KEY (sym_id, window_id, as_of_date),
    CONSTRAINT fact_index_returns_sym_fk    FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT fact_index_returns_window_fk FOREIGN KEY (window_id) REFERENCES return_window (window_id)
);
CREATE INDEX idx_fact_index_returns_asof ON fact_index_returns (as_of_date, window_id);
CREATE TRIGGER fact_index_returns_set_updated_at
    BEFORE UPDATE ON fact_index_returns FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE fact_index_extremes (
    sym_id          bigint      NOT NULL,
    as_of_date      date        NOT NULL,
    high_52w        numeric,
    low_52w         numeric,
    high_52w_date   date,
    low_52w_date    date,
    pct_off_high    numeric,
    pct_off_low     numeric,
    input_hash      text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_index_extremes_pk PRIMARY KEY (sym_id, as_of_date),
    CONSTRAINT fact_index_extremes_sym_fk FOREIGN KEY (sym_id) REFERENCES instrument (sym_id)
);
CREATE INDEX idx_fact_index_extremes_as_of_date ON fact_index_extremes (as_of_date);
CREATE TRIGGER fact_index_extremes_set_updated_at
    BEFORE UPDATE ON fact_index_extremes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE universe_benchmark (
    universe_id text        NOT NULL,
    sym_id      bigint      NOT NULL,
    role        text        NOT NULL,
    is_primary  boolean     NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_benchmark_pk PRIMARY KEY (universe_id, sym_id),
    CONSTRAINT universe_benchmark_sym_fk FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT universe_benchmark_role_chk
        CHECK (role IN ('price_return', 'total_return', 'net_total_return'))
);
CREATE UNIQUE INDEX uq_universe_benchmark_primary
    ON universe_benchmark (universe_id) WHERE is_primary;

COMMIT;
