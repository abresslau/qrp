-- Deploy sym:date_naming_convention to pg
-- requires: fundamentals_date_column

BEGIN;

-- Standardize DATE column names for meaning + cross-engine portability
-- (see docs/data-conventions.md). Rules:
--   * point-in-time observation date  -> as_of_date  (canonical, was asof/as_of/date)
--   * every other DATE column ends in -> _date
--   * sanctioned exceptions (kept):   -> valid_from / valid_to / pit_valid_from
--                                        (SCD valid-time idiom; half-open [from, to))
-- No column is a bare type/reserved word; nothing is quoted -> clean Postgres ->
-- Snowflake/BigQuery case-folding.

-- as_of_date: collapse the three spellings of the point-in-time observation date.
ALTER TABLE fact_returns           RENAME COLUMN asof  TO as_of_date;
ALTER INDEX  idx_fact_returns_asof_window RENAME TO idx_fact_returns_as_of_date_window;
ALTER TABLE fundamentals           RENAME COLUMN "date" TO as_of_date;
ALTER INDEX  idx_fundamentals_date_mktcap RENAME TO idx_fundamentals_as_of_date_mktcap;
ALTER TABLE universe_accuracy_check RENAME COLUMN as_of TO as_of_date;

-- _date suffix for the remaining bare DATE columns.
ALTER TABLE pipeline_backfill_progress RENAME COLUMN floor_reached TO floor_reached_date;
ALTER TABLE membership_proposal        RENAME COLUMN first_seen TO first_seen_date;
ALTER TABLE membership_proposal        RENAME COLUMN last_seen  TO last_seen_date;
ALTER TABLE trading_calendar_version   RENAME COLUMN first_session TO first_session_date;
ALTER TABLE trading_calendar_version   RENAME COLUMN last_session  TO last_session_date;

COMMIT;
