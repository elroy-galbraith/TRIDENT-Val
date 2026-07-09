# ADR 0007: Structural exclusion over ML redaction for DOM content leakage

**Status:** Accepted · **Date:** 2026-07

## Context
Interaction fencing stops the agent from *touching* sensitive fields but page-agent
still serialises the full DOM as text, so underwriter notes and audit status were
transmitted to the LLM on every step. An ML PII-redaction layer (client-side NER,
~98% recall on Latin-script names) was evaluated as a fix.

## Decision
Deterministic structural exclusion as the primary control: elements tagged
`data-copilot-redact` have their content scrubbed from the serialised DOM before it
leaves the proxy, replaced by a stub (e.g. "[underwriter notes: hidden]"). ML
redaction is reserved as optional defence-in-depth for PII appearing in fields we did
not anticipate.

## Consequences
- Zero-leak guarantee for known fields, with no recall percentage to caveat.
- Business-confidential non-PII content (statuses, balances, litigation notes) is
  covered — NER taxonomies would miss it entirely.
- The stub keeps the copilot honest: it knows a field exists but cannot read it.
- Residual risk: sensitive data typed into untagged fields; that is the
  defence-in-depth layer's job if real client data ever enters scope.

## Alternatives considered
- **NER redaction as primary (e.g. Rampart):** rejected. Probabilistic where the
  problem is deterministic (field locations are known), blind to non-PII confidential
  content, and weak on non-Latin scripts. Sound tool, wrong layer.
- **Regex DLP at proxy:** weaker than both; catches formats, not meaning.
