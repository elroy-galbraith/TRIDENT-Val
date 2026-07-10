# ADR 0017: Production pipeline hardening — migrations, model monitoring, and in-tenant extraction ahead of ingestion buildout

**Status:** Proposed · **Date:** 2026-07

## Context
ADRs 0011–0013 and 0015–0016 set direction for ingestion (`dlt`), document extraction
(Docling + LLM), and sequencing (vertical demo before platform refactor). Reviewing
that plan against what a bank's actual production deployment requires — not just what
demos well in a pitch — surfaces gaps the existing ADRs don't address: none block the
demo, but several will block the platform the moment ingestion work begins in earnest,
and one (model monitoring) is a bigger regulatory exposure than the ingestion tooling
itself.

## Decision
Before or alongside the ingestion buildout scoped in ADR 0012, add four things not
currently planned:

1. **Alembic migrations, before any new ingestion code lands.** Today, schema changes
   require dropping the database and reseeding (`Base.metadata.create_all`, additive
   columns only). A live bank portfolio can never be wiped to add a column. This is a
   harder blocker than which ETL library is used and should land first.

2. **A scheduled model backtest/drift job, reusing the existing champion/challenger and
   audit-ledger infrastructure.** No ADR currently covers ongoing model monitoring —
   the README lists drift monitoring and retraining cadence as explicitly out of scope.
   For an AVM feeding LTV/collateral/IFRS 9 decisions, a bank's model risk function
   (SR 11-7 / PRA SS1/23-style governance) will ask about ongoing performance
   monitoring before ingestion breadth. The shadow-scoring ledger already gives us
   predicted-vs-booked history; a periodic job comparing it against realized outcomes
   and alerting on drift is a small addition on top of infrastructure that already
   exists, not a new subsystem.

3. **In-tenant or self-hosted inference for the LLM extraction stage in ADR 0011, not
   only for Docling.** ADR 0011's "documents never leave your infrastructure" claim
   covers layout parsing but not the second stage — typed-field extraction currently
   implies an LLM call, which for the report-narration and copilot paths already goes
   to a hosted provider (OpenRouter/Gemini). Extracted PII (names, addresses, values)
   would leave the environment at exactly the step marketed as residency-safe. Either
   scope extraction to a model the bank's own tenant hosts (Azure OpenAI / Bedrock in
   their VPC, or an open-weight model on-prem), or narrow the claim to "parsing never
   leaves; extraction is configurable" before this goes in front of an infosec review.

4. **Lead connector design with SFTP/file-drop patterns, not API polling.** ADR 0013's
   mock vendor API is a reasonable demo prop, but banks are typically far more
   restrictive about outbound API integrations than periodic secure file transfers.
   `dlt` supports SFTP/file sources natively — the real connector story should lead
   with that pattern so it matches what a client's actual integration constraints look
   like, rather than over-indexing the demo on the API case.

Scheduling/orchestration (flagged as an open gap in ADR 0012) should also stop being
fully deferred: a minimal scheduled runner (cron job or GitHub Actions on a timer
invoking the `dlt` pipeline) should exist once there is more than one job to run
(ingestion sync + the new backtest job), rather than waiting for volume to force the
issue.

## Consequences
- Migrations become a prerequisite for ADR 0012's ingestion work rather than a
  parallel-track concern; this reorders near-term priority but doesn't change
  ADR 0012's tool choice.
- Model monitoring gets scoped as a near-term addition, not a deferred item — it is
  cheap to build (reuses `model_valuations` and `system_logs`) and closes the gap most
  likely to surface in a bank's model risk review.
- ADR 0011 is not reversed, but its data-residency claim needs either an
  implementation change (in-tenant extraction model) or a narrower claim before it's
  presented as-is to a client's security team.
- Connector prioritization shifts toward file-based sources first; the mock API
  connector from ADR 0013 remains useful as a secondary demo case, not the lead.
- None of this requires undoing ADR 0015/0016's sequencing — it fits inside "finish
  the vertical demo, then platformize," but shifts what belongs in the platformization
  pass.

## Alternatives considered
- **Leave the plan as-is (ADRs 0011–0013 only):** rejected; ships a residency claim
  that doesn't hold end-to-end and defers a schema-migration blocker until it breaks
  ingestion work already in flight.
- **Build full orchestration (Airflow/Dagster) now:** rejected for the same reason
  ADR 0012 rejected Airbyte/Meltano — disproportionate ops burden before volume or
  job count justifies it. A minimal scheduled runner is enough until that changes.
- **Defer model monitoring until after the ingestion platform is built:** rejected;
  it's smaller in scope than the ingestion work and closer to what a bank's model risk
  reviewer will ask about first, so it should not sit behind a larger, longer-lead
  workstream.
