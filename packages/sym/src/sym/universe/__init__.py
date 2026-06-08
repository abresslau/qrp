"""The sym Universe Layer (Epic U1).

A pluggable layer that defines *which* securities sym tracks — by index, custom
list, or rules-based criteria — and keeps that membership point-in-time and
survivorship-safe. Story U1.1 ships the foundation: the `universe` registry +
the config-keyed `UniverseProvider` abstraction (mirroring the AR-5 source
registry). Concrete providers and the membership event log/projection land in
later U1/U2/U5 stories.
"""

from __future__ import annotations
