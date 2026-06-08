-- Verify sym:universe_membership on pg

-- Errors if the table or any expected column is absent.
SELECT universe_id, composite_figi, raw_identifier, valid_from, valid_to, source
  FROM universe_membership
 WHERE FALSE;
