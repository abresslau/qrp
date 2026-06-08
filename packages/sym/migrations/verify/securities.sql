-- Verify sym:securities on pg

-- Errors if the table or any expected column is absent.
SELECT composite_figi, share_class_figi, status, delist_date,
       mic, currency_code, created_at, updated_at
  FROM securities
 WHERE FALSE;
