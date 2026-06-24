-- Verify sym:universe_accuracy_check on pg
-- NOTE: the universe/membership subsystem was extracted into the `universe` package + database
-- (migration sym:universe_extract drops these tables from the sym DB). This migration's objects no
-- longer exist in sym, so the existence check is intentionally a no-op — `universe_extract` is the
-- authoritative end-state.
SELECT 1;
