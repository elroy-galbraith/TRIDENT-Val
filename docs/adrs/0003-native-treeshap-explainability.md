# ADR 0003: Native TreeSHAP for explainability, not mocked contributions

**Status:** Accepted · **Date:** 2026-07

## Context
The PRD specified a "SHAP mockup" widget showing top value drivers. Static numbers
would satisfy the wireframe but not the platform's core claim: that the valuation
process is legible to auditors.

## Decision
Use LightGBM's built-in `pred_contrib=True`, which returns exact TreeSHAP values with
no additional dependency. Contributions are computed in log-price space and converted
to approximate dollar impact at the prediction point. The widget recomputes live for
every what-if scenario.

## Consequences
- Explainability is a functional feature: drivers and detractors change coherently as
  the underwriter adjusts inputs, which is the strongest moment in the demo.
- Dollar conversion of log-space SHAP is a local approximation; documented as such.
- Zero added dependencies; negligible latency cost (round-trip stays well under the
  200 ms PRD budget).

## Alternatives considered
- **Hard-coded mock values:** rejected; undermines the legibility thesis the product
  is selling and would be exposed by any interactive scenario.
- **Separate `shap` package:** unnecessary for tree models; adds a heavy dependency
  for capability LightGBM already provides exactly.
