-- Verify sym:rename_symbology_pk on pg

-- Errors if the renamed PK column is absent.
SELECT sym_id
  FROM security_symbology
 WHERE FALSE;
