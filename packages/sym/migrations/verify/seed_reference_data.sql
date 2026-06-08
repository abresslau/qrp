-- Verify sym:seed_reference_data on pg

-- Errors if the canonical seed rows are missing.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM currency WHERE code = 'USD') THEN
        RAISE EXCEPTION 'seed_reference_data: currency seed missing';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM exchange WHERE mic = 'XNYS') THEN
        RAISE EXCEPTION 'seed_reference_data: exchange seed missing';
    END IF;
END;
$$;
