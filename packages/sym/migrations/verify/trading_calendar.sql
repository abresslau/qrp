-- Verify sym:trading_calendar on pg

BEGIN;

SELECT calendar_version, mic, library, library_version, content_hash,
       session_count, first_session, last_session, is_current, created_at, updated_at
  FROM trading_calendar_version
 WHERE FALSE;

SELECT calendar_version, mic, session_date, created_at
  FROM trading_calendar
 WHERE FALSE;

-- Partial-unique guard exists: at most one current version per MIC.
SELECT 1 / (CASE WHEN EXISTS (
    SELECT 1 FROM pg_indexes
     WHERE indexname = 'trading_calendar_version_current_uq'
) THEN 1 ELSE 0 END);

ROLLBACK;
