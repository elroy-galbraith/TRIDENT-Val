# ADR 0011: Docling plus LLM typed extraction for document ingestion

**Status:** Accepted · **Date:** 2026-07

## Context
The platform must demonstrate extracting structured property data from PDFs
(surveyor reports, legacy mortgage files). Parsing layout and extracting typed fields
are different problems; hosted parsers exist but route client documents through
third-party clouds.

## Decision
Two-stage pipeline: Docling (open source, MIT, runs locally on CPU) for layout- and
table-aware parsing, then LLM structured-output extraction into typed Pydantic
schemas with per-field confidence. Low-confidence fields route into the existing
triage queue for human review rather than silently landing in the book.

## Consequences
- "Documents never leave your infrastructure" becomes a genuine differentiator when
  selling document processing to a bank.
- Confidence-gated human review extends the platform's legibility pattern to
  ingestion.
- Local parsing costs CPU; acceptable at PoC volume, benchmark before promising
  throughput.

## Alternatives considered
- **LlamaParse / Unstructured (hosted):** faster to start; rejected on data-residency
  positioning and per-page pricing.
- **AWS Textract:** strong on forms; rejected as it couples the pitch to a cloud
  vendor story.
- **Single-stage "LLM reads the PDF":** rejected; conflates layout recovery with
  field extraction and fails on tables and scans.
