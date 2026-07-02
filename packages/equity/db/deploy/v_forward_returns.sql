-- Deploy equity:v_forward_returns to pg

BEGIN;

-- Forward (future-horizon) returns for the rolling windows, for ML TARGETS. A forward return over
-- horizon H at date t is BY DEFINITION the trailing-H return observed at the session H forward of t:
--   fwd_return(figi, t, H) == trailing_return(first session >= t+H, H)
-- so this is a pure RE-INDEXING of fact_returns (no new price math): the LATERAL picks the first
-- as_of_date >= t + H_interval for the SAME (figi, window), whose pr/tr is the forward return from t.
-- Rows whose forward endpoint has not yet occurred (the trailing tail) are simply ABSENT (the LATERAL
-- returns nothing), so unrealized labels are never fabricated. Restricted to the rolling horizons
-- (1W/1M/3M/6M/9M/1Y) — calendar-anchored (WTD..YTD) and multi-year-CAGR windows are not meaningful
-- forward labels.
--
-- ML DISCIPLINE: fwd_pr/fwd_tr are TARGETS ONLY — never use them as features. They embed future
-- information relative to as_of_date. Drop rows with a NULL fwd (gated forward endpoint) and the
-- unrealized tail (absent) from any training set. Features must be strictly as-of <= as_of_date.
CREATE OR REPLACE VIEW equity.v_forward_returns AS
SELECT
    f.composite_figi,
    f.window_id,
    f.as_of_date,
    fwd.as_of_date AS fwd_end_date,
    fwd.pr         AS fwd_pr,
    fwd.tr         AS fwd_tr
FROM equity.fact_returns f
CROSS JOIN LATERAL (
    -- the horizon date t+H, computed once (the trailing windows are calendar-anchored then
    -- session-snapped, so a calendar interval is the right forward offset; the first session
    -- >= t+H is at most ~1 session off the exact trailing-H endpoint — the AC-4 boundary class).
    SELECT (f.as_of_date + CASE f.window_id
        WHEN 6  THEN interval '7 days'    -- 1W
        WHEN 7  THEN interval '1 month'   -- 1M
        WHEN 8  THEN interval '3 months'  -- 3M
        WHEN 9  THEN interval '6 months'  -- 6M
        WHEN 10 THEN interval '9 months'  -- 9M
        WHEN 11 THEN interval '1 year'    -- 1Y
      END)::date AS h
) hz
JOIN LATERAL (
    SELECT g.as_of_date, g.pr, g.tr
    FROM equity.fact_returns g
    WHERE g.composite_figi = f.composite_figi
      AND g.window_id = f.window_id
      AND g.as_of_date >= hz.h
      -- BOUND: the forward endpoint must be within ~2 weeks of t+H. Without this, a data gap after
      -- t+H (suspension / delist-then-relist) would let the first later row — arbitrarily far in the
      -- future — masquerade as the forward return, silently mislabeling an ML target. Beyond the
      -- bound the row is ABSENT (unrealized), never fabricated.
      AND g.as_of_date <= hz.h + interval '14 days'
    ORDER BY g.as_of_date
    LIMIT 1
) fwd ON true
WHERE f.window_id IN (6, 7, 8, 9, 10, 11);

COMMENT ON VIEW equity.v_forward_returns IS
    'Forward (future-horizon) returns for the rolling windows (1W/1M/3M/6M/9M/1Y), as a re-index of '
    'fact_returns: fwd = trailing-H return at the first session >= as_of_date + H. ML TARGETS ONLY '
    '(embed future info; never use as features); unrealized tail is absent, gated endpoint -> NULL.';

COMMIT;
