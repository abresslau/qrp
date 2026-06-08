-- Verify sym:universe_member_resolution on pg

-- Errors if the table or any expected column is absent.
SELECT universe_id, raw_identifier, composite_figi, share_class_figi,
       resolution_status, detail, resolved_at
  FROM universe_member_resolution
 WHERE FALSE;
