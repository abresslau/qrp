-- Verify sym:gics_scd on pg

-- Errors if the table or any expected column is absent.
SELECT gics_id, composite_figi,
       sector_code, sector_name,
       industry_group_code, industry_group_name,
       industry_code, industry_name,
       sub_industry_code, sub_industry_name,
       source, valid_from, valid_to, created_at, updated_at
  FROM gics_scd
 WHERE FALSE;
