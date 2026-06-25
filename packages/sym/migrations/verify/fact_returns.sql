-- Verify sym:fact_returns on pg
-- No-op: the objects this change created were extracted to the `equity` package+database
-- (sym:equity_extract). The equity DB owns + verifies them now.
SELECT 1;
