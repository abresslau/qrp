-- Deploy sym:index_levels to pg
-- requires: instrument

BEGIN;

-- Benchmark index level series (Benchmark epic, B2). Indexes are level/close-ONLY
-- (no OHLCV, no splits, no per-name corporate actions), so they get their own
-- store keyed on the universal sym_id — deliberately NOT prices_raw (whose split/
-- dividend machinery would corrupt them). The `variant` row dimension keeps the
-- return treatments distinct (PR price-return, NTR net-total-return, GTR gross-
-- total-return) — conflating them silently corrupts alpha. Immutable + source-tagged.
CREATE TABLE index_levels (
    sym_id       BIGINT      NOT NULL,
    session_date DATE        NOT NULL,
    variant      TEXT        NOT NULL,
    level        NUMERIC     NOT NULL,
    source       TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT index_levels_pk        PRIMARY KEY (sym_id, session_date, variant),
    CONSTRAINT index_levels_sym_fk    FOREIGN KEY (sym_id) REFERENCES instrument (sym_id),
    CONSTRAINT index_levels_variant_chk CHECK (variant IN ('PR', 'NTR', 'GTR')),
    CONSTRAINT index_levels_level_chk   CHECK (level > 0)
);

CREATE INDEX idx_index_levels_date ON index_levels (session_date);

COMMENT ON TABLE  index_levels         IS 'Benchmark index level series (B2), keyed on sym_id. Level-only, immutable, source-tagged; NOT prices_raw.';
COMMENT ON COLUMN index_levels.variant IS 'PR (price return) | NTR (net total return) | GTR (gross total return). Never conflate — they imply different alpha.';

COMMIT;
