-- Verify sym:membership_event on pg

-- Errors if the table or any expected column is absent.
SELECT event_id, universe_id, raw_identifier, change, effective_date,
       effective_date_precision, source, provenance, recorded_at
  FROM membership_event
 WHERE FALSE;
