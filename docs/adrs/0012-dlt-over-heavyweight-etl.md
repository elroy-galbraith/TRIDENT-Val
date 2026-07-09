# ADR 0012: dlt for source connectivity over heavyweight ETL

**Status:** Accepted · **Date:** 2026-07

## Context
The platform must credibly ingest from the variety of sources a bank actually has
(core-banking exports, SFTP drops, vendor APIs, spreadsheets) without standing up a
data-platform team's worth of infrastructure for a PoC.

## Decision
Use dlt (data-load tool): embeddable in the existing FastAPI/Python stack,
declarative sources, incremental loading, schema-evolution handling, and a connector
is just a Python function. Export side stays lightweight: CSV (existing), xlsx via
openpyxl, PDF via the reporting pipeline (ADR 0009).

## Consequences
- "We can ingest from your export format" is demonstrable in code a client's
  engineer can read in one sitting.
- Provenance (source, load timestamp) and quarantine of malformed records become
  first-class demo behaviours.
- dlt is a library, not a platform: scheduling/orchestration remains ours to own if
  volumes grow.

## Alternatives considered
- **Airbyte / Meltano:** rejected for PoC; a cluster to babysit and disproportionate
  ops burden for the same demo behaviours.
- **Hand-rolled ETL scripts:** rejected; schema drift and incremental state are
  exactly the undifferentiated work dlt already solves.
