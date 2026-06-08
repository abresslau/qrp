-- Deploy sym:price_storage to pg
-- requires: securities

-- Raw price ingestion storage (FR-5, AR-6/AR-7, NFR-2/3/6). Stores RAW OHLCV +
-- EXPLICIT corporate-action factors only -- never a vendor adjusted close;
-- adjusted prices are derived in Epic 3 (v_prices_adjusted). Immutable by default
-- (AR-10): backfill/delta insert ON CONFLICT DO NOTHING, so a re-run is a no-op.
BEGIN;

-- Raw, unadjusted daily bars. The yfinance adapter un-split-adjusts to true raw
-- before this layer (Story 2.2). No adjusted_close column by design (FR-5/AR-7).
CREATE TABLE prices_raw (
    composite_figi  CHAR(12)    NOT NULL,
    session_date    DATE        NOT NULL,
    open            NUMERIC     NOT NULL,
    high            NUMERIC     NOT NULL,
    low             NUMERIC     NOT NULL,
    close           NUMERIC     NOT NULL,
    volume          BIGINT      NOT NULL,
    currency_code   CHAR(3)     NOT NULL,
    source          TEXT        NOT NULL,
    retrieved_at    TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT prices_raw_pk PRIMARY KEY (composite_figi, session_date),
    CONSTRAINT prices_raw_positive_chk  CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CONSTRAINT prices_raw_ordering_chk   CHECK (high >= low AND high >= open AND high >= close
                                                AND low <= open AND low <= close),
    CONSTRAINT prices_raw_volume_chk     CHECK (volume >= 0),
    CONSTRAINT prices_raw_securities_fk  FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    CONSTRAINT prices_raw_currency_fk    FOREIGN KEY (currency_code) REFERENCES currency (code)
);

CREATE INDEX idx_prices_raw_session_date ON prices_raw (session_date);

CREATE TRIGGER prices_raw_set_updated_at
    BEFORE UPDATE ON prices_raw FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Explicit corporate-action factor store (AR-6). Splits (ratio, unitless) and
-- dividends (per-share amount in a currency). Factors come ONLY from these
-- explicit records, never reverse-engineered from price ratios.
CREATE TABLE corporate_actions (
    composite_figi  CHAR(12)    NOT NULL,
    ex_date         DATE        NOT NULL,
    action_type     TEXT        NOT NULL,
    value           NUMERIC     NOT NULL,
    currency_code   CHAR(3),
    source          TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT corporate_actions_pk PRIMARY KEY (composite_figi, ex_date, action_type),
    CONSTRAINT corporate_actions_type_chk  CHECK (action_type IN ('split', 'dividend')),
    CONSTRAINT corporate_actions_value_chk CHECK (value > 0),
    -- dividends carry a currency; splits (a ratio) do not.
    CONSTRAINT corporate_actions_currency_chk
        CHECK ((action_type = 'dividend') = (currency_code IS NOT NULL)),
    CONSTRAINT corporate_actions_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi),
    CONSTRAINT corporate_actions_currency_fk   FOREIGN KEY (currency_code) REFERENCES currency (code)
);

CREATE TRIGGER corporate_actions_set_updated_at
    BEFORE UPDATE ON corporate_actions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Per-figi ingestion cursor (NFR-6, AR-13). The writer advances cursor_date +
-- status atomically with the price rows -- the cursor never advances without rows.
CREATE TABLE pipeline_backfill_progress (
    composite_figi  CHAR(12)    PRIMARY KEY,
    source          TEXT        NOT NULL,
    cursor_date     DATE,
    status          TEXT        NOT NULL DEFAULT 'pending',
    detail          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pipeline_backfill_progress_status_chk CHECK (status IN ('pending', 'ok', 'error')),
    CONSTRAINT pipeline_backfill_progress_securities_fk
        FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi)
);

CREATE TRIGGER pipeline_backfill_progress_set_updated_at
    BEFORE UPDATE ON pipeline_backfill_progress FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Missing-price log (NFR-3): an open trading day (per trading_calendar) with no
-- vendor price. Recorded, never forward-filled.
CREATE TABLE price_gaps (
    composite_figi  CHAR(12)    NOT NULL,
    session_date    DATE        NOT NULL,
    source          TEXT        NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT price_gaps_pk PRIMARY KEY (composite_figi, session_date),
    CONSTRAINT price_gaps_securities_fk FOREIGN KEY (composite_figi) REFERENCES securities (composite_figi)
);

COMMENT ON TABLE prices_raw        IS 'Raw unadjusted daily OHLCV (FR-5). No adjusted close; adjusted is derived in v_prices_adjusted (AR-7).';
COMMENT ON TABLE corporate_actions IS 'Explicit split/dividend factor store (AR-6). Factors derive ONLY from these records.';
COMMENT ON TABLE pipeline_backfill_progress IS 'Per-figi ingestion cursor; advanced atomically with rows (NFR-6, AR-13).';
COMMENT ON TABLE price_gaps        IS 'Open trading days with no vendor price (NFR-3). Logged, never forward-filled.';

COMMIT;
