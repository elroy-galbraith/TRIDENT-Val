# ADR 0004: Variance-based audit triage seeding with deterministic RNG

**Status:** Accepted · **Date:** 2026-07

## Context
The sandbox needs a plausible operational state: a triage queue that looks like a real
mortgage book under AVM monitoring, reproducible across rebuilds so demos and tests
are stable.

## Decision
Seed audit status from model-vs-sale variance: |AVM − sale| / sale > 15% →
Flagged: High Variance; 8–15% → Pending Review; else Approved. Simulated loan
balances drawn uniformly from 60–90% of baseline sale price using a fixed-seed RNG.

## Consequences
- Produces a realistic queue (~130 flagged, ~390 pending of 2,930) driven by genuine
  model disagreement, not random labels — flagged assets are actually the ones the
  model struggles with, which makes inspector walk-throughs credible.
- Deterministic rebuilds: screenshots, tests, and demo scripts stay valid.
- Thresholds are arbitrary but defensible; parameterise per client later.

## Alternatives considered
- **Random status assignment:** rejected; flagged assets would show no explainable
  anomaly on inspection, collapsing the demo narrative.
