-- Deploy sym:universe to pg
-- requires: updated_at_trigger

BEGIN;

-- Universe registry (Story U1.1). One row per defined research universe; the
-- membership itself lives in the event log + projection (later stories). kind
-- selects the provider archetype (config-keyed, AR-5). config/source_pref are
-- provider-specific JSON. pit_valid_from is the start of trustworthy point-in-
-- time history (NULL until set) -- queries before it must refuse/flag, never
-- back-project (survivorship guardrail).
CREATE TABLE universe (
    universe_id     TEXT        PRIMARY KEY,
    name            TEXT        NOT NULL,
    kind            TEXT        NOT NULL,
    config          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    pit_valid_from  DATE,
    source_pref     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT universe_id_format_chk CHECK (universe_id ~ '^[a-z0-9][a-z0-9_-]*$'),
    CONSTRAINT universe_kind_chk      CHECK (kind IN ('custom_list', 'index', 'criteria'))
);

CREATE TRIGGER universe_set_updated_at
    BEFORE UPDATE ON universe
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  universe                IS 'Defined research universes (Story U1.1). Membership lives in the event log + projection; this is the registry.';
COMMENT ON COLUMN universe.universe_id    IS 'Short stable slug (e.g. seed, sp500). Primary identity used by the CLI and membership tables.';
COMMENT ON COLUMN universe.kind           IS 'Provider archetype: custom_list | index | criteria (config-keyed, AR-5).';
COMMENT ON COLUMN universe.pit_valid_from IS 'Start of trustworthy point-in-time history; queries before it refuse/flag (never back-project). NULL until set.';

COMMIT;
