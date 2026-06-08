-- Verify sym:exchange_figi_exch_code on pg

BEGIN;

-- Column exists.
SELECT exch_code FROM exchange WHERE FALSE;

-- The exchanges used by the seed universe all carry a code (errors if any is NULL).
SELECT 1 / (CASE WHEN NOT EXISTS (
    SELECT 1 FROM exchange
     WHERE mic IN ('XNYS', 'XNAS', 'XLON', 'XPAR', 'XETR', 'XSWX', 'XTKS', 'XHKG')
       AND exch_code IS NULL
) THEN 1 ELSE 0 END);

ROLLBACK;
