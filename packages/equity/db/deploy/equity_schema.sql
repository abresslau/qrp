-- Deploy equity:equity_schema to pg
--
-- The equity package's own database: raw equity prices, explicit corporate-action factors, the
-- deterministic split-adjusted view, and the reproducible PR/TR returns matrix. Extracted verbatim
-- from sym (the schema is byte-faithful to the sym originals) EXCEPT: the FKs to securities are
-- dropped to SOFT references (composite_figi is a stable string; securities lives in the sym DB and
-- Postgres has no cross-DB FK). The currency + return_window reference tables are seeded locally
-- (seed_reference) so their FKs stay intact same-DB. Tables live in `public` (like sym).

BEGIN;

-- updated_at touch trigger (sym's set_updated_at, verbatim).
CREATE OR REPLACE FUNCTION public.set_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

-- Exact NUMERIC product aggregate for cumulative split factors (exp(sum(ln())) would be float and
-- turn a 4:1 split into 3.9999...; this is exact + deterministic). Required by v_prices_adjusted.
CREATE AGGREGATE public.product(numeric) (
    sfunc = numeric_mul,
    stype = numeric,
    initcond = '1'
);

-- ===== reference tables (seeded in seed_reference; kept here so FKs resolve same-DB) =====
CREATE TABLE public.currency (
    code character(3) NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT currency_pkey PRIMARY KEY (code),
    CONSTRAINT currency_code_format_chk CHECK ((code ~ '^[A-Z]{3}$'::text))
);
CREATE TRIGGER currency_set_updated_at BEFORE UPDATE ON public.currency
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.return_window (
    window_id integer NOT NULL,
    code text NOT NULL,
    label text NOT NULL,
    kind text NOT NULL,
    annualized boolean DEFAULT false NOT NULL,
    CONSTRAINT return_window_pkey PRIMARY KEY (window_id),
    CONSTRAINT return_window_code_key UNIQUE (code),
    CONSTRAINT return_window_kind_chk CHECK ((kind = ANY (ARRAY['calendar'::text, 'session'::text, 'trailing'::text, 'inception'::text, 'period'::text])))
);

-- ===== raw prices =====
CREATE TABLE public.prices_raw (
    composite_figi character(12) NOT NULL,
    session_date date NOT NULL,
    open numeric NOT NULL,
    high numeric NOT NULL,
    low numeric NOT NULL,
    close numeric NOT NULL,
    volume bigint NOT NULL,
    currency_code character(3) NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT prices_raw_pk PRIMARY KEY (composite_figi, session_date),
    CONSTRAINT prices_raw_currency_fk FOREIGN KEY (currency_code) REFERENCES public.currency(code),
    CONSTRAINT prices_raw_ordering_chk CHECK (((high >= low) AND (high >= open) AND (high >= close) AND (low <= open) AND (low <= close))),
    CONSTRAINT prices_raw_positive_chk CHECK (((open > (0)::numeric) AND (high > (0)::numeric) AND (low > (0)::numeric) AND (close > (0)::numeric))),
    CONSTRAINT prices_raw_volume_chk CHECK ((volume >= 0))
);
COMMENT ON TABLE public.prices_raw IS 'Raw unadjusted daily OHLCV (FR-5). No adjusted close; adjusted is derived in v_prices_adjusted (AR-7). composite_figi -> securities is a SOFT reference (sym DB).';
CREATE INDEX idx_prices_raw_session_date ON public.prices_raw USING btree (session_date);
CREATE TRIGGER prices_raw_set_updated_at BEFORE UPDATE ON public.prices_raw
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== explicit corporate-action factors =====
CREATE TABLE public.corporate_actions (
    composite_figi character(12) NOT NULL,
    ex_date date NOT NULL,
    action_type text NOT NULL,
    value numeric NOT NULL,
    currency_code character(3),
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT corporate_actions_pk PRIMARY KEY (composite_figi, ex_date, action_type),
    CONSTRAINT corporate_actions_currency_fk FOREIGN KEY (currency_code) REFERENCES public.currency(code),
    CONSTRAINT corporate_actions_currency_chk CHECK (((action_type = 'dividend'::text) = (currency_code IS NOT NULL))),
    CONSTRAINT corporate_actions_type_chk CHECK ((action_type = ANY (ARRAY['split'::text, 'dividend'::text]))),
    CONSTRAINT corporate_actions_value_chk CHECK ((value > (0)::numeric))
);
COMMENT ON TABLE public.corporate_actions IS 'Explicit split/dividend factor store (AR-6). Factors derive ONLY from these records. composite_figi -> securities is a SOFT reference (sym DB).';
CREATE TRIGGER corporate_actions_set_updated_at BEFORE UPDATE ON public.corporate_actions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== gap log =====
CREATE TABLE public.price_gaps (
    composite_figi character(12) NOT NULL,
    session_date date NOT NULL,
    source text NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT price_gaps_pk PRIMARY KEY (composite_figi, session_date)
);
COMMENT ON TABLE public.price_gaps IS 'Open trading days with no vendor price (NFR-3). Logged, never forward-filled. composite_figi -> securities is a SOFT reference (sym DB).';

-- ===== stage-1 anomaly flags =====
CREATE TABLE public.prices_review (
    composite_figi character(12) NOT NULL,
    session_date date NOT NULL,
    flag_type text NOT NULL,
    detail text,
    pct_move numeric,
    source text NOT NULL,
    reviewed boolean DEFAULT false NOT NULL,
    resolution text,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT prices_review_pk PRIMARY KEY (composite_figi, session_date, flag_type),
    CONSTRAINT prices_review_prices_fk FOREIGN KEY (composite_figi, session_date) REFERENCES public.prices_raw(composite_figi, session_date),
    CONSTRAINT prices_review_flag_type_chk CHECK ((flag_type = ANY (ARRAY['price_jump'::text, 'price_on_non_trading_day'::text, 'sweep_divergence'::text]))),
    CONSTRAINT prices_review_resolution_chk CHECK (((resolution IS NULL) OR (resolution = ANY (ARRAY['confirmed'::text, 'rejected'::text])))),
    CONSTRAINT prices_review_reviewed_chk CHECK ((reviewed = (resolution IS NOT NULL)))
);
COMMENT ON TABLE public.prices_review IS 'Stage-1 anomaly flags, one per (figi, session_date, flag_type). Stage-2 gate excludes unreviewed-flag dates from fact_returns. composite_figi -> securities is a SOFT reference (sym DB).';
CREATE INDEX idx_prices_review_unreviewed ON public.prices_review USING btree (composite_figi) WHERE (NOT reviewed);
CREATE TRIGGER prices_review_set_updated_at BEFORE UPDATE ON public.prices_review
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== per-figi ingest cursor =====
CREATE TABLE public.pipeline_backfill_progress (
    composite_figi character(12) NOT NULL,
    source text NOT NULL,
    cursor_date date,
    status text DEFAULT 'pending'::text NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    floor_reached_date date,
    CONSTRAINT pipeline_backfill_progress_pkey PRIMARY KEY (composite_figi),
    CONSTRAINT pipeline_backfill_progress_status_chk CHECK ((status = ANY (ARRAY['pending'::text, 'ok'::text, 'error'::text])))
);
COMMENT ON TABLE public.pipeline_backfill_progress IS 'Per-figi ingestion cursor; advanced atomically with rows (NFR-6, AR-13). composite_figi -> securities is a SOFT reference (sym DB).';
CREATE TRIGGER pipeline_backfill_progress_set_updated_at BEFORE UPDATE ON public.pipeline_backfill_progress
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== run-level pipeline log =====
CREATE TABLE public.pipeline_run_log (
    run_id bigint NOT NULL,
    mode text NOT NULL,
    source text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone NOT NULL,
    attempted integer DEFAULT 0 NOT NULL,
    loaded integer DEFAULT 0 NOT NULL,
    skipped integer DEFAULT 0 NOT NULL,
    errored integer DEFAULT 0 NOT NULL,
    rows_written bigint DEFAULT 0 NOT NULL,
    anomaly_flags integer DEFAULT 0 NOT NULL,
    gaps integer DEFAULT 0 NOT NULL,
    status text NOT NULL,
    detail text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    triggered_by text,
    CONSTRAINT pipeline_run_log_pkey PRIMARY KEY (run_id),
    CONSTRAINT pipeline_run_log_counts_chk CHECK (((attempted >= 0) AND (loaded >= 0) AND (skipped >= 0) AND (errored >= 0))),
    CONSTRAINT pipeline_run_log_range_chk CHECK ((finished_at >= started_at)),
    CONSTRAINT pipeline_run_log_status_chk CHECK ((status = ANY (ARRAY['success'::text, 'partial'::text]))),
    CONSTRAINT pipeline_run_log_status_consistency_chk CHECK (((errored = 0) = (status = 'success'::text)))
);
COMMENT ON TABLE public.pipeline_run_log IS 'Run-level pipeline log (FR-8, NFR-7). Run-level counts, separate from the per-figi pipeline_backfill_progress cursor.';
ALTER TABLE public.pipeline_run_log ALTER COLUMN run_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.pipeline_run_log_run_id_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1
);
CREATE INDEX idx_pipeline_run_log_started ON public.pipeline_run_log USING btree (started_at DESC);

