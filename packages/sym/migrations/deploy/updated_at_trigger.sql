-- Deploy sym:updated_at_trigger to pg

BEGIN;

-- Shared trigger used by every table to satisfy NFR-5 (universal updated_at).
-- Reference and fact tables attach a BEFORE UPDATE row trigger to this function.
CREATE FUNCTION set_updated_at() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

COMMIT;
