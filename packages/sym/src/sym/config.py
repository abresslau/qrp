"""Database connection configuration.

The connection is assembled from environment variables so that no credentials
live in the repository. A single ``SYM_DATABASE_URL`` takes precedence; otherwise
the libpq-standard ``PG*`` instance creds (PGHOST/PGPORT/PGUSER/PGPASSWORD) are used,
falling back to legacy ``SYM_DB_*`` then local-development defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "localhost"
DEFAULT_PORT = "5432"
DEFAULT_DBNAME = "sym"
DEFAULT_USER = "postgres"

DEFAULT_SOURCE = "yfinance"


def source_key() -> str:
    """The configured market-data source key (``SYM_SOURCE``), default ``yfinance``.

    Selects the adapter via :func:`sym.sources.registry.get_source` — swapping
    vendors is a config flip, never a code change (AR-5).
    """
    load_dotenv()
    return os.environ.get("SYM_SOURCE", DEFAULT_SOURCE)


@dataclass(frozen=True)
class DbConfig:
    """Resolved PostgreSQL connection parameters."""

    host: str
    port: str
    dbname: str
    user: str
    password: str | None

    def conninfo(self) -> str:
        """Return a libpq connection string for psycopg."""
        parts = [
            f"host={self.host}",
            f"port={self.port}",
            f"dbname={self.dbname}",
            f"user={self.user}",
        ]
        if self.password:
            parts.append(f"password={self.password}")
        return " ".join(parts)


def _find_dotenv() -> Path | None:
    """Locate a ``.env`` by walking up from this file to the repo root."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_dotenv() -> None:
    """Load ``KEY=VALUE`` pairs from a repo-root ``.env`` into ``os.environ``.

    Existing environment variables are never overwritten (the shell wins over
    the file). Lines that are blank or start with ``#`` are ignored.
    """
    path = _find_dotenv()
    if path is None:
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_db_config() -> str:
    """Resolve the database connection string from the environment.

    ``SYM_DATABASE_URL`` wins if set; otherwise the discrete ``SYM_DB_*``
    variables are assembled (falling back to local-development defaults).
    """
    load_dotenv()
    url = os.environ.get("SYM_DATABASE_URL")
    if url:
        return url

    cfg = DbConfig(
        host=os.environ.get("PGHOST") or os.environ.get("SYM_DB_HOST", DEFAULT_HOST),
        port=os.environ.get("PGPORT") or os.environ.get("SYM_DB_PORT", DEFAULT_PORT),
        dbname=os.environ.get("SYM_DB_NAME", DEFAULT_DBNAME),
        user=os.environ.get("PGUSER") or os.environ.get("SYM_DB_USER", DEFAULT_USER),
        password=os.environ.get("PGPASSWORD") or os.environ.get("SYM_DB_PASSWORD"),
    )
    return cfg.conninfo()
