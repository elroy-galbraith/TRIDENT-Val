"""Docling + LLM document-extraction pipeline for the extraction-accuracy demo (see README's
Document Intake section, and app.synthetic_reports for how the source documents and their
ground truth are generated).

Two genuinely different jobs, kept separate: Docling does the actual document understanding —
layout analysis and OCR, turning a PDF (possibly a degraded scan) into text/markdown. An LLM
then does *structured extraction only* from that already-extracted text — turning prose/table
text into the named fields TRIDENT-Val's canonical Property model uses, with a confidence per
field. This mirrors app.narrative's "LLM narrates, never computes" ethos in reverse: here the
LLM never invents document content, it only structures what Docling already read.

`docling` is lazy-imported inside extract_document() rather than at module top: it pulls in
torch and downloads layout/OCR models from HuggingFace on first use, so a deployment without
network access to huggingface.co (or without the package installed) should 503 cleanly on this
one feature rather than crash the whole backend at import time — the same posture as "reports
still generate in full with no LLM configured" in app.narrative.
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from .models import ExtractionFieldResult, ExtractionRun, ExtractionRunStatus, SyntheticDocument

EXTRACTION_LLM_BASE_URL = os.environ.get(
    "EXTRACTION_LLM_PROVIDER_BASE_URL",
    os.environ.get("REPORT_LLM_PROVIDER_BASE_URL", "https://openrouter.ai/api/v1"))
EXTRACTION_LLM_API_KEY = os.environ.get(
    "EXTRACTION_LLM_PROVIDER_API_KEY", os.environ.get("REPORT_LLM_PROVIDER_API_KEY", ""))
EXTRACTION_LLM_MODEL = os.environ.get(
    "EXTRACTION_LLM_MODEL", os.environ.get("REPORT_LLM_MODEL", "google/gemini-2.5-flash"))
EXTRACTION_LLM_TIMEOUT = float(os.environ.get("EXTRACTION_LLM_TIMEOUT_SECONDS", "60"))

CONFIDENCE_TRIAGE_THRESHOLD = 0.75

# (field, kind, tolerance) — kind="numeric" compares with a relative tolerance (fractional,
# e.g. 0.02 = +/-2%); kind="exact" does a case-insensitive string/int compare. Mirrors
# app.synthetic_reports.GROUND_TRUTH_FIELDS, the answer key every document was built from.
FIELD_SPECS = [
    ("pid", "exact", None),
    ("neighborhood", "exact", None),
    ("bldg_type", "exact", None),
    ("house_style", "exact", None),
    ("ms_zoning", "exact", None),
    ("year_built", "exact", None),
    ("overall_qual", "exact", None),
    ("overall_cond", "exact", None),
    ("gr_liv_area", "numeric", 0.02),
    ("total_bsmt_sf", "numeric", 0.02),
    ("full_bath", "exact", None),
    ("half_bath", "exact", None),
    ("bedroom_abvgr", "exact", None),
    ("sale_price", "numeric", 0.02),
]

SYSTEM_PROMPT = """You are extracting structured field values from the text of a scanned \
property valuation document for a data-quality benchmark. The text was produced by an OCR/
layout pipeline and may contain recognition errors, especially if the source was a degraded \
scan.

