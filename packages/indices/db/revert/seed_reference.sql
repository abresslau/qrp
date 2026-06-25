-- Revert indices:seed_reference from pg
-- Remove the seeded return_window rows (reference seed; safe to clear on revert).

BEGIN;

DELETE FROM indices.return_window WHERE window_id BETWEEN 1 AND 28;

COMMIT;
