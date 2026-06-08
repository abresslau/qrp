-- Revert sym:date_naming_convention from pg

BEGIN;

ALTER TABLE trading_calendar_version   RENAME COLUMN last_session_date  TO last_session;
ALTER TABLE trading_calendar_version   RENAME COLUMN first_session_date TO first_session;
ALTER TABLE membership_proposal        RENAME COLUMN last_seen_date  TO last_seen;
ALTER TABLE membership_proposal        RENAME COLUMN first_seen_date TO first_seen;
ALTER TABLE pipeline_backfill_progress RENAME COLUMN floor_reached_date TO floor_reached;

ALTER TABLE universe_accuracy_check RENAME COLUMN as_of_date TO as_of;
ALTER INDEX  idx_fundamentals_as_of_date_mktcap RENAME TO idx_fundamentals_date_mktcap;
ALTER TABLE fundamentals           RENAME COLUMN as_of_date TO "date";
ALTER INDEX  idx_fact_returns_as_of_date_window RENAME TO idx_fact_returns_asof_window;
ALTER TABLE fact_returns           RENAME COLUMN as_of_date TO asof;

COMMIT;
