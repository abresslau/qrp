-- Revert sym:equity_extract from pg
-- Recreates the equity objects in the sym database (schema only; the data lives in the equity
-- database). Faithful to the original sym migrations (price_storage / fact_returns / v_prices_adjusted
-- / prices_review / fact_price_extremes / pipeline_run_log), in their final form, with the
-- securities/currency/return_window FKs restored.

BEGIN;

CREATE AGGREGATE product(numeric) (
    sfunc = numeric_mul,
    stype = numeric,
    initcond = '1'
);

CREATE TABLE prices_raw (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    session_date date NOT NULL,
    open numeric NOT NULL,
    high numeric NOT NULL,
    low numeric NOT NULL,
    close numeric NOT NULL,
    volume bigint NOT NULL,
    currency_code character(3) NOT NULL REFERENCES currency (code),
    source text NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT prices_raw_pk PRIMARY KEY (composite_figi, session_date),
    CONSTRAINT prices_raw_ordering_chk CHECK (((high >= low) AND (high >= open) AND (high >= close) AND (low <= open) AND (low <= close))),
    CONSTRAINT prices_raw_positive_chk CHECK (((open > (0)::numeric) AND (high > (0)::numeric) AND (low > (0)::numeric) AND (close > (0)::numeric))),
    CONSTRAINT prices_raw_volume_chk CHECK ((volume >= 0))
);
CREATE INDEX idx_prices_raw_session_date ON prices_raw USING btree (session_date);
CREATE TRIGGER prices_raw_set_updated_at BEFORE UPDATE ON prices_raw
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE corporate_actions (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    ex_date date NOT NULL,
    action_type text NOT NULL,
    value numeric NOT NULL,
    currency_code character(3) REFERENCES currency (code),
    source text NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT corporate_actions_pk PRIMARY KEY (composite_figi, ex_date, action_type),
    CONSTRAINT corporate_actions_currency_chk CHECK (((action_type = 'dividend'::text) = (currency_code IS NOT NULL))),
    CONSTRAINT corporate_actions_type_chk CHECK ((action_type = ANY (ARRAY['split'::text, 'dividend'::text]))),
    CONSTRAINT corporate_actions_value_chk CHECK ((value > (0)::numeric))
);
CREATE TRIGGER corporate_actions_set_updated_at BEFORE UPDATE ON corporate_actions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE price_gaps (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    session_date date NOT NULL,
    source text NOT NULL,
    detected_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT price_gaps_pk PRIMARY KEY (composite_figi, session_date)
);

