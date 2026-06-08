"""sym — Global Equity Security Master + Market Data + Returns warehouse.

Module 1 of a personal quant research warehouse. The package is organized into
domain subpackages:

- ``identity``       — FIGI resolution, securities master, effective-dated symbology
- ``sources``        — source-abstraction contract and per-vendor adapters
- ``ingest``         — price/factor ingestion, anomaly annotation, run logging
- ``calendar``       — trading-calendar snapshotting
- ``returns``        — adjusted-price view + 18-window PR/TR return engine
- ``classification`` — GICS classification (slowly-changing dimension)
"""

__version__ = "0.1.0"
