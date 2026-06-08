-- Verify sym:date_naming_convention on pg

SELECT as_of_date FROM fact_returns WHERE FALSE;
SELECT as_of_date FROM fundamentals WHERE FALSE;
SELECT as_of_date FROM universe_accuracy_check WHERE FALSE;
SELECT floor_reached_date FROM pipeline_backfill_progress WHERE FALSE;
SELECT first_seen_date, last_seen_date FROM membership_proposal WHERE FALSE;
SELECT first_session_date, last_session_date FROM trading_calendar_version WHERE FALSE;
