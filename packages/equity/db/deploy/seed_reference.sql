-- Deploy equity:seed_reference to pg
-- requires: equity_schema

-- Seed the equity-DB reference tables so a FRESH `deploy_all` of the equity database is functional:
-- prices_raw/corporate_actions FK currency, fact_returns FKs return_window. Idempotent
-- (ON CONFLICT DO NOTHING) so it is a no-op on an already-populated equity DB. Mirrors sym's
-- seed_reference_data currency list + the 28 canonical return windows (FR-9).

BEGIN;

INSERT INTO public.currency (code, name) VALUES
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

INSERT INTO public.return_window (window_id, code, label, kind, annualized) VALUES
    (1, '1D', '1 day', 'calendar', false),
    (2, 'WTD', 'Week to date', 'calendar', false),
    (3, 'MTD', 'Month to date', 'calendar', false),
    (4, 'QTD', 'Quarter to date', 'calendar', false),
    (5, 'YTD', 'Year to date', 'calendar', false),
    (6, '1W', '1 week', 'trailing', false),
    (7, '1M', '1 month', 'trailing', false),
    (8, '3M', '3 months', 'trailing', false),
    (9, '6M', '6 months', 'trailing', false),
    (10, '9M', '9 months', 'trailing', false),
    (11, '1Y', '1 year', 'trailing', false),
    (12, '2Y_ANN', '2 years annualized', 'trailing', true),
    (13, '3Y_ANN', '3 years annualized', 'trailing', true),
    (14, '5Y_ANN', '5 years annualized', 'trailing', true),
    (15, '10Y_ANN', '10 years annualized', 'trailing', true),
    (16, '20Y_ANN', '20 years annualized', 'trailing', true),
    (17, '30Y_ANN', '30 years annualized', 'trailing', true),
    (18, 'SI_ANN', 'Since inception annualized', 'inception', true),
    (19, '5D', '5 trading days', 'session', false),
    (20, '10D', '10 trading days', 'session', false),
    (21, '2Y', '2 years', 'trailing', false),
    (22, '3Y', '3 years', 'trailing', false),
    (23, '5Y', '5 years', 'trailing', false),
    (24, '10Y', '10 years', 'trailing', false),
    (25, '20Y', '20 years', 'trailing', false),
    (26, '30Y', '30 years', 'trailing', false),
    (27, 'SI', 'Since inception', 'inception', false),
    (28, 'PQ', 'Last completed quarter', 'period', false)
ON CONFLICT (window_id) DO NOTHING;

COMMIT;
