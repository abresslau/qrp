-- Verify sym:fact_index_returns on pg
-- No-op: the objects this change created were extracted to the `indices` package+database
-- (sym:index_extract). The indices DB owns + verifies them now.
SELECT 1;
