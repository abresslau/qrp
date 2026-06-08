-- Deploy sym:seed_reference_data to pg
-- requires: exchange

-- Idempotent population of the reference tables. Currencies cover the
-- actively-traded global equity markets; exchanges cover the major operating
-- MICs (Story 1.5 reconciles this against the finalized seed universe and adds
-- any missing MIC). Re-deploy is safe (UPSERT); updated_at is refreshed.

BEGIN;

INSERT INTO currency (code, name) VALUES
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
ON CONFLICT (code) DO UPDATE
    SET name = EXCLUDED.name,
        updated_at = now();

INSERT INTO exchange (mic, name, country, country_iso, timezone, currency_code) VALUES
    ('XNYS', 'New York Stock Exchange',            'United States',  'US', 'America/New_York',    'USD'),
    ('XNAS', 'Nasdaq Stock Market',                'United States',  'US', 'America/New_York',    'USD'),
    ('ARCX', 'NYSE Arca',                          'United States',  'US', 'America/New_York',    'USD'),
    ('XASE', 'NYSE American',                      'United States',  'US', 'America/New_York',    'USD'),
    ('XTSE', 'Toronto Stock Exchange',             'Canada',         'CA', 'America/Toronto',     'CAD'),
    ('XLON', 'London Stock Exchange',              'United Kingdom', 'GB', 'Europe/London',       'GBP'),
    ('XETR', 'Deutsche Boerse XETRA',              'Germany',        'DE', 'Europe/Berlin',       'EUR'),
    ('XFRA', 'Frankfurt Stock Exchange',           'Germany',        'DE', 'Europe/Berlin',       'EUR'),
    ('XPAR', 'Euronext Paris',                     'France',         'FR', 'Europe/Paris',        'EUR'),
    ('XAMS', 'Euronext Amsterdam',                 'Netherlands',    'NL', 'Europe/Amsterdam',    'EUR'),
    ('XBRU', 'Euronext Brussels',                  'Belgium',        'BE', 'Europe/Brussels',     'EUR'),
    ('XLIS', 'Euronext Lisbon',                    'Portugal',       'PT', 'Europe/Lisbon',       'EUR'),
    ('XMIL', 'Borsa Italiana',                     'Italy',          'IT', 'Europe/Rome',         'EUR'),
    ('XMAD', 'Bolsa de Madrid',                    'Spain',          'ES', 'Europe/Madrid',       'EUR'),
    ('XSWX', 'SIX Swiss Exchange',                 'Switzerland',    'CH', 'Europe/Zurich',       'CHF'),
    ('XSTO', 'Nasdaq Stockholm',                   'Sweden',         'SE', 'Europe/Stockholm',    'SEK'),
    ('XHEL', 'Nasdaq Helsinki',                    'Finland',        'FI', 'Europe/Helsinki',     'EUR'),
    ('XCSE', 'Nasdaq Copenhagen',                  'Denmark',        'DK', 'Europe/Copenhagen',   'DKK'),
    ('XOSL', 'Oslo Bors',                          'Norway',         'NO', 'Europe/Oslo',         'NOK'),
    ('XTKS', 'Tokyo Stock Exchange',               'Japan',          'JP', 'Asia/Tokyo',          'JPY'),
    ('XHKG', 'Hong Kong Stock Exchange',           'Hong Kong',      'HK', 'Asia/Hong_Kong',      'HKD'),
    ('XSHG', 'Shanghai Stock Exchange',            'China',          'CN', 'Asia/Shanghai',       'CNY'),
    ('XSHE', 'Shenzhen Stock Exchange',            'China',          'CN', 'Asia/Shanghai',       'CNY'),
    ('XSES', 'Singapore Exchange',                 'Singapore',      'SG', 'Asia/Singapore',      'SGD'),
    ('XKRX', 'Korea Exchange',                     'South Korea',    'KR', 'Asia/Seoul',          'KRW'),
    ('XTAI', 'Taiwan Stock Exchange',              'Taiwan',         'TW', 'Asia/Taipei',         'TWD'),
    ('XBOM', 'BSE Ltd',                            'India',          'IN', 'Asia/Kolkata',        'INR'),
    ('XNSE', 'National Stock Exchange of India',   'India',          'IN', 'Asia/Kolkata',        'INR'),
    ('XASX', 'Australian Securities Exchange',     'Australia',      'AU', 'Australia/Sydney',    'AUD'),
    ('XNZE', 'NZX',                                'New Zealand',    'NZ', 'Pacific/Auckland',    'NZD'),
    ('BVMF', 'B3 - Brasil Bolsa Balcao',           'Brazil',         'BR', 'America/Sao_Paulo',   'BRL'),
    ('XMEX', 'Bolsa Mexicana de Valores',          'Mexico',         'MX', 'America/Mexico_City', 'MXN'),
    ('XJSE', 'Johannesburg Stock Exchange',        'South Africa',   'ZA', 'Africa/Johannesburg', 'ZAR'),
    ('XTAE', 'Tel Aviv Stock Exchange',            'Israel',         'IL', 'Asia/Jerusalem',      'ILS'),
    ('XWAR', 'Warsaw Stock Exchange',              'Poland',         'PL', 'Europe/Warsaw',       'PLN')
ON CONFLICT (mic) DO UPDATE
    SET name = EXCLUDED.name,
        country = EXCLUDED.country,
        country_iso = EXCLUDED.country_iso,
        timezone = EXCLUDED.timezone,
        currency_code = EXCLUDED.currency_code,
        updated_at = now();

COMMIT;
