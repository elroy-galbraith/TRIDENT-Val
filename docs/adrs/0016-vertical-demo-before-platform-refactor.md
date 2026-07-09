# ADR 0016: Vertical demo before platform refactor

**Status:** Accepted · **Date:** 2026-07

## Context
The project serves two goals in tension: a sharp, finished vertical demo for an
active bank negotiation, and a generalised platform for the consultancy's broader
pipeline. Generalisation work (module extraction, config surfaces, multi-tenant
concerns) competes for the same hours as demo polish, and refactoring destabilises
exactly the thing being shown.

## Decision
Sequence, don't blend. Finish the client-facing vertical story first — ingestion
demo, assignment view, reporting — then perform the modular refactor (ADR 0015) as a
deliberate platformisation step. The drift from "PoC for one bank" to "platform" is
acknowledged and adopted as a decision, not permitted as an accident.

## Consequences
- No refactoring mid-pitch; the demo stays stable in the weeks that matter.
- Platform work inherits a proven vertical as its reference implementation, which is
  the correct order for extracting abstractions.
- Requires restraint: generalisation ideas get logged, not implemented, until the
  vertical milestone closes.

## Alternatives considered
- **Refactor first:** rejected; abstractions extracted before a second use case exist
  are guesses, and the demo pays the stability cost.
- **Blend continuously:** rejected; the failure mode is a demo that breaks the week
  before the meeting.
