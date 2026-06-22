-- Deploy sym:exchange_bbg_exchange_code to pg
-- requires: exchange_figi_exch_code

-- Bloomberg PRIMARY-VENUE exchange code: the 2-char local-venue code (e.g. Xetra GY, NYSE UN,
-- Nasdaq UW), DISTINCT from the country composite in exch_code (Germany GR, US US). The venue
-- code is the only Bloomberg field that separates two same-composite listings of one ticker
-- (NYSE UN vs Nasdaq UW are both composite US). Renders the Bloomberg "exchange" qualified
-- ticker ("ADS GY"); the composite/region code lives in exch_code, the FactSet region is
-- country_iso. Derived display only — qualified tickers are never stored.
BEGIN;

ALTER TABLE exchange ADD COLUMN IF NOT EXISTS bbg_exchange_code TEXT;

UPDATE exchange e
   SET bbg_exchange_code = m.code
  FROM (VALUES
    ('XNYS', 'UN'), ('XNAS', 'UW'), ('XETR', 'GY'), ('XFRA', 'GF'), ('XLON', 'LN'),
    ('XPAR', 'FP'), ('XAMS', 'NA'), ('XBRU', 'BB'), ('XMIL', 'IM'), ('XMAD', 'SM'),
    ('XSWX', 'SW'), ('XSTO', 'SS'), ('XOSL', 'NO'), ('XCSE', 'DC'), ('XHEL', 'FH'),
    ('XLIS', 'PL'), ('XWAR', 'PW'), ('XHKG', 'HK'), ('XTKS', 'JT'), ('XKRX', 'KS'),
    ('XTAI', 'TT'), ('XSES', 'SP'), ('XASX', 'AT'), ('XTSE', 'CT'), ('XBOM', 'IB'),
    ('XNSE', 'IS'), ('XMEX', 'MM'), ('XNZE', 'NZ'), ('XJSE', 'SJ'), ('XTAE', 'IT'),
    ('BVMF', 'BZ')
    -- Deliberately NOT seeded (venue code unconfirmed — the null-safe display falls back to the
    -- region/bare ticker rather than show a guessed code): XASE (NYSE American), ARCX (NYSE Arca),
    -- XSHG / XSHE (Shanghai / Shenzhen segments — exch_code already carries C1 / C2 for the region).
  ) AS m(mic, code)
 WHERE e.mic = m.mic;

COMMENT ON COLUMN exchange.bbg_exchange_code IS 'Bloomberg primary-venue exchange code (e.g. GY Xetra, UN NYSE, UW Nasdaq) — the local-venue 2-char, distinct from the country composite in exch_code. Renders the Bloomberg "exchange" qualified ticker (TICKER + code). NULL where the venue code is unconfirmed; display falls back to the region/bare ticker.';

COMMIT;