-- ===== materialized PR/TR matrix =====
CREATE TABLE public.fact_returns (
    composite_figi character(12) NOT NULL,
    window_id integer NOT NULL,
    as_of_date date CONSTRAINT fact_returns_asof_not_null NOT NULL,
    pr numeric,
    tr numeric,
    input_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    gated boolean DEFAULT false NOT NULL,
    CONSTRAINT fact_returns_pk PRIMARY KEY (composite_figi, window_id, as_of_date),
    CONSTRAINT fact_returns_window_fk FOREIGN KEY (window_id) REFERENCES public.return_window(window_id)
);
COMMENT ON TABLE public.fact_returns IS 'Materialized PR/TR matrix (AR-7). Loader-written; incremental dirty-set refresh; each row stamped input_hash = hash(raw_slice + factor_set + calendar_version). composite_figi -> securities is a SOFT reference (sym DB).';
CREATE INDEX idx_fact_returns_as_of_date_window ON public.fact_returns USING btree (as_of_date, window_id);
CREATE INDEX idx_fact_returns_published ON public.fact_returns USING btree (as_of_date, window_id) WHERE (NOT gated);
CREATE TRIGGER fact_returns_set_updated_at BEFORE UPDATE ON public.fact_returns
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== materialized 52-week extremes =====
CREATE TABLE public.fact_price_extremes (
    composite_figi character(12) NOT NULL,
    as_of_date date NOT NULL,
    high_52w numeric,
    low_52w numeric,
    high_52w_date date,
    low_52w_date date,
    pct_off_high numeric,
    pct_off_low numeric,
    input_hash text NOT NULL,
    gated boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT fact_price_extremes_pk PRIMARY KEY (composite_figi, as_of_date)
);
COMMENT ON TABLE public.fact_price_extremes IS 'Materialized 52-week (trailing 365d) high/low of the adjusted close + pct-off. Loader-written; input_hash dirty-set; gated rows held NULL. composite_figi -> securities is a SOFT reference (sym DB).';
CREATE INDEX idx_fact_price_extremes_as_of_date ON public.fact_price_extremes USING btree (as_of_date);
CREATE INDEX idx_fact_price_extremes_published ON public.fact_price_extremes USING btree (as_of_date) WHERE (NOT gated);
CREATE TRIGGER fact_price_extremes_set_updated_at BEFORE UPDATE ON public.fact_price_extremes
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===== deterministic split-adjusted view (AR-7) =====
CREATE VIEW public.v_prices_adjusted AS
SELECT
    p.composite_figi,
    p.session_date,
    p.currency_code,
    p.close AS close_raw,
    f.split_factor,
    p.close / f.split_factor AS adj_close
FROM public.prices_raw p
CROSS JOIN LATERAL (
    SELECT COALESCE(public.product(ca.value), 1) AS split_factor
    FROM public.corporate_actions ca
    WHERE ca.composite_figi = p.composite_figi
      AND ca.action_type = 'split'
      AND ca.ex_date > p.session_date
) f;
COMMENT ON VIEW public.v_prices_adjusted IS 'Deterministic split-adjusted prices derived from prices_raw + explicit split factors (AR-7). adj_close = close_raw / product(future split ratios). No stored adjusted column; factors from corporate_actions only (AR-6).';

COMMIT;
