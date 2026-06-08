-- Deploy sym:fx_source_rank to pg
-- requires: fx_rate

BEGIN;

-- Source trust tier for the canonical read-side pick when two sources hold a rate for the
-- same (pair, as_of_date): lower wins. Mirrors SOURCE_PRECEDENCE in src/sym/fx/source.py.
-- Frankfurter (primary) < ECB (reconcile) < fawazahmed0 (breadth fallback) < unknown.
CREATE FUNCTION fx_source_rank(source TEXT) RETURNS INT
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE source
        WHEN 'frankfurter' THEN 10
        WHEN 'ecb'         THEN 20
        WHEN 'fawazahmed0' THEN 30
        ELSE 100
    END
$$;

COMMENT ON FUNCTION fx_source_rank(TEXT) IS
    'FX source trust tier (lower preferred) for the canonical (pair,date) pick across sources. Mirrors SOURCE_PRECEDENCE in sym.fx.source.';

COMMIT;
