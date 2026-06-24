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
run. Freshness is judged against the **previous business date** (the last completed trading session,
not today's in-progress one): a dataset behind that by even one business day is "stale"
(``stale_after_days = 0``). ``cadence`` is kept for labelling (slow-cadence rows say so on the page).
"""

from __future__ import annotations

from dataclasses import dataclass

# Which package database a dataset lives in. ``sym`` is the sym package DB; the rest own their own
# database under the DB-per-package topology (resolved via ``config.package_dsn(package)``).
SYM = "sym"
RATES = "rates"
MACRO = "macro"
ALTDATA = "altdata"
COMMODITIES = "commodities"


@dataclass(frozen=True)
class Dataset:
    """One table whose recency stands in for a bucket's freshness."""

    package: str            # sym | rates | macro | altdata  → which database
    table: str              # schema-qualified where the owning DB uses a schema (rates.curve_point,
    #                         macro.observation, altdata.pageview); bare for sym's public tables
    date_column: str        # the business-date column to take max() / coverage-session over
    label: str              # human label for the page (e.g. "sym.prices_raw")
    wide: bool = False      # True → use the broadly-complete coverage session, not a plain max()
    id_column: str | None = None   # entity key for the instrument count (DISTINCT over a recent window)
    group_column: str | None = None  # subcategory key for per-group worst-lag (e.g. rates.country)
    count_label: str | None = None   # unit for the instrument count on the page (e.g. "pairs",
    #                                  "names", "series", "commodities", "indices", "curves")


@dataclass(frozen=True)
class Bucket:
    """A big-bucket job + the dataset(s) whose freshness the EOD page reports for it."""

    key: str                # stable id + Dagster job name
    label: str              # display name
    subcategory: str        # the breakdown dimension ("source" | "universe" | "country" | …)
    datasets: tuple[Dataset, ...]
    cadence: str = "daily"          # "daily" (trading sessions) | "slow" (weekly/monthly/event)
    stale_after_days: int = 0       # days behind the EXPECTED (previous) business date before
    #                                 flagged "stale". 0 ⇒ behind by even one business day is stale.
    note: str | None = None         # honest caveat shown on the row (cadence, proxy, …)
    run_options: tuple[str, ...] = ()  # small fixed launchable subcategories surfaced as one-click
    #                                    run chips on the EOD board (e.g. index_levels: yahoo/msci).
    #                                    Empty ⇒ only a whole-bucket "Run" (per-universe/country sets
    #                                    are too large to chip; run the whole bucket or use the CLI).


# The nine buckets, in rail order. The dataset chosen per bucket is the one whose recency best
# represents "did this bucket run for the latest business day".
BUCKETS: tuple[Bucket, ...] = (
    Bucket(
        "fx", "FX rates", "source",
        (Dataset(SYM, "fx_rate", "as_of_date", "sym.fx_rate",
                 id_column="quote_currency", count_label="pairs"),),
    ),
    Bucket(
        "equity_prices", "Equity prices", "universe",
        (Dataset(SYM, "prices_raw", "session_date", "sym.prices_raw",
                 wide=True, id_column="composite_figi", count_label="names"),),
    ),
    Bucket(
        "index_levels", "Index levels", "provider",
        (Dataset(SYM, "index_levels", "session_date", "sym.index_levels",
                 id_column="sym_id", count_label="indices"),),
        run_options=("yahoo", "msci"),  # yahoo = `sym indices`; msci = `sym msci-pull`
    ),
    Bucket(
        "commodities", "Commodities", "commodity",
        (Dataset(COMMODITIES, "commodities.price_daily", "as_of_date", "commodities.price_daily",
                 wide=True, id_column="commodity_code", count_label="commodities"),),
    ),
    Bucket(
        "rates", "Rates curves", "country",
        # group_column drives the per-country worst-lag; the instrument count is the number of
        # distinct curves (a composite key) over a recent window — handled specially in the gateway.
        (Dataset(RATES, "rates.curve_point", "as_of_date", "rates.curve_point",
                 group_column="country", count_label="curves"),),
        note="per-country; worst-lagging country shown",
    ),
    Bucket(
        "fundamental", "Fundamentals", "universe",
        (Dataset(SYM, "fundamentals", "as_of_date", "sym.fundamentals",
                 id_column="composite_figi", count_label="names"),),
        cadence="slow",
        note="vendor-cadence; lags the price tape by design",
    ),
    Bucket(
        "alt_data", "Alt data", "source",
        (Dataset(ALTDATA, "altdata.observation", "obs_date", "altdata.observation",
                 id_column="composite_figi", count_label="series"),),
        cadence="slow",
    ),
    Bucket(
        "macro", "Macro", "source",
        (Dataset(MACRO, "macro.observation", "obs_date", "macro.observation",
                 id_column="series_id", count_label="series"),),
        cadence="slow",
        note="monthly/quarterly series; large lag is normal",
    ),
    Bucket(
        "universe", "Universe membership", "universe",
        (Dataset(SYM, "membership_event", "recorded_at", "sym.membership_event"),),
        cadence="slow",
        note="event-log; only changes on a constituent move",
    ),
    Bucket(
        "calculations", "Calculations (returns)", "calc type",
        # Plain index-cheap max(as_of_date): fact_returns is 28 windows × figis × dates, so a
        # coverage-session count(DISTINCT) is ~28× the cost of the prices scan (12s+). Returns are
        # recomputed FROM prices, so the equity_prices bucket already carries the laggard story; the
        # last as_of_date with returns is the honest signal here.
        (Dataset(SYM, "fact_returns", "as_of_date", "sym.fact_returns"),),
        run_options=("returns", "gics", "index_returns"),
    ),
)

# Quick lookup by key.
BUCKETS_BY_KEY: dict[str, Bucket] = {b.key: b for b in BUCKETS}


# Dagster job name per bucket — a mnemonic ``<asset>_<verb>`` (the command the bucket runs), distinct
# from the bucket ``key`` (the stable internal id used for dispatch + freshness special-casing). Keeps
# the bucket jobs readable in the Dagster UI and kills the `rates` clash with `rates_uk_boe`/
# `rates_world`. Anything not listed keeps its key as the job name (calculations; commodities is the
# dedicated schedules.py job, not a generated bucket job).
JOB_NAMES: dict[str, str] = {
    "fx": "fx_load",
    "equity_prices": "equity_load",
    "index_levels": "index_load",
    "rates": "rates_load",
    "fundamental": "fundamental_load",
    "alt_data": "alt_data_load",
    "macro": "macro_load",
    "universe": "universe_load",
}


def job_name(key: str) -> str:
    """The Dagster job name for a bucket key (mnemonic where mapped, else the key itself)."""
    return JOB_NAMES.get(key, key)


def bucket_keys() -> list[str]:
    return [b.key for b in BUCKETS]
