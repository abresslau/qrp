# Public schema contract

This document defines the **stable, public** database surface that downstream
warehouse modules may depend on (NFR-4). Column names, types, and primary keys
listed here are a contract: a breaking change requires a new Sqitch migration
and a versioned schema change — never an in-place edit. The canonical source is
always the migrations under `migrations/`; this file summarizes the contract.

## `securities` (Story 1.3, FR-1..FR-4)

Security master keyed on CompositeFIGI. Soft-delete only — a delisted name keeps
its row (survivorship-bias constraint); rows are never physically deleted.

| Column | Type | Notes |
| --- | --- | --- |
| `composite_figi` | `CHAR(12)` PK | Stable primary identity. Factors and prices key on this. |
| `share_class_figi` | `CHAR(12)` null | Groups multiple share classes; analytics only. |
| `status` | `TEXT` | `active` \| `delisted` \| `suspended`. Do not silently filter `delisted` (survivorship). |
| `delist_date` | `DATE` null | Delisting date; NULL while `active`. |
| `mic` | `CHAR(4)` | Primary listing exchange (ISO-10383 MIC), FK → `exchange`. |
| `currency_code` | `CHAR(3)` | Trading currency (ISO-4217), FK → `currency`. No implicit USD. |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | NFR-5; `updated_at` maintained by trigger. |

**Identity guarantee:** a lookup by any supported identifier for a given
effective date resolves to exactly one `composite_figi` (see
`security_symbology`).

## `security_symbology` (Story 1.3, FR-2, FR-3)

Effective-dated identifiers resolving to a CompositeFIGI. Narrow shape: one row
per `(symbol_type, symbol_value)` with a validity interval.

| Column | Type | Notes |
| --- | --- | --- |
| `sym_id` | `BIGINT` PK (identity) | Surrogate key. |
| `composite_figi` | `CHAR(12)` | FK → `securities`. |
| `symbol_type` | `TEXT` | `ticker` \| `isin` \| `cusip` \| `sedol` \| `local_code`. |
| `symbol_value` | `TEXT` | The identifier value. |
| `mic` | `CHAR(4)` null | Listing exchange for exchange-scoped symbols; NULL for global ids. |
| `country_iso` | `CHAR(2)` null | ISO-3166-1 alpha-2 of the listing. |
| `valid_from` | `DATE` | Inclusive lower bound of validity. |
| `valid_to` | `DATE` null | Exclusive upper bound; NULL = currently effective. |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | NFR-5. |

**Temporal uniqueness:** an `EXCLUDE` constraint forbids the same
`(symbol_type, symbol_value, mic)` from resolving over overlapping time — this is
what guarantees the one-identifier→one-FIGI lookup above.

### Resolution query (any identifier → CompositeFIGI at an effective date)

```sql
SELECT composite_figi
  FROM security_symbology
 WHERE symbol_type  = :symbol_type      -- e.g. 'isin'
   AND symbol_value = :symbol_value
   AND (:mic IS NULL OR mic = :mic)      -- supply MIC for ticker lookups
   AND valid_from <= :as_of
   AND (valid_to IS NULL OR valid_to > :as_of);
```
