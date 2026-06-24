-- Revert fx:seed_currency from pg
-- Intentional no-op: the seeded rows are reference data with no independent lifecycle, and
-- fx.currency is FK'd by fx.fx_rate — a DELETE here would fail while rates exist. The rows are
-- removed when the fx_schema revert drops fx.currency (which runs after this in reverse order).

BEGIN;

SELECT 1;

COMMIT;
