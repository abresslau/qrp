"""DB-per-package topology discipline (Story QH.5 — the AR-R3 gate).

The topology's "contract" is discipline, not a package (architecture revision
2026-06-08). This suite IS the local CI for it (no CI infrastructure exists — a script
without a runner rots, the A.1 types-freshness lesson):

1. no Sqitch project's deploy DDL references another package's schema (the enforceable
   form of "no cross-DB FK" — Postgres cannot FK across databases, but cross-schema
   DDL coupling is the same disease);
2. consumer packages read ONLY the documented sym read surface (AR-R3 "consumers read
   sym's stable views" — base tables are the accepted surface until the federation
   restructure, per the architecture note; the allowlist lives in
   ``qrp_api.sym_contract`` and additions must be made THERE, deliberately — it is the
   single source shared with the ``qrp_readonly`` role provisioner, Story QH.3);
3. no consumer imports the sym Python package — cross-package DATA flows over
   read-only connections; cross-package CODE reuse flows through the peer packages'
   own seams (portfolios/signals/backtest), never through sym internals.

Honest limits (stated, not hidden): the scans are regex over source text, not SQL
parsers — dynamic SQL composition would evade them (none exists today); the CTE
exclusion is file-scoped; consumers' own .sql files carry only their own DDL (covered
by check 1, not 2-3); `services/api`'s sym module is the sym OWNER's serving surface
and is deliberately out of scope; `lineage` reads information_schema only.
"""

from __future__ import annotations

import re
from pathlib import Path

from qrp_api.sym_contract import SYM_INTERNAL_RELATIONS, SYM_READ_SURFACE

REPO = Path(__file__).resolve().parents[3]

# Sqitch project dir -> the schema(s) that project owns. sym owns the default (public)
# schema of its own database; operate owns the `qrp` schema. (The root `db/` dir is
# the RETIRED pre-split `qrp` monolith project — net-nil schema effect, recorded in
# tools/deploy_all.py and the ledger; deliberately not gated.)
PROJECT_SCHEMAS = {
    "packages/sym/migrations": {"public"},
    "packages/operate/db": {"qrp"},
    "packages/altdata/db": {"altdata"},
    "packages/backtest/db": {"backtest"},
    "packages/macro/db": {"macro"},
    "packages/optimiser/db": {"optimiser"},
    "packages/portfolios/db": {"portfolios"},
    "packages/signals/db": {"signals"},
}
ALL_PACKAGE_SCHEMAS = {"qrp", "altdata", "backtest", "macro", "optimiser", "portfolios",
                       "signals"}

# Relations that moved to the `universe` peer package + its own database — consumers
# (backtest/signals) read them as a peer DB, so they are a KNOWN vocabulary, not a sym read.
UNIVERSE_RELATIONS = {
    "universe", "membership_event", "membership_proposal", "universe_member_resolution",
    "universe_membership", "universe_monitor_log", "universe_accuracy_check",
}

# SYM_READ_SURFACE + SYM_INTERNAL_RELATIONS are imported from qrp_api.sym_contract — the
# single source shared with the qrp_readonly role provisioner (Story QH.3). Extend the
# surface THERE, deliberately.

CONSUMER_PACKAGES = ("altdata", "analytics", "backtest", "macro", "optimiser",
                     "portfolios", "signals", "operate")

# relation token after FROM/JOIN, optionally schema-qualified (qualification is
# captured so `public.prices_raw` / `sym.public.prices_raw` cannot slip past).
# Two passes with different case rules (each documented where used):
# - UPPERCASE keywords = the house SQL style — drives the unknown-name guard
#   (lowercase would also match Python `from x import` / prose, drowning it in noise);
# - case-INSENSITIVE — drives the allowlist scan over KNOWN sym relation names
#   (`from prices_raw` cannot evade by casing; `from __future__` is not a sym name).
_READ_UPPER_RE = re.compile(
    r"(?:FROM|JOIN)\s+([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*){0,2})\b"
)
_READ_ANYCASE_RE = re.compile(
    r"(?:FROM|JOIN)\s+([a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*){0,2})\b(?!\s+import\b)",
    re.IGNORECASE,
)



def _strip_sql_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _project_sql(project: str) -> list[Path]:
    files = sorted((REPO / project).rglob("*.sql"))
    assert files, f"{project}: no SQL found — the gate would pass vacuously"
    return files


