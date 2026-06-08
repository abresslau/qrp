-- Verify sym:universe on pg

-- Errors if the table or any expected column is absent.
SELECT universe_id, name, kind, config, pit_valid_from, source_pref, created_at, updated_at
  FROM universe
 WHERE FALSE;
