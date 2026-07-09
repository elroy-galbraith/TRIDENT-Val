# ADR 0013: Synthetic sources derived from Ames ground truth

**Status:** Accepted · **Date:** 2026-07

## Context
Ingestion and extraction need demo data. No suitable open dataset mirrors a bank's
internal source landscape, and real documents would be unverifiable (and
unobtainable). The question "what are we showing?" resolves to behaviours — meet data
where it lives, canonical model with provenance, quarantine of bad records,
incremental sync — not to the data itself.

## Decision
Shatter the Ames book into fake source systems that mirror the client's landscape: a
core-banking-style CSV drop with realistic ugliness (renamed columns, divergent date
formats, string PIDs), a paginated mock vendor API, and a valuations-team xlsx with
deliberately broken rows. For document extraction, generate surveyor-style PDF
reports *from Ames records*, degrade a subset to scan quality, and run Docling + LLM
extraction against documents whose true values are known — enabling measured
per-field accuracy and confidence-based routing to triage.

## Consequences
- Extraction accuracy becomes a measurable claim ("X% correct, uncertain fields
  flagged") rather than a pretty demo over unverifiable documents.
- Disclosure rule: presented as "synthetic reports generated from a public dataset so
  extraction accuracy can be measured against ground truth" — the simulation framed
  as methodology, never passed off as real.
- Ames serves as both source zoo and answer key; no external datasets required.

## Alternatives considered
- **Scraped/real documents:** rejected; no ground truth, legal ambiguity, and weaker
  claims.
- **Fully invented synthetic data:** rejected; loses the anchor to a known-good book
  the rest of the platform already uses.
