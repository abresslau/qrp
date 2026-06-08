-- Verify sym:currency on pg

-- Errors if the table or any expected column is absent.
SELECT code, name, created_at, updated_at
  FROM currency
 WHERE FALSE;