def test_no_cross_package_schema_references_in_ddl():
    offenders: list[str] = []
    for project, own in PROJECT_SCHEMAS.items():
        foreign = ALL_PACKAGE_SCHEMAS - own
        for sql_file in _project_sql(project):
            text = _strip_sql_comments(sql_file.read_text(encoding="utf-8"))
            for schema in foreign:
                if re.search(rf"\b{schema}\.[a-z_]+", text, re.IGNORECASE):
                    offenders.append(f"{project}/{sql_file.name}: references {schema}.*")
    assert offenders == [], "cross-package schema coupling in DDL:\n" + "\n".join(offenders)


def _consumer_sources(pkg: str) -> list[Path]:
    files = sorted((REPO / "packages" / pkg / "src").rglob("*.py"))
    assert files, f"packages/{pkg}/src yields no sources — the gate would pass vacuously"
    return files


def _reads_in(text: str, pattern: re.Pattern) -> set[str]:
    """Bare relation tokens read in a source file.

    CTE names (file-scoped collection — an honest limit) and package-schema-qualified
    peer reads are excluded; qualification cannot hide a sym relation
    (the bare last component is what's compared).
    """
    ctes = {
        m.lower()
        for m in re.findall(
            r"(?:WITH(?:\s+RECURSIVE)?|,)\s+([a-z_][a-z_0-9]*)\s+AS\s*\(",
            text, re.IGNORECASE,
        )
    }
    out: set[str] = set()
    for m in pattern.finditer(text):
        token = m.group(1).lower()
        parts = token.split(".")
        if len(parts) > 1 and parts[0] in ALL_PACKAGE_SCHEMAS:
            # a package-schema-qualified read is a PEER-database read over that
            # package's own connection (own schema, or a cross-module input per
            # AR-R2 — e.g. signals reading macro.observation) — not a sym read.
            # sym relations live in sym's public schema and arrive (un)qualified
            # as public.<rel> or bare.
            continue
        bare = parts[-1]
        if bare in ctes and len(parts) == 1:
            continue
        out.add(bare)
    return out


def test_consumers_read_only_the_documented_sym_surface():
    # case-INSENSITIVE over the KNOWN sym names — casing cannot evade the allowlist
    offenders: list[str] = []
    for pkg in CONSUMER_PACKAGES:
        for src in _consumer_sources(pkg):
            reads = _reads_in(src.read_text(encoding="utf-8"), _READ_ANYCASE_RE)
            for rel in sorted(reads & SYM_INTERNAL_RELATIONS):
                offenders.append(f"packages/{pkg}/{src.name}: reads sym-internal {rel!r}")
    assert offenders == [], (
        "sym reads outside the AR-R3 surface (extend SYM_READ_SURFACE deliberately "
        "if the contract is meant to grow):\n" + "\n".join(offenders)
    )


def test_consumer_sym_reads_are_within_the_vocabulary():
    # the allowlist test above can only catch what its vocabulary names — this guard
    # fails when a consumer's FROM/JOIN names a relation the vocabulary doesn't know,
    # so silently widening the contract requires editing THIS file. House-style
    # (UPPERCASE) keywords only: a lowercase unknown-name read is the guard's stated
    # blind spot (lowercase KNOWN names are still caught by the allowlist above).
    known = SYM_READ_SURFACE | SYM_INTERNAL_RELATIONS | ALL_PACKAGE_SCHEMAS | UNIVERSE_RELATIONS
    unknown: list[str] = []
    for pkg in CONSUMER_PACKAGES:
        for src in _consumer_sources(pkg):
            reads = _reads_in(src.read_text(encoding="utf-8"), _READ_UPPER_RE)
            for rel in sorted(reads - known - {pkg}):
                unknown.append(f"packages/{pkg}/{src.name}: unvocabularied relation {rel!r}")
    assert unknown == [], (
        "relations the topology gate's vocabulary doesn't know (classify each as "
        "surface or internal):\n" + "\n".join(unknown)
    )


def test_no_consumer_imports_the_sym_python_package():
    offenders: list[str] = []
    for pkg in CONSUMER_PACKAGES:
        for src in _consumer_sources(pkg):
            text = src.read_text(encoding="utf-8")
            if re.search(r"^\s*(from sym[.\s]|import sym\b)", text, re.MULTILINE):
                offenders.append(f"packages/{pkg}/{src.name}")
    assert offenders == [], (
        "consumers must not import sym (data over connections only):\n"
        + "\n".join(offenders)
    )
