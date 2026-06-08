-- Deploy sym:exchange_figi_exch_code to pg
-- requires: seed_reference_data

-- OpenFIGI resolves a ticker by its *exchange code* (Bloomberg composite code,
-- e.g. US/LN/FP), NOT by the operating ISO MIC we store: OpenFIGI's micCode wants
-- the segment MIC (NASDAQ XNGS, not the operating XNAS), so micCode=XNAS silently
-- matches nothing. Mapping MIC -> exchCode here lets identity resolution use the
-- exchange reference table as the single source of that translation.
BEGIN;

ALTER TABLE exchange ADD COLUMN exch_code TEXT;

UPDATE exchange e
   SET exch_code = m.code
  FROM (VALUES
    ('ARCX', 'US'), ('BVMF', 'BZ'), ('XAMS', 'NA'), ('XASE', 'US'), ('XASX', 'AU'),
    ('XBOM', 'IN'), ('XBRU', 'BB'), ('XCSE', 'DC'), ('XETR', 'GR'), ('XFRA', 'GF'),
    ('XHEL', 'FH'), ('XHKG', 'HK'), ('XJSE', 'SJ'), ('XKRX', 'KS'), ('XLIS', 'PL'),
    ('XLON', 'LN'), ('XMAD', 'SM'), ('XMEX', 'MM'), ('XMIL', 'IM'), ('XNAS', 'US'),
    ('XNSE', 'IN'), ('XNYS', 'US'), ('XNZE', 'NZ'), ('XOSL', 'NO'), ('XPAR', 'FP'),
    ('XSES', 'SP'), ('XSHE', 'C2'), ('XSHG', 'C1'), ('XSTO', 'SS'), ('XSWX', 'SW'),
    ('XTAE', 'IT'), ('XTAI', 'TT'), ('XTKS', 'JP'), ('XTSE', 'CN'), ('XWAR', 'PW')
  ) AS m(mic, code)
 WHERE e.mic = m.mic;

COMMENT ON COLUMN exchange.exch_code IS 'OpenFIGI/Bloomberg composite exchange code for ticker resolution (e.g. US, LN, FP). Translates the ISO operating MIC to OpenFIGI exchCode; the operating MIC does not match OpenFIGI micCode (which expects the segment MIC).';

COMMIT;
