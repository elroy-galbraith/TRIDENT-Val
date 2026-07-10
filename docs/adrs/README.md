# TRIDENT-Val — Architecture Decision Records

Decision log for the TRIDENT-Val PoC (Residential Portfolio AVM & Risk Triage Engine).
Format follows Michael Nygard's ADR convention: Context → Decision → Consequences,
with rejected alternatives recorded explicitly.

| # | Title | Status |
|---|-------|--------|
| 0001 | [Postgres primary with SQLite zero-config fallback](0001-postgres-primary-sqlite-fallback.md) | Accepted |
| 0002 | [Track model artifact and dataset in the repository](0002-track-model-artifact-in-repo.md) | Accepted |
| 0003 | [Native TreeSHAP for explainability, not mocked contributions](0003-native-treeshap-explainability.md) | Accepted |
| 0004 | [Variance-based audit triage seeding with deterministic RNG](0004-variance-based-triage-seeding.md) | Accepted |
| 0005 | [Copilot LLM access via server-side proxy only](0005-copilot-llm-server-side-proxy.md) | Accepted |
| 0006 | [Copilot fenced to read/navigate-only actions](0006-copilot-read-navigate-only.md) | Accepted |
| 0007 | [Structural exclusion over ML redaction for DOM content leakage](0007-structural-exclusion-over-ml-redaction.md) | Accepted |
| 0008 | [Champion/challenger with shadow scoring; no per-property model choice](0008-champion-challenger-shadow-scoring.md) | Accepted |
| 0009 | [Reports anchored to IVS 103 / RICS Red Book structure](0009-reports-anchored-to-ivs-red-book.md) | Accepted |
| 0010 | [Revaluation as discrete runs with index adjustments](0010-revaluation-as-discrete-runs.md) | Accepted |
| 0011 | [Docling plus LLM typed extraction for document ingestion](0011-docling-llm-typed-extraction.md) | Accepted |
| 0012 | [dlt for source connectivity over heavyweight ETL](0012-dlt-over-heavyweight-etl.md) | Accepted |
| 0013 | [Synthetic sources derived from Ames ground truth](0013-synthetic-sources-from-ames.md) | Accepted |
| 0014 | [Thin work management; no workflow engine](0014-thin-work-management.md) | Accepted |
| 0015 | [Modular monolith over microservices](0015-modular-monolith.md) | Accepted |
| 0016 | [Vertical demo before platform refactor](0016-vertical-demo-before-platform-refactor.md) | Accepted |
| 0017 | [Production pipeline hardening: migrations, model monitoring, and in-tenant extraction ahead of ingestion buildout](0017-production-pipeline-hardening.md) | Proposed |
