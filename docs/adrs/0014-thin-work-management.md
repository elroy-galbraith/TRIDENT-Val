# ADR 0014: Thin work management; no workflow engine

**Status:** Accepted · **Date:** 2026-07

## Context
Valuation teams assign properties to reviewers, and managers need to monitor
progress. The temptation is a full workflow product: notifications, comments,
escalation rules, SLAs.

## Decision
Build the thin version only: an `assignments` model (property, assignee, due date,
state) layered on the existing audit lifecycle, plus a manager view showing queue
depth per person, aging, and completion. Nothing more.

## Consequences
- Roughly a day of work; gives the manager in the demo room something to lean into.
- Workflow engines are a product category banks already own (and integrate with);
  competing there is PoC scope-death.
- Requests for notifications/escalations become integration conversations — and
  billable ones — rather than backlog items.

## Alternatives considered
- **Full workflow engine:** rejected; wrong competitive ground and unbounded scope.
- **No work management at all:** rejected; assignment visibility is cheap and
  directly answers a stated client behaviour.
