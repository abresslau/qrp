-- Verify sym:prices_review_per_flag on pg

SELECT 1/count(*) FROM pg_constraint
 WHERE conname = 'prices_review_pk'
   AND conrelid = 'prices_review'::regclass
   AND array_length(conkey, 1) = 3;
