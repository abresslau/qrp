-- Verify sym:exchange on pg

-- Errors if the table or any expected column is absent.
SELECT mic, name, country, country_iso, timezone, currency_code, created_at, updated_at
  FROM exchange
 WHERE FALSE;
