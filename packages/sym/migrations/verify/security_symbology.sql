-- Verify sym:security_symbology on pg

-- Errors if the table or any expected column is absent. The surrogate PK is
-- intentionally not named here so this verify survives the later
-- rename_symbology_pk change (symbology_id -> sym_id) under a full `sqitch verify`.
SELECT composite_figi, symbol_type, symbol_value, mic,
       country_iso, valid_from, valid_to, created_at, updated_at
  FROM security_symbology
 WHERE FALSE;
