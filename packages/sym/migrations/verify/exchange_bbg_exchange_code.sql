-- Verify sym:exchange_bbg_exchange_code on pg

BEGIN;

-- Column exists.
SELECT bbg_exchange_code FROM exchange WHERE FALSE;

-- The major venues used by the seed universe all carry a code (errors if any is NULL).
SELECT 1 / (CASE WHEN NOT EXISTS (
    SELECT 1 FROM exchange
     WHERE mic IN ('XNYS', 'XNAS', 'XLON', 'XPAR', 'XETR', 'XTKS', 'XHKG')
       AND bbg_exchange_code IS NULL
) THEN 1 ELSE 0 END);

ROLLBACK;
