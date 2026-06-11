-- Verify macro:series_category on pg

BEGIN;

SELECT category FROM macro.series WHERE FALSE;

ROLLBACK;
