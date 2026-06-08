-- Verify sym:instrument on pg

SELECT sym_id, kind, name, currency_code, status, created_at, updated_at
  FROM instrument WHERE FALSE;
SELECT sym_id, source, value, created_at FROM instrument_xref WHERE FALSE;
