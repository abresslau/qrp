-- Verify sym:fx_views_precedence on pg
-- NOTE: FX was extracted into the `fx` package + database (migration sym:fx_extract drops these
-- objects from the sym DB). This create-migration's objects no longer exist in sym, so the
-- existence check is intentionally a no-op — `fx_extract` is the authoritative end-state here.
SELECT 1;
