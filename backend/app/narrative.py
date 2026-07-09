"""LLM-drafted narrative sections for exported valuation reports (see app.reports).

Narrate, never compute: every figure that reaches this module was already computed by the
AVM/inference pipeline or recorded by a human underwriter before generation starts. The
model's only job is prose synthesis of the JSON payload it is handed — it is instructed to
never introduce a number, feature, name, or claim that isn't already present in that
payload. Report templates render the model's output inside a visibly delimited box (see
app.reports and the templates) so a reader can always tell which paragraphs are
LLM-assisted narration versus structured data pulled straight from the database.

Routed through OpenRouter (an OpenAI-compatible aggregator) so the drafting model can be
swapped via config with no code change; defaults to Gemini 2.5 Flash. Unlike the copilot
proxy in app.main (which streams a browser-facing chat session through the backend), this
call is entirely server-side: the narrative text is baked into the PDF at generation time
and the API key never has a code path to the browser.
"""
import json
import os
import time
from typing import Optional

import httpx
from loguru import logger

REPORT_LLM_BASE_URL = os.environ.get("REPORT_LLM_PROVIDER_BASE_URL", "https://openrouter.ai/api/v1")
REPORT_LLM_API_KEY = os.environ.get("REPORT_LLM_PROVIDER_API_KEY", "")
REPORT_LLM_MODEL = os.environ.get("REPORT_LLM_MODEL", "google/gemini-2.5-flash")
REPORT_LLM_TIMEOUT = float(os.environ.get("REPORT_LLM_TIMEOUT_SECONDS", "30"))
REPORT_LLM_TEMPERATURE = 0.2  # low temperature: drafting fixed facts, not being creative

NOT_CONFIGURED_MSG = (
    "AI-drafted narrative is not enabled for this deployment (REPORT_LLM_PROVIDER_API_KEY "
    "is unset). This section is left as a placeholder; every figure it would have narrated "
    "still appears in the structured data above.")
DRAFT_FAILED_MSG = (
    "AI-drafted narrative could not be generated for this export (the drafting request "
    "failed or timed out — see backend logs). This section is left as a placeholder; every "
    "figure it would have narrated still appears in the structured data above.")

SYSTEM_PROMPT = """You are drafting narrative sections of a professional residential property \
valuation decision report for a bank underwriting file, structured in accordance with IVS 103 \
/ RICS Red Book VPS 6 minimum report content. You are not the valuer and this is not your \
valuation: a human underwriter has already recorded (or is in the process of recording) the \
decision. Your only job is to turn the structured facts you are given into short, precise, \
professional prose that a RICS/IVS-literate reviewer can audit against the source data.

Hard rules, no exceptions:
1. Every number, percentage, feature name, model name, status, and date you write MUST come \
verbatim from the JSON payload in the user message. Never calculate, re-round, estimate, or \
invent a figure that is not already present in that payload.
2. Never assert what the valuation "should" be, never make or imply a credit recommendation. \
Describe what the data shows and what the underwriter recorded — do not tell the reader what \
to conclude or decide. Professional judgement belongs to the named underwriter, not to you.
3. If a field needed for a section is null, missing, or empty in the payload, say so plainly \
(e.g. "No underwriter notes were recorded at the time of export") instead of inventing content.
4. Plain, precise, professional prose. Short paragraphs, no bullet points, no headings, no \
marketing language, no hedging filler ("it's important to note that...").
5. Output ONLY a single JSON object matching the schema described in the user message — no \
markdown fences, no prose outside the JSON.
"""


# Module-level and persistent so repeated report exports reuse one connection pool instead of
# paying a fresh TCP/TLS handshake per narrative call — same rationale as the AsyncClient the
# copilot proxy in app.main keeps alive for its own LLM calls.
_client = httpx.Client(timeout=REPORT_LLM_TIMEOUT)


def is_configured() -> bool:
    return bool(REPORT_LLM_API_KEY)


