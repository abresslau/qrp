-- Deploy indices:indices_schema to pg
--
-- The indices package's own database: benchmark index level series, the materialized index-returns
-- matrix + 52-week extremes, and the universe→benchmark link. Extracted from sym (the schema is
-- faithful to the sym originals, post the index_levels_drop_variant simplification — each published
-- series is its own instrument, so there is no `variant` row dimension) EXCEPT: the FKs to
-- `instrument` (sym DB) and `universe` (universe DB) are dropped to SOFT references — sym_id is a
-- stable bigint, those tables live in other databases, and Postgres has no cross-DB FK. The
-- return_window reference table is seeded locally (seed_reference) so its FK stays intact same-DB.
-- Objects live in a dedicated `indices` schema + a DB-level search_path resolves bare names.

CREATE SCHEMA IF NOT EXISTS indices;

BEGIN;

-- updated_at touch trigger (sym's set_updated_at, verbatim).
CREATE OR REPLACE FUNCTION indices.set_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

-- ===== reference table (seeded in seed_reference; kept here so the FK resolves same-DB) =====
CREATE TABLE indices.return_window (
    window_id integer NOT NULL,
    code text NOT NULL,
    label text NOT NULL,
    kind text NOT NULL,
    annualized boolean DEFAULT false NOT NULL,
    CONSTRAINT return_window_pkey PRIMARY KEY (window_id),
    CONSTRAINT return_window_code_key UNIQUE (code),
    CONSTRAINT return_window_kind_chk CHECK ((kind = ANY (ARRAY['calendar'::text, 'session'::text, 'trailing'::text, 'inception'::text, 'period'::text])))
);

-- ===== benchmark index level series (B2) — level-only, immutable, source-tagged =====
-- Keyed on the universal sym_id (instrument lives in the sym DB → soft reference, no cross-DB FK).
CREATE TABLE indices.index_levels (
    sym_id       bigint      NOT NULL,
    session_date date        NOT NULL,
    level        numeric     NOT NULL,
    source       text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT index_levels_pk      PRIMARY KEY (sym_id, session_date),
    CONSTRAINT index_levels_level_chk CHECK (level > 0)
);
CREATE INDEX idx_index_levels_date ON indices.index_levels (session_date);
COMMENT ON TABLE indices.index_levels IS 'Benchmark index level series (B2), keyed on sym_id. Level-only, immutable, source-tagged; NOT prices_raw. sym_id -> instrument is a soft ref (sym DB).';

-- ===== materialized benchmark index returns (B3) — level ratios over the 18 windows =====
CREATE TABLE indices.fact_index_returns (
    sym_id      bigint      NOT NULL,
    window_id   integer     NOT NULL,
    as_of_date  date        NOT NULL,
    ret         numeric,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fact_index_returns_pk PRIMARY KEY (sym_id, window_id, as_of_date),
    CONSTRAINT fact_index_returns_window_fk FOREIGN KEY (window_id) REFERENCES indices.return_window (window_id)
);
CREATE INDEX idx_fact_index_returns_asof ON indices.fact_index_returns (as_of_date, window_id);
CREATE TRIGGER fact_index_returns_set_updated_at
    BEFORE UPDATE ON indices.fact_index_returns
    FOR EACH ROW EXECUTE FUNCTION indices.set_updated_at();
COMMENT ON TABLE indices.fact_index_returns IS 'Materialized benchmark index returns (B3), from index_levels level ratios over the 18 windows. Alpha = asset return - benchmark return at the same (window, as_of_date). sym_id soft ref (sym DB).';

-- ===== 52-week index extremes (3.2-ext) — no gate (index levels are unflagged) =====
CREATE TABLE indices.fact_index_extremes (
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
    CONSTRAINT fact_index_extremes_pk PRIMARY KEY (sym_id, as_of_date)
);
CREATE INDEX idx_fact_index_extremes_as_of_date ON indices.fact_index_extremes (as_of_date);
CREATE TRIGGER fact_index_extremes_set_updated_at
    BEFORE UPDATE ON indices.fact_index_extremes FOR EACH ROW EXECUTE FUNCTION indices.set_updated_at();
COMMENT ON TABLE indices.fact_index_extremes IS 'Materialized 52-week (trailing 365d) high/low of the index level + pct-off, per (sym_id, as_of_date). input_hash dirty-set; no gate. sym_id soft ref (sym DB).';

-- ===== universe → benchmark link — both FKs are soft (universe DB + sym DB) =====
CREATE TABLE indices.universe_benchmark (
    universe_id text        NOT NULL,
    sym_id      bigint      NOT NULL,
    role        text        NOT NULL,
    is_primary  boolean     NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT universe_benchmark_pk PRIMARY KEY (universe_id, sym_id),
    CONSTRAINT universe_benchmark_role_chk
        CHECK (role IN ('price_return', 'total_return', 'net_total_return'))
);
-- At most one primary benchmark per universe.
CREATE UNIQUE INDEX uq_universe_benchmark_primary
    ON indices.universe_benchmark (universe_id) WHERE is_primary;
COMMENT ON TABLE indices.universe_benchmark IS 'Links an index universe (constituents, universe DB) to its benchmark index series (instrument, sym DB). universe_id + sym_id are both soft refs (cross-DB).';

COMMIT;

-- search_path is a per-database setting that takes effect on subsequent connections (cannot run in
-- the transaction above; idempotent + connection-scoped).
ALTER DATABASE indices SET search_path TO indices, public;
