# ADR 0010: Revaluation as discrete runs with index adjustments

**Status:** Accepted · **Date:** 2026-07

## Context
Periodic revaluation is the AVM's economic case (collateral monitoring, LTV drift,
provisioning inputs) — a one-time valuation is what banks already buy from human
valuers. The Ames dataset is a single time slice, so market evolution must be
simulated somehow.

## Decision
Model revaluation as discrete runs: a `valuation_runs` dimension (run id, as-of date,
model id, scenario) over the existing (pid, model_id) valuation keying. Market
movement between runs is injected as neighbourhood-level index adjustments —
presented as what it is, since HPI-indexed AVM updating between full revaluations is
genuine industry practice. Triage logic extends to period-over-period signals (value
drop > X%, LTV crossing 80%). Stress scenarios are simply named runs with a different
index vector.

## Consequences
- Animates the whole platform in one demo arc: run → LTV distribution shifts →
  queue refills → underwriters work it → cycle report exports.
- Stress testing arrives almost free and is the slide risk committees care about.
- Hard boundary: no macro forecasting, no auto-provisioning, no rate models — beyond
  cycles + shocks + delta reporting lies a treasury system, not a demonstration.

## Alternatives considered
- **Time-series market simulator:** rejected; a rabbit hole with no ground truth to
  simulate from and no additional credibility over indexed runs.