Hard rules:
1. Extract ONLY values that are actually present in the given text. Never use outside \
knowledge about real properties, never guess a "plausible" value if the text doesn't contain \
it — if a field is illegible or absent, set its value to null and confidence to 0.
2. confidence is your own estimate (0.0-1.0) of how certain you are that the extracted value \
exactly matches what the source text states, given OCR noise, ambiguous formatting, etc. Low \
confidence for anything you had to guess at or that looks OCR-garbled.
3. Numeric fields must be plain numbers (no "$", no commas, no units).
4. Output ONLY a single JSON object matching the schema in the user message — no markdown \
fences, no prose outside the JSON.
"""

SCHEMA_HINT = """Return a JSON object with exactly these keys, each mapping to an object with
"value" and "confidence" keys:
- pid (integer, the parcel/property ID)
- neighborhood (string)
- bldg_type (string, e.g. "1Fam")
- house_style (string, e.g. "1Story")
- ms_zoning (string, e.g. "RL")
- year_built (integer)
- overall_qual (integer 1-10)
- overall_cond (integer 1-10)
- gr_liv_area (number, gross living area in sq ft)
- total_bsmt_sf (number, total basement area in sq ft)
- full_bath (integer)
- half_bath (integer)
- bedroom_abvgr (integer, bedrooms above grade)
- sale_price (number, the appraised/valuation figure in USD)"""

_client = httpx.Client(timeout=EXTRACTION_LLM_TIMEOUT)


def is_llm_configured() -> bool:
    return bool(EXTRACTION_LLM_API_KEY)


def _docling_convert(file_path: str) -> str:
    """Lazy-imported: docling pulls in torch and downloads layout/OCR models from
    HuggingFace on first DocumentConverter() call. Import failures and conversion failures
    (including a blocked/offline model download) both raise — the caller marks the
    ExtractionRun as failed rather than letting either crash the request."""
    from docling.document_converter import DocumentConverter  # noqa: PLC0415
    converter = DocumentConverter()
    result = converter.convert(file_path)
    return result.document.export_to_markdown()


def _extract_fields_via_llm(document_text: str) -> dict:
    """Returns {field_name: {"value": ..., "confidence": float}}. Raises on any failure —
    the caller is responsible for marking the run failed; there is no cosmetic fallback here
    the way app.narrative has one, because a missing extraction *is* the missing headline
    metric, not a cosmetic placeholder paragraph (see module docstring)."""
    resp = _client.post(
        f"{EXTRACTION_LLM_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {EXTRACTION_LLM_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "TRIDENT-Val Document Extraction",
        },
        json={
            "model": EXTRACTION_LLM_MODEL,
            "temperature": 0.0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{SCHEMA_HINT}\n\nDOCUMENT TEXT:\n{document_text}"},
            ],
        },
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM extraction did not return a JSON object")
    return parsed


def _values_match(field: str, kind: str, tolerance: Optional[float], extracted, truth) -> Optional[bool]:
    if extracted is None:
        return None  # field wasn't extracted at all — not the same as "extracted but wrong"
    if kind == "numeric":
        try:
            return abs(float(extracted) - float(truth)) <= tolerance * abs(float(truth) or 1.0)
        except (TypeError, ValueError):
            return False
    return str(extracted).strip().lower() == str(truth).strip().lower()


def extract_document(db: Session, document_id: int, actor: Optional[str]) -> ExtractionRun:
    """Runs Docling conversion + LLM structured extraction for one synthetic document,
    scores every field against its known ground truth, and routes low-confidence-or-wrong
    fields to human triage. Synchronous, matching the rest of the app's heavy-but-synchronous
    operations (report generation, revaluation cycles, ingestion sync)."""
    document = db.get(SyntheticDocument, document_id)
    if document is None:
        raise ValueError(f"SyntheticDocument {document_id} not found")

    run = ExtractionRun(document_id=document_id, status=ExtractionRunStatus.RUNNING, triggered_by=actor)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        docling_start = time.perf_counter()
        document_text = _docling_convert(document.file_path)
        docling_latency_ms = (time.perf_counter() - docling_start) * 1000

        if not is_llm_configured():
            raise RuntimeError(
                "No extraction LLM configured (EXTRACTION_LLM_PROVIDER_API_KEY / "
                "REPORT_LLM_PROVIDER_API_KEY unset) — structured extraction has nothing to run.")

        llm_start = time.perf_counter()
        extracted = _extract_fields_via_llm(document_text)
        llm_latency_ms = (time.perf_counter() - llm_start) * 1000

        matches = []
        for field, kind, tolerance in FIELD_SPECS:
            entry = extracted.get(field) or {}
            value = entry.get("value") if isinstance(entry, dict) else entry
            confidence = entry.get("confidence") if isinstance(entry, dict) else None
            truth = document.ground_truth.get(field)
            match = _values_match(field, kind, tolerance, value, truth)
            confidence = float(confidence) if isinstance(confidence, (int, float)) else None
            # Route on a wrong/missing field OR low confidence — deliberately including a
            # confident-but-wrong field (match is False) as well as a correct-but-unsure one
            # (match is True, confidence below threshold): "we flagged what we weren't sure
            # about" should be true even when the guess happened to land right.
            routed = (match is not True) or confidence is None or confidence < CONFIDENCE_TRIAGE_THRESHOLD
            matches.append(match)
            db.add(ExtractionFieldResult(
                run_id=run.id, field_name=field,
                extracted_value=None if value is None else str(value),
                ground_truth_value=str(truth), match=match, confidence=confidence,
                routed_to_triage=routed,
            ))

        scored = [m for m in matches if m is not None]
        run.overall_field_accuracy = (sum(1 for m in scored if m) / len(scored)) if scored else 0.0
        run.docling_latency_ms = round(docling_latency_ms, 1)
        run.llm_latency_ms = round(llm_latency_ms, 1)
        run.llm_used = True
        run.status = ExtractionRunStatus.SUCCEEDED
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.bind(actor=actor, context={
            "run_id": run.id, "document_id": document_id, "accuracy": run.overall_field_accuracy,
            "degraded": document.degraded,
        }).info("Extraction run #{run_id} for document {doc_id}: {accuracy:.0%} field accuracy.",
               run_id=run.id, doc_id=document_id, accuracy=run.overall_field_accuracy)
        return run
    except Exception as e:
        db.rollback()
        run = db.get(ExtractionRun, run.id)
        run.status = ExtractionRunStatus.FAILED
        run.completed_at = datetime.now(timezone.utc)
        run.error = str(e)
        db.commit()
        logger.bind(actor=actor, context={"run_id": run.id, "document_id": document_id, "error": str(e)}).error(
            "Extraction run #{run_id} for document {doc_id} failed: {error}",
            run_id=run.id, doc_id=document_id, error=str(e))
        raise
