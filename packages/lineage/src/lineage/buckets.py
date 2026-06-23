"""The QRP data-pipeline **bucket taxonomy** — the single source of truth shared by

* the **Dagster bucket jobs** (trigger/backfill per bucket × subcategory × date), and
* the **Data Monitor › EOD** page (per-bucket freshness: expected vs actual + last run).

Keeping both on ONE definition means the page can never drift from the jobs. This module is
deliberately **dependency-light** — it imports only the stdlib (NO ``dagster``, NO DB driver) so
the FastAPI gateway can import it without pulling Dagster into the API process.

Each bucket names the dataset(s) whose freshness represents it, the package/database that owns
them, the date column to read, and how to read "latest" honestly (a plain ``max`` for a
point-in-time series; the broadly-complete *coverage session* for a wide cross-sectional table so
one fresh sub-universe can't mask a stale rest — the documented max-masks-laggards trap). The
``job`` name is both the Dagster job (Part A) and the key the EOD page uses to look up the latest
run. Cadence + ``stale_after_days`` make the ok/stale verdict honest per dataset (a monthly macro
series is not "stale" at 5 days).
"""

from __future__ import annotations

from dataclasses import dataclass

# Which package database a dataset lives in. ``sym`` is the sym package DB; the rest own their own
# database under the DB-per-package topology (resolved via ``config.package_dsn(package)``).
SYM = "sym"
RATES = "rates"
MACRO = "macro"
ALTDATA = "altdata"


@dataclass(frozen=True)
class Dataset:
    """One table whose recency stands in for a bucket's freshness."""

    package: str            # sym | rates | macro | altdata  → which database
    table: str              # schema-qualified where the owning DB uses a schema (rates.curve_point,
    #                         macro.observation, altdata.pageview); bare for sym's public tables
    date_column: str        # the business-date column to take max() / coverage-session over
    label: str              # human label for the page (e.g. "sym.prices_raw")
    wide: bool = False      # True → use the broadly-complete coverage session, not a plain max()
    id_column: str | None = None   # entity key for the coverage-session count (wide datasets)
    group_column: str | None = None  # subcategory key for per-group worst-lag (e.g. rates.country)


@dataclass(frozen=True)
class Bucket:
    """A big-bucket job + the dataset(s) whose freshness the EOD page reports for it."""

    key: str                # stable id + Dagster job name
    label: str              # display name
    subcategory: str        # the breakdown dimension ("source" | "universe" | "country" | …)
    datasets: tuple[Dataset, ...]
    cadence: str = "daily"          # "daily" (trading sessions) | "slow" (weekly/monthly/event)
    stale_after_days: int = 4       # days behind the expected session before flagged "stale"
    note: str | None = None         # honest caveat shown on the row (cadence, proxy, …)


# The nine buckets, in rail order. The dataset chosen per bucket is the one whose recency best
# represents "did this bucket run for the latest business day".
BUCKETS: tuple[Bucket, ...] = (
    Bucket(
        "fx", "FX rates", "source",
        (Dataset(SYM, "fx_rate", "as_of_date", "sym.fx_rate"),),
    ),
    Bucket(
        "equity_prices", "Equity prices", "universe",
        (Dataset(SYM, "prices_raw", "session_date", "sym.prices_raw",
                 wide=True, id_column="composite_figi"),),
    ),
    Bucket(
        "index_levels", "Index levels", "provider",
        (Dataset(SYM, "index_levels", "session_date", "sym.index_levels"),),
    ),
    Bucket(
        "rates", "Rates curves", "country",
        (Dataset(RATES, "rates.curve_point", "as_of_date", "rates.curve_point",
                 group_column="country"),),
        note="per-country; worst-lagging country shown",
    ),
    Bucket(
        "fundamental", "Fundamentals", "universe",
        (Dataset(SYM, "fundamentals", "as_of_date", "sym.fundamentals"),),
        cadence="slow", stale_after_days=14,
        note="vendor-cadence; lags the price tape by design",
    ),
    Bucket(
        "alt_data", "Alt data", "source",
        (Dataset(ALTDATA, "altdata.observation", "obs_date", "altdata.observation"),),
        cadence="slow", stale_after_days=8,
    ),
    Bucket(
        "macro", "Macro", "source",
        (Dataset(MACRO, "macro.observation", "obs_date", "macro.observation"),),
        cadence="slow", stale_after_days=45,
        note="monthly/quarterly series; large lag is normal",
    ),
    Bucket(
        "universe", "Universe membership", "universe",
        (Dataset(SYM, "membership_event", "recorded_at", "sym.membership_event"),),
        cadence="slow", stale_after_days=31,
        note="event-log; only changes on a constituent move",
    ),
    Bucket(
        "calculations", "Calculations (returns)", "calc type",
        # Plain index-cheap max(as_of_date): fact_returns is 28 windows × figis × dates, so a
        # coverage-session count(DISTINCT) is ~28× the cost of the prices scan (12s+). Returns are
        # recomputed FROM prices, so the equity_prices bucket already carries the laggard story; the
        # last as_of_date with returns is the honest signal here.
        (Dataset(SYM, "fact_returns", "as_of_date", "sym.fact_returns"),),
    ),
)

# Quick lookup by key (also the Dagster job name set Part A registers).
BUCKETS_BY_KEY: dict[str, Bucket] = {b.key: b for b in BUCKETS}


def bucket_keys() -> list[str]:
    return [b.key for b in BUCKETS]
