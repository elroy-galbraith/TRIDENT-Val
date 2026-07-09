# ADR 0005: Copilot LLM access via server-side proxy only

**Status:** Accepted · **Date:** 2026-07

## Context
The in-page copilot (page-agent) needs an LLM backend. The library accepts an
OpenAI-compatible `baseURL` and key directly in the browser, and ships a demo CDN
routed through a free third-party testing endpoint.

## Decision
No API keys in the browser. page-agent points at a FastAPI proxy route
(`/api/v1/copilot`) which holds provider credentials server-side and forwards in
OpenAI chat-completions format. Provider selection (Gemini Flash default; Claude for
narration-heavy intents) is a proxy concern, invisible to the client.

## Consequences
- Key rotation, rate limiting, logging, and intent-based routing centralise in one
  place; providers can be swapped without touching frontend code.
- The proxy route must sit behind the same auth as the rest of the API — an exposed
  proxy is a free LLM endpoint on our billing (verified after Render deploy).
- The vendor demo CDN is prohibited for anything beyond a local toy.

## Alternatives considered
- **Key in browser env:** rejected; extractable by any visitor.
- **Vendor demo endpoint:** rejected; third-party sees all DOM content.
