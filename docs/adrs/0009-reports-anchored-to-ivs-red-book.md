# ADR 0009: Reports anchored to IVS 103 / RICS Red Book structure

**Status:** Accepted · **Date:** 2026-07

## Context
Auditors need exportable reports containing results plus narrative commentary,
ideally following a professional-body format. RICS is the recognised valuation body
in the target market; the 2025 Red Book (aligned to IVS effective 2025) added
mandatory standards around AVMs and AI, and RICS responsible-AI standards require
disclosure when AI materially contributes to findings. The IVS position is that no
model output alone, absent professional judgement, constitutes a compliant valuation.

## Decision
Two report types — a per-asset decision report and a portfolio review summary —
structured on the IVS 103 / Red Book VPS minimum-contents skeleton (asset
identification, valuation date, basis of value, approach and model, key inputs and
assumptions, limitations, status of reviewer). Framing: the *underwriter's decision
report supported by the AVM*, never "the AVM's report". LLM narrates but never
computes: all figures injected from the database and inference pipeline; the LLM
drafts variance commentary (from SHAP drivers), disagreement explanation, and
limitations. AI-drafted sections are visibly delimited, and a standing disclosure
block records LLM assistance, reviewing human, and model id/version. Server-side PDF
(WeasyPrint from HTML templates).

## Consequences
- Reports read as professionally literate and embed the audit trail (model version,
  data timestamp, decision, signatory) — the legibility thesis as an artifact.
- Marketing constraint: describe as "structured in accordance with IVS 103 / Red Book
  reporting requirements", never "RICS-compliant" — compliance requires a Registered
  Valuer, not a format.

## Alternatives considered
- **Free-form LLM-written report:** rejected; unverifiable numbers and no
  professional anchor.
- **Numbers-only export:** rejected; misses the commentary auditors actually want and
  the differentiating capability.
