-- Deploy sym:fundamentals to pg
-- requires: securities

BEGIN;

-- Minimal fundamentals input (Story U5.1) — the reference data a rules-based
-- screen (U5.2) needs that sym does not otherwise store: market cap + shares
-- outstanding, as an effective-dated snapshot (as_of). ADV is derivable from the
-- stored EOD volume×price, so it is not duplicated here. A missing value is left
-- NULL + flagged in detail (never faked). Mutable per (figi, as_of) snapshot.
CREATE TABLE fundamentals (
    composite_figi     CHAR(12)    NOT NULL,
    as_of              DATE        NOT NULL,
    market_cap         NUMERIC,
    shares_outstanding NUMERIC,
    currency_code      CHAR(3),
    source             TEXT        NOT NULL,
    detail             JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fundamentals_pk PRIMARY KEY (composite_figi, as_of),
    CONSTRAINT fundamentals_figi_fk FOREIGN KEY (composite_figi)
        REFERENCES securities (composite_figi),
    CONSTRAINT fundamentals_nonneg_chk
        CHECK ((market_cap IS NULL OR market_cap >= 0)
           AND (shares_outstanding IS NULL OR shares_outstanding >= 0))
);

CREATE INDEX idx_fundamentals_asof_mktcap
    ON fundamentals (as_of, market_cap DESC NULLS LAST);

CREATE TRIGGER fundamentals_set_updated_at
    BEFORE UPDATE ON fundamentals
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  fundamentals       IS 'Minimal fundamentals input (Story U5.1): market cap + shares outstanding, effective-dated, for rules-based screens (U5.2). Missing values stay NULL + flagged, never faked.';
COMMENT ON COLUMN fundamentals.as_of IS 'Snapshot date; a screen reads the latest snapshot on/before its evaluation date.';

COMMIT;
