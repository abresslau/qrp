-- Deploy sym:securities to pg
-- requires: exchange

BEGIN;

-- Security master (FR-1..FR-4). PK is the CompositeFIGI: a split/dividend hits
-- one class, so factors key on composite_figi; share_class_figi groups classes
-- for analytics only (1-to-many, nullable). Soft-delete only -- a delisted name
-- keeps its row with status='delisted' (survivorship-bias constraint); rows are
-- NEVER physically deleted.
CREATE TABLE securities (
    composite_figi    CHAR(12)    PRIMARY KEY,
    share_class_figi  CHAR(12),
    status            TEXT        NOT NULL DEFAULT 'active',
    delist_date       DATE,
    mic               CHAR(4)     NOT NULL,
    currency_code     CHAR(3)     NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT securities_composite_figi_chk   CHECK (composite_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT securities_share_class_figi_chk CHECK (share_class_figi IS NULL OR share_class_figi ~ '^[A-Z0-9]{12}$'),
    CONSTRAINT securities_status_chk           CHECK (status IN ('active', 'delisted', 'suspended')),
    CONSTRAINT securities_active_no_delist_chk CHECK (status <> 'active' OR delist_date IS NULL),
    CONSTRAINT securities_exchange_fk          FOREIGN KEY (mic) REFERENCES exchange (mic),
    CONSTRAINT securities_currency_fk          FOREIGN KEY (currency_code) REFERENCES currency (code)
);

CREATE INDEX idx_securities_share_class_figi ON securities (share_class_figi);
CREATE INDEX idx_securities_mic              ON securities (mic);
CREATE INDEX idx_securities_currency_code    ON securities (currency_code);
CREATE INDEX idx_securities_status           ON securities (status);

CREATE TRIGGER securities_set_updated_at
    BEFORE UPDATE ON securities
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Public schema contract (NFR-4). These column names/types are consumed by
-- downstream warehouse modules; breaking changes require a new migration.
COMMENT ON TABLE  securities                  IS 'Security master keyed on CompositeFIGI. Public contract for downstream modules (NFR-4). Soft-delete only.';
COMMENT ON COLUMN securities.composite_figi   IS 'CompositeFIGI (12-char). Stable primary identity; factors/prices key on this.';
COMMENT ON COLUMN securities.share_class_figi IS 'ShareClassFIGI grouping multiple classes; analytics only, nullable.';
COMMENT ON COLUMN securities.status           IS 'Lifecycle state: active | delisted | suspended. Never filter silently on delisted (survivorship).';
COMMENT ON COLUMN securities.delist_date      IS 'Delisting date; NULL while active.';
COMMENT ON COLUMN securities.mic              IS 'Primary listing exchange (ISO-10383 MIC), FK to exchange.';
COMMENT ON COLUMN securities.currency_code    IS 'Trading currency (ISO-4217), FK to currency. No implicit USD.';

COMMIT;
