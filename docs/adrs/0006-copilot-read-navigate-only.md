# ADR 0006: Copilot fenced to read/navigate-only actions

**Status:** Accepted · **Date:** 2026-07

## Context
page-agent can operate any interactive element it can see, including "Save audit
decision". The platform's value proposition to a bank is a trustworthy, auditable
valuation process with human accountability.

## Decision
Mutating controls (audit status writes, notes, exports that trigger side effects) are
excluded from the agent's reach via interaction fencing. The copilot explains,
navigates, and filters; it does not write.

## Consequences
- Eliminates the worst demo/product failure mode: an AI mis-clicking into the audit
  ledger, which would contradict the governance story in one stroke.
- Onboarding and "show me the flagged assets" flows — the actual use case — are
  unaffected.
- If agent-initiated writes are ever wanted, they require an explicit
  confirm-with-human step and their own ADR.

## Alternatives considered
- **Full UI control:** rejected; an unaccountable writer inside an accountability
  product.
- **Confirmation dialogs on everything:** heavier UX for no additional demo value at
  PoC stage.
