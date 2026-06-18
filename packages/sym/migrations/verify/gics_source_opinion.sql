-- Verify sym:gics_source_opinion on pg

-- Errors if the table or any expected column is absent.
SELECT opinion_id, composite_figi, source,
       sector_code, sector_name,
       industry_group_code, industry_group_name,
       industry_code, industry_name,
       sub_industry_code, sub_industry_name,
       valid_from, valid_to, created_at, updated_at
  FROM gics_source_opinion
 WHERE FALSE;
