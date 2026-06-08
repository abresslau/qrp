-- Deploy sym:fact_returns_gated to pg
-- requires: fact_returns

-- Stage-2 anomaly gate (AR-9 / NFR-1, gate half). A fact_returns row whose asof or
-- base references an UNREVIEWED prices_review flag is marked gated (pr/tr held NULL)
-- so a suspect price never reaches PUBLISHED returns; published consumers filter
-- WHERE NOT gated. Reviewing the flag un-gates the row on the next recompute.
BEGIN;

ALTER TABLE fact_returns ADD COLUMN gated BOOLEAN NOT NULL DEFAULT FALSE;

-- Published cross-sectional access ("all securities, one asof+window, not gated").
CREATE INDEX idx_fact_returns_published ON fact_returns (asof, window_id) WHERE NOT gated;

COMMENT ON COLUMN fact_returns.gated IS 'TRUE when an endpoint references an unreviewed prices_review flag (AR-9 gate). Published returns exclude gated rows; cleared and re-materialized once the flag is reviewed.';

COMMIT;
