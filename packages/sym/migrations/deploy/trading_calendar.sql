-- Deploy sym:trading_calendar to pg
-- requires: exchange

BEGIN;

-- Versioned snapshot of exchange_calendars trading sessions (AR-4 / D3). The DB
-- table -- never the library at query time -- is the read source for returns
-- window anchoring, and calendar_version participates in fact_returns.input_hash.
-- A re-snapshot whose content differs is written as a NEW version; prior
-- versions are never mutated (immutable history), so a fact_returns row stays
-- reproducible against the exact calendar it was computed under.
CREATE TABLE trading_calendar_version (
    calendar_version  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mic               CHAR(4)     NOT NULL,
    library           TEXT        NOT NULL DEFAULT 'exchange_calendars',
    library_version   TEXT        NOT NULL,
    content_hash      TEXT        NOT NULL,
    session_count     INTEGER     NOT NULL,
    first_session     DATE        NOT NULL,
    last_session      DATE        NOT NULL,
    is_current        BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trading_calendar_version_exchange_fk
        FOREIGN KEY (mic) REFERENCES exchange (mic),
    CONSTRAINT trading_calendar_version_count_chk CHECK (session_count >= 0),
    CONSTRAINT trading_calendar_version_range_chk CHECK (last_session >= first_session),
    -- Identical content for a MIC is never stored twice: a re-snapshot that
    -- produces the same sessions reuses the existing version (idempotency).
    CONSTRAINT trading_calendar_version_content_uq UNIQUE (mic, content_hash)
);

-- At most one currently-effective version per exchange.
CREATE UNIQUE INDEX trading_calendar_version_current_uq
    ON trading_calendar_version (mic) WHERE is_current;

CREATE TABLE trading_calendar (
    calendar_version  BIGINT      NOT NULL,
    mic               CHAR(4)     NOT NULL,
    session_date      DATE        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT trading_calendar_pk PRIMARY KEY (calendar_version, mic, session_date),
    CONSTRAINT trading_calendar_version_fk
        FOREIGN KEY (calendar_version)
        REFERENCES trading_calendar_version (calendar_version) ON DELETE CASCADE,
    CONSTRAINT trading_calendar_exchange_fk
        FOREIGN KEY (mic) REFERENCES exchange (mic)
);

-- "Is D a trading day on exchange X?" and ranged session scans.
CREATE INDEX idx_trading_calendar_mic_date ON trading_calendar (mic, session_date);

CREATE TRIGGER trading_calendar_version_set_updated_at
    BEFORE UPDATE ON trading_calendar_version
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE  trading_calendar_version IS 'One row per (exchange, calendar snapshot version). content_hash detects drift; is_current marks the active snapshot. Immutable: a differing re-snapshot adds a version, never mutates a prior one.';
COMMENT ON TABLE  trading_calendar         IS 'Open trading sessions per exchange per calendar_version (AR-4). The DB table is the read source for returns window anchoring; calendar_version feeds fact_returns.input_hash.';
COMMENT ON COLUMN trading_calendar_version.calendar_version IS 'Stable surrogate version handle; participates in fact_returns.input_hash (AR-7).';
COMMENT ON COLUMN trading_calendar_version.content_hash     IS 'sha256 of library_version + the ordered session list; identical content reuses the version (idempotent re-snapshot).';
COMMENT ON COLUMN trading_calendar_version.is_current       IS 'TRUE for the active snapshot of this exchange; superseded versions stay for reproducibility.';

COMMIT;
