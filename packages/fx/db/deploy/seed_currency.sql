-- Deploy fx:seed_currency to pg
-- requires: fx_schema

BEGIN;

-- Seed the fx-DB currency reference so a FRESH `deploy_all` of the fx database is functional:
-- fx_rate FKs fx.currency, and `_default_currencies` (SELECT code FROM fx.currency) drives the
-- default `fx load` set — an empty currency table makes the whole fx DB non-functional (every
-- insert FK-fails / nothing loads). Mirrors sym's seed_reference_data currency list. Idempotent
-- (ON CONFLICT DO NOTHING) so it is a no-op on an already-populated fx DB.

INSERT INTO fx.currency (code, name) VALUES
    ('USD', 'US Dollar'),
    ('EUR', 'Euro'),
    ('GBP', 'Pound Sterling'),
    ('JPY', 'Yen'),
    ('CHF', 'Swiss Franc'),
    ('CAD', 'Canadian Dollar'),
    ('AUD', 'Australian Dollar'),
    ('NZD', 'New Zealand Dollar'),
    ('HKD', 'Hong Kong Dollar'),
    ('CNY', 'Yuan Renminbi'),
    ('SGD', 'Singapore Dollar'),
    ('SEK', 'Swedish Krona'),
    ('NOK', 'Norwegian Krone'),
    ('DKK', 'Danish Krone'),
    ('KRW', 'Won'),
    ('TWD', 'New Taiwan Dollar'),
    ('INR', 'Indian Rupee'),
    ('BRL', 'Brazilian Real'),
    ('MXN', 'Mexican Peso'),
    ('ZAR', 'Rand'),
    ('ILS', 'New Israeli Sheqel'),
    ('PLN', 'Zloty'),
    ('THB', 'Baht'),
    ('IDR', 'Rupiah'),
    ('MYR', 'Malaysian Ringgit'),
    ('PHP', 'Philippine Peso'),
    ('TRY', 'Turkish Lira'),
    ('AED', 'UAE Dirham'),
    ('SAR', 'Saudi Riyal'),
    ('CZK', 'Czech Koruna'),
    ('HUF', 'Forint'),
    ('CLP', 'Chilean Peso')
ON CONFLICT (code) DO NOTHING;

COMMIT;
