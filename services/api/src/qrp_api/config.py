"""Platform + database configuration for the QRP API.

Branding + the module registry come from ``platform.toml`` at the monorepo root. The
database connection reuses sym's env convention (``SYM_DATABASE_URL`` wins, else discrete
``SYM_DB_*`` with local-dev defaults), loaded from a monorepo-root ``.env`` — so the API
points at the same database as the sym CLI with zero extra setup.

(v1 uses a single DSN for reads. The architecture's dual-credential model — a read-only
role for reads + an op-exec path — is a follow-up hardening; reads here are SQL over sym's
published views/tables, and the API never mutates sym's schema.)
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

_DB_DEFAULTS = {"host": "localhost", "port": "5432", "dbname": "sym", "user": "postgres"}


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "platform.toml").is_file():
            return parent
    raise FileNotFoundError("platform.toml not found above the API package")


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
    """Directory of the sym project (where `uv run sym ...` executes for Operate jobs).

    Override with SYM_PROJECT_DIR; default is a sibling `sym` checkout next to this repo.
    """
    _load_dotenv()
    env = os.environ.get("SYM_PROJECT_DIR")
    if env:
        return Path(env)
    sibling = _repo_root().parent / "sym"
    return sibling if (sibling / "pyproject.toml").is_file() else Path("C:/Projects/sym")


def db_dsn() -> str:
    """Resolve the sym database DSN from the environment (sym's convention)."""
    _load_dotenv()
    url = os.environ.get("SYM_DATABASE_URL")
    if url:
        return url
    host = os.environ.get("SYM_DB_HOST", _DB_DEFAULTS["host"])
    port = os.environ.get("SYM_DB_PORT", _DB_DEFAULTS["port"])
    dbname = os.environ.get("SYM_DB_NAME", _DB_DEFAULTS["dbname"])
    user = os.environ.get("SYM_DB_USER", _DB_DEFAULTS["user"])
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={user}"]
    password = os.environ.get("SYM_DB_PASSWORD")
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


def package_dsn(package: str) -> str:
    """DSN for a package that owns its own database (DB-per-package topology).

    On the same Postgres instance as sym by default (reuses SYM_DB_* host/creds), in a
    database named after the package. Override per package via ``<PKG>_DATABASE_URL`` or the
    discrete ``<PKG>_DB_*`` (e.g. SIGNAL_DB_HOST) — so a package can later move to its own host.
    """
    _load_dotenv()
    p = package.upper()
    url = os.environ.get(f"{p}_DATABASE_URL")
    if url:
        return url
    host = os.environ.get(f"{p}_DB_HOST", os.environ.get("SYM_DB_HOST", _DB_DEFAULTS["host"]))
    port = os.environ.get(f"{p}_DB_PORT", os.environ.get("SYM_DB_PORT", _DB_DEFAULTS["port"]))
    dbname = os.environ.get(f"{p}_DB_NAME", package)
    user = os.environ.get(f"{p}_DB_USER", os.environ.get("SYM_DB_USER", _DB_DEFAULTS["user"]))
    parts = [f"host={host}", f"port={port}", f"dbname={dbname}", f"user={user}"]
    password = os.environ.get(f"{p}_DB_PASSWORD", os.environ.get("SYM_DB_PASSWORD"))
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


def macro_dsn() -> str:
    """DSN for the `macro` package's own database (see ``package_dsn``)."""
    return package_dsn("macro")


def signal_dsn() -> str:
    """DSN for the `signal` package's own database (see ``package_dsn``)."""
    return package_dsn("signal")
