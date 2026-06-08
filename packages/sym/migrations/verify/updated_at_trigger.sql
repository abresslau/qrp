-- Verify sym:updated_at_trigger on pg

-- Errors if the function is absent.
SELECT 'set_updated_at()'::regprocedure;
