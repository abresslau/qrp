"""`universe` CLI — placeholder during the sym→universe extraction.

The universe subcommands currently live under ``sym universe`` (they need an injected identity
Resolver, which sym provides). This standalone entry point is reserved for the membership-only
verbs once the resolver injection lands; for now it points operators at `sym universe`.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print(
        "the universe CLI is not yet wired standalone — use `sym universe ...` "
        "(it injects the identity resolver). See universe-package.md.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
