-- Deploy sym:gics_source_opinion to pg
-- requires: gics_scd

BEGIN;

-- btree_gist powers the per-(figi, source) no-overlap exclusion (also pulled in by
-- gics_scd / security_symbology; CREATE ... IF NOT EXISTS is idempotent).
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Per-SOURCE GICS opinion store (multi-source classification matrix). Distinct from
-- gics_scd, which holds the ONE precedence-resolved classification per security: this
-- table holds EVERY source's own opinion of a company concurrently, so the detail view
-- can show "what each source says" and disagreement is visible. Same SCD shape as
-- gics_scd, but the no-overlap exclusion is keyed on (composite_figi, source) so
-- different sources coexist for one company while a single source keeps point-in-time
-- integrity. gics_scd is NOT derived from this (yet) — it remains the resolved truth.
CREATE TABLE gics_source_opinion (
    opinion_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    composite_figi       CHAR(12)    NOT NULL,
    source               TEXT        NOT NULL,
    sector_code          TEXT,
    sector_name          TEXT,
    industry_group_code  TEXT,
    industry_group_name  TEXT,
    industry_code        TEXT,
    industry_name        TEXT,
    sub_industry_code    TEXT,
    sub_industry_name    TEXT,
    valid_from           DATE        NOT NULL,
    valid_to             DATE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT gso_figi_chk      CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT gso_validity_chk  CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT gso_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    -- One company may hold at most one EFFECTIVE opinion PER SOURCE over any instant,
    -- but several sources may hold opinions at once (the whole point of the matrix).
    CONSTRAINT gso_no_overlap EXCLUDE USING gist (
        composite_figi WITH =,
        source WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

CREATE INDEX idx_gso_composite_figi ON gics_source_opinion (composite_figi);
CREATE INDEX idx_gso_source         ON gics_source_opinion (source);
CREATE INDEX idx_gso_sector         ON gics_source_opinion (sector_name);

CREATE TRIGGER gso_set_updated_at
    BEFORE UPDATE ON gics_source_opinion
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE gics_source_opinion IS
    'Per-source GICS opinion matrix (every source''s own classification per security; SCD, keyed on (figi, source)). gics_scd remains the precedence-resolved truth.';

COMMIT;
