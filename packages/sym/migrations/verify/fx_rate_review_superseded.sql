-- Verify sym:fx_rate_review_superseded on pg

SELECT 1/count(*) FROM pg_constraint
 WHERE conname = 'fx_rate_review_resolution_chk'
   AND conrelid = 'fx_rate_review'::regclass
   AND pg_get_constraintdef(oid) LIKE '%superseded%';
