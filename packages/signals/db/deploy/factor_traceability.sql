-- Deploy signals:factor_traceability to pg
-- requires: signals

BEGIN;

-- FR-21 traceability (Story Q9.3, folded into Q9.2): every factor names its inputs
-- (module-qualified refs, e.g. "altdata:wikipedia:pageviews") and states its method,
-- so a derived signal is reproducible and its cross-module provenance is explicit.
ALTER TABLE signals.factor
    ADD COLUMN inputs JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN method TEXT;

COMMENT ON COLUMN signals.factor.inputs IS
    'Module-qualified input refs (JSON array of strings, e.g. "macro:UST:DEBT", '
    '"sym:fact_returns:1D"). The cross-module provenance record (FR-21).';
COMMENT ON COLUMN signals.factor.method IS
    'How the raw value is computed, incl. stated definition choices (e.g. direction '
    'orientation) and honesty caveats (current-vintage macro, sparse coverage).';

COMMIT;
