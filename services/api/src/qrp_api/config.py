"""Platform + database configuration for the QRP gateway.

Branding + the module registry come from ``platform.toml``. Database credentials are
**instance-level, not package-level**: the shared Postgres instance is configured with the
libpq-standard ``PG*`` env vars (``PGHOST``/``PGPORT``/``PGUSER``/``PGPASSWORD``), and each
package only names its own database (``dbname = <package>``). sym is just another package whose
database is named ``sym``. Override any package's whole DSN with ``<PKG>_DATABASE_URL`` (or its
name with ``<PKG>_DB_NAME``) to move it to its own host later.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

# Shared-instance defaults (the DATABASE name is per-package, so it isn't here).
_INSTANCE_DEFAULTS = {"host": "localhost", "port": "5432", "user": "postgres"}


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "platform.toml").is_file():
            return parent
    raise FileNotFoundError("platform.toml not found above the gateway package")


@lru_cache
def platform_config() -> dict:
    return tomllib.loads((_repo_root() / "platform.toml").read_text(encoding="utf-8"))


def platform_name() -> str:
    return platform_config().get("platform", {}).get("name", "QRP")


def modules() -> list[dict]:
    return platform_config().get("modules", [])


def enabled_modules() -> list[dict]:
    return [m for m in modules() if m.get("enabled")]


@lru_cache
def _load_dotenv() -> None:
    path = _repo_root() / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def sym_project_dir() -> Path:
    """Directory of the sym CODE checkout (where `uv run sym <op>` executes for Operate jobs).

    This is a code path, not a credential. Override with SYM_PROJECT_DIR; default is a sibling
    `sym` checkout next to this repo.
    """
    _load_dotenv()
    env = os.environ.get("SYM_PROJECT_DIR")
    if env:
        return Path(env)
    sibling = _repo_root().parent / "sym"
    return sibling if (sibling / "pyproject.toml").is_file() else Path("C:/Projects/sym")


def package_dsn(package: str) -> str:
    """DSN for a package's own database on the shared instance.

    Instance creds come from the libpq-standard ``PG*`` env (shared by every package); this only
    names the database (``dbname = <package>``). Override the whole DSN per package via
    ``<PKG>_DATABASE_URL``, or just its name via ``<PKG>_DB_NAME``.
    """
    _load_dotenv()
    p = package.upper()
    url = os.environ.get(f"{p}_DATABASE_URL")
    if url:
        return url
    host = os.environ.get("PGHOST", _INSTANCE_DEFAULTS["host"])
    port = os.environ.get("PGPORT", _INSTANCE_DEFAULTS["port"])
    user = os.environ.get("PGUSER", _INSTANCE_DEFAULTS["user"])
    dbname = os.environ.get(f"{p}_DB_NAME", package)
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={user}"]
    password = os.environ.get("PGPASSWORD")
    if password:
        # libpq keyword-DSN quoting: a password with spaces or quotes must be single-quoted,
        # with backslash-escaped \ and ' (else the whole DSN fails to parse at startup).
        quoted = password.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"password='{quoted}'")
    return " ".join(parts)


def db_dsn() -> str:
    """The sym package's database, full credentials (sym is a peer named ``sym``).

    This is the privileged path; consumer READS should use ``sym_readonly_dsn()`` so the
    least-privilege role enforces reads-are-read-only physically (Story QH.3).
    """
    return package_dsn("sym")


def dagster_job_url(job: str) -> str:
    """Deep link to a bucket's job in the Dagster UI (the lineage code location).

    The bucket jobs are named exactly the bucket keys, so ``{job}`` is the bucket key. Fully
    overridable for a different host/port or code-location name via ``DAGSTER_JOB_URL_TEMPLATE``
    (default targets ``dagster dev -m lineage.definitions`` on :3333). The link is best-effort —
    it just opens the Dagster UI; it doesn't require Dagster to be reachable from the API.
    """
    _load_dotenv()
    tmpl = os.environ.get(
        "DAGSTER_JOB_URL_TEMPLATE",
        "http://localhost:3333/locations/lineage.definitions/jobs/{job}",
    )
    return tmpl.format(job=job)


def sym_readonly_dsn() -> str:
    """Least-privilege DSN for consumer READS of the sym package (Story QH.3).

    sym is a read-only upstream peer; consumer reads go through the ``qrp_readonly``
    Postgres role whose grants (``SELECT`` on the AR-R3 read surface only) make a write
    physically impossible — not merely a code-review convention. Op-execution and each
    package's writes to its own database keep full credentials and do not use this DSN.

    Resolution precedence: ``SYM_READONLY_URL`` (whole DSN) > ``PGRO_USER`` /
    ``PGRO_PASSWORD`` role creds on the shared instance (host/port/dbname from the same
    ``PG*`` env as ``package_dsn``) > the full-cred sym DSN as a pre-provision fallback,
    so an environment that has not yet provisioned the role still reads (read-only by
    convention until it does).
    """
    _load_dotenv()
    url = os.environ.get("SYM_READONLY_URL")
    if url:
        return url
    ro_user = os.environ.get("PGRO_USER")
    if not ro_user:
        return db_dsn()
    host = os.environ.get("PGHOST", _INSTANCE_DEFAULTS["host"])
    port = os.environ.get("PGPORT", _INSTANCE_DEFAULTS["port"])
    dbname = os.environ.get("SYM_DB_NAME", "sym")
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={ro_user}"]
    password = os.environ.get("PGRO_PASSWORD")
    if password:
        # same libpq keyword-DSN quoting as package_dsn (a password with spaces/quotes
        # must be single-quoted with backslash-escaped \ and ' or the DSN won't parse).
        quoted = password.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"password='{quoted}'")
    return " ".join(parts)
