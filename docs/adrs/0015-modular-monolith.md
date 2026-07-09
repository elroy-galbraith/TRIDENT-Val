# ADR 0015: Modular monolith over microservices

**Status:** Accepted · **Date:** 2026-07

## Context
The codebase is being restructured for reuse and resale: parts of the platform should
be pluggable into other engagements, demoable independently, and priceable as
modules. Microservices are the reflexive answer to "modular".

## Decision
Modular monolith: clear package boundaries — core (domain models), valuation
(registry, inference, champion/challenger), ingestion, reporting, workflow, copilot —
with explicit interfaces between them, deployed as a single unit. Resale enablers are
config-driven branding/thresholds and per-client data isolation, not deployment
topology. A service is extracted only when a specific boundary proves it needs
independent scaling or deployment under real load.

## Consequences
- Ops burden stays proportionate to a small team; no distributed-systems tax for
  zero client-visible benefit.
- Module boundaries double as the pricing sheet: clients can buy ingestion +
  reporting without the AVM, or the full stack.
- Discipline required: boundaries are only as real as the interfaces; cross-package
  imports must be policed.

## Alternatives considered
- **Microservices now:** rejected; multiplies deployment, observability, and failure
  modes before any boundary has earned it.
- **No restructuring:** rejected; the PoC's value as a reusable asset depends on
  separable parts.