def _chat_json(user_content: str, max_tokens: int, log_context: dict) -> Optional[dict]:
    """POST one chat-completion turn to OpenRouter and parse a JSON object out of it.
    Returns None on any failure — every caller must have a grounded fallback ready."""
    start = time.perf_counter()
    try:
        resp = _client.post(
            f"{REPORT_LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {REPORT_LLM_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "TRIDENT-Val Valuation Reports",
            },
            json={
                "model": REPORT_LLM_MODEL,
                "temperature": REPORT_LLM_TEMPERATURE,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.bind(context={**log_context, "model": REPORT_LLM_MODEL, "latency_ms": latency_ms}).info(
            "Report narrative drafted ({model}, {latency}ms).",
            model=REPORT_LLM_MODEL, latency=latency_ms)
        return parsed if isinstance(parsed, dict) else None
    except httpx.TimeoutException:
        logger.bind(context={**log_context, "model": REPORT_LLM_MODEL}).warning(
            "Report narrative drafting timed out after {timeout}s.", timeout=REPORT_LLM_TIMEOUT)
    except httpx.HTTPError as e:
        logger.bind(context={**log_context, "model": REPORT_LLM_MODEL, "error": str(e)}).warning(
            "Report narrative drafting failed: {error}", error=str(e))
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as e:
        logger.bind(context={**log_context, "model": REPORT_LLM_MODEL, "error": str(e)}).warning(
            "Report narrative drafting returned an unusable response: {error}", error=str(e))
    return None


ASSET_SCHEMA_HINT = """Return a JSON object with exactly these string keys:
- "variance_commentary": 2-4 sentences explaining, from the SHAP driver/detractor figures in \
the payload, why the AVM landed where it did and how it compares to the recorded baseline sale \
price and variance percentage.
- "disagreement_commentary": if the payload's champion/challenger comparison shows more than \
one model AND they diverge, 2-3 sentences explaining the disagreement and which value was \
booked and why (use the triage decision rationale if present). If there is only one model, or \
the payload says the models agree, set this to null.
- "notes_synthesis": if underwriter_notes in the payload is non-empty, 1-3 sentences \
summarizing it in third person. If underwriter_notes is empty, set this to null.
- "limitations_context": 1-2 sentences connecting the model's general limitations to this \
specific asset's numbers (e.g. its error band relative to its variance, or its audit status) — \
not a restatement of the generic limitations list, which is printed separately."""

PORTFOLIO_SCHEMA_HINT = """Return a JSON object with exactly this string key:
- "executive_summary": 4-7 sentences summarizing portfolio exposure, LTV risk distribution, \
audit triage outcomes, and champion/challenger model agreement, using only the figures in the \
payload below."""


def draft_asset_narrative(payload: dict, pid: int) -> dict:
    """Returns {variance_commentary, disagreement_commentary, notes_synthesis,
    limitations_context} — every value either grounded LLM prose or a clearly-labeled
    placeholder. Never raises."""
    fallback = {
        "variance_commentary": NOT_CONFIGURED_MSG if not is_configured() else DRAFT_FAILED_MSG,
        "disagreement_commentary": None,
        "notes_synthesis": None,
        "limitations_context": None,
    }
    if not is_configured():
        return fallback

    user_content = (
        f"{ASSET_SCHEMA_HINT}\n\nREPORT DATA (JSON):\n{json.dumps(payload, indent=2, default=str)}")
    result = _chat_json(user_content, max_tokens=900, log_context={"pid": pid, "report_type": "asset"})
    if result is None:
        return fallback
    return {
        "variance_commentary": result.get("variance_commentary") or fallback["variance_commentary"],
        "disagreement_commentary": result.get("disagreement_commentary") or None,
        "notes_synthesis": result.get("notes_synthesis") or None,
        "limitations_context": result.get("limitations_context") or None,
    }


def draft_portfolio_narrative(payload: dict) -> dict:
    """Returns {executive_summary} — grounded LLM prose or a clearly-labeled placeholder."""
    fallback = {
        "executive_summary": NOT_CONFIGURED_MSG if not is_configured() else DRAFT_FAILED_MSG,
    }
    if not is_configured():
        return fallback

    user_content = (
        f"{PORTFOLIO_SCHEMA_HINT}\n\nREPORT DATA (JSON):\n{json.dumps(payload, indent=2, default=str)}")
    result = _chat_json(user_content, max_tokens=500, log_context={"report_type": "portfolio"})
    if result is None:
        return fallback
    return {"executive_summary": result.get("executive_summary") or fallback["executive_summary"]}
