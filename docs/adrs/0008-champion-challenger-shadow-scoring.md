# ADR 0008: Champion/challenger with shadow scoring; no per-property model choice

**Status:** Accepted · **Date:** 2026-07

## Context
The platform should demonstrate handling multiple model versions (updates or new
architectures) with model cards and comparison — the situation a bank's data science
team creates continuously. The naive design lets users pick which model values a
given property.

## Decision
One champion books every value; challengers score the full portfolio in shadow and
never book. Champion/challenger divergence beyond a threshold routes the asset to the
triage queue, where a human decides (accept champion, adopt challenger's figure as a
logged manual override, or set their own) with rationale recorded. Promotion of a
challenger to champion is a portfolio-level, logged, authorised act. A model registry
(id, version, status, metrics, model card) backs the whole mechanism; valuations are
keyed by (pid, model_id).

## Consequences
- Aligns with model risk management practice (SR 11-7-style inventory, shadow
  testing, governed promotion); reframes the product from "an AVM" to "model
  governance", a stronger institutional story.
- Disagreement becomes signal, feeding the existing triage/audit machinery.
- Requires a second model with genuine contrast (e.g. a GAM/linear challenger) so the
  disagreement queue is non-empty and interesting.

## Alternatives considered
- **Per-property model selection:** rejected as an adverse-selection anti-pattern —
  users pick the number they prefer, auditors flag it immediately, and the point of
  having a model is undermined.