CREATE TABLE prices_review (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    session_date date NOT NULL,
    flag_type text NOT NULL,
    detail text,
    pct_move numeric,
    source text NOT NULL,
    reviewed boolean DEFAULT false NOT NULL,
    resolution text,
    reviewed_at timestamptz,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT prices_review_pk PRIMARY KEY (composite_figi, session_date, flag_type),
    CONSTRAINT prices_review_prices_fk FOREIGN KEY (composite_figi, session_date) REFERENCES prices_raw (composite_figi, session_date),
    CONSTRAINT prices_review_flag_type_chk CHECK ((flag_type = ANY (ARRAY['price_jump'::text, 'price_on_non_trading_day'::text, 'sweep_divergence'::text]))),
    CONSTRAINT prices_review_resolution_chk CHECK (((resolution IS NULL) OR (resolution = ANY (ARRAY['confirmed'::text, 'rejected'::text])))),
    CONSTRAINT prices_review_reviewed_chk CHECK ((reviewed = (resolution IS NOT NULL)))
);
CREATE INDEX idx_prices_review_unreviewed ON prices_review USING btree (composite_figi) WHERE (NOT reviewed);
CREATE TRIGGER prices_review_set_updated_at BEFORE UPDATE ON prices_review
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE pipeline_backfill_progress (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    source text NOT NULL,
    cursor_date date,
    status text DEFAULT 'pending'::text NOT NULL,
    detail text,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    floor_reached_date date,
    CONSTRAINT pipeline_backfill_progress_pkey PRIMARY KEY (composite_figi),
    CONSTRAINT pipeline_backfill_progress_status_chk CHECK ((status = ANY (ARRAY['pending'::text, 'ok'::text, 'error'::text])))
);
CREATE TRIGGER pipeline_backfill_progress_set_updated_at BEFORE UPDATE ON pipeline_backfill_progress
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE pipeline_run_log (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mode text NOT NULL,
    source text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    attempted integer DEFAULT 0 NOT NULL,
    loaded integer DEFAULT 0 NOT NULL,
    skipped integer DEFAULT 0 NOT NULL,
    errored integer DEFAULT 0 NOT NULL,
    rows_written bigint DEFAULT 0 NOT NULL,
    anomaly_flags integer DEFAULT 0 NOT NULL,
    gaps integer DEFAULT 0 NOT NULL,
    status text NOT NULL,
    detail text,
    created_at timestamptz DEFAULT now() NOT NULL,
    triggered_by text,
    CONSTRAINT pipeline_run_log_counts_chk CHECK (((attempted >= 0) AND (loaded >= 0) AND (skipped >= 0) AND (errored >= 0))),
    CONSTRAINT pipeline_run_log_range_chk CHECK ((finished_at >= started_at)),
    CONSTRAINT pipeline_run_log_status_chk CHECK ((status = ANY (ARRAY['success'::text, 'partial'::text]))),
    CONSTRAINT pipeline_run_log_status_consistency_chk CHECK (((errored = 0) = (status = 'success'::text)))
);
CREATE INDEX idx_pipeline_run_log_started ON pipeline_run_log USING btree (started_at DESC);

CREATE TABLE fact_returns (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    window_id integer NOT NULL REFERENCES return_window (window_id),
    as_of_date date NOT NULL,
    pr numeric,
    tr numeric,
    input_hash text NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    gated boolean DEFAULT false NOT NULL,
    CONSTRAINT fact_returns_pk PRIMARY KEY (composite_figi, window_id, as_of_date)
);
CREATE INDEX idx_fact_returns_as_of_date_window ON fact_returns USING btree (as_of_date, window_id);
CREATE INDEX idx_fact_returns_published ON fact_returns USING btree (as_of_date, window_id) WHERE (NOT gated);
CREATE TRIGGER fact_returns_set_updated_at BEFORE UPDATE ON fact_returns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE fact_price_extremes (
    composite_figi character(12) NOT NULL REFERENCES securities (composite_figi),
    as_of_date date NOT NULL,
    high_52w numeric,
    low_52w numeric,
    high_52w_date date,
    low_52w_date date,
    pct_off_high numeric,
    pct_off_low numeric,
    input_hash text NOT NULL,
    gated boolean DEFAULT false NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT fact_price_extremes_pk PRIMARY KEY (composite_figi, as_of_date)
);
CREATE INDEX idx_fact_price_extremes_as_of_date ON fact_price_extremes USING btree (as_of_date);
CREATE INDEX idx_fact_price_extremes_published ON fact_price_extremes USING btree (as_of_date) WHERE (NOT gated);
CREATE TRIGGER fact_price_extremes_set_updated_at BEFORE UPDATE ON fact_price_extremes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE VIEW v_prices_adjusted AS
SELECT
    p.composite_figi,
    p.session_date,
    p.currency_code,
    p.close AS close_raw,
    f.split_factor,
    p.close / f.split_factor AS adj_close
FROM prices_raw p
CROSS JOIN LATERAL (
    SELECT COALESCE(product(ca.value), 1) AS split_factor
    FROM corporate_actions ca
    WHERE ca.composite_figi = p.composite_figi
      AND ca.action_type = 'split'
      AND ca.ex_date > p.session_date
) f;

COMMIT;
