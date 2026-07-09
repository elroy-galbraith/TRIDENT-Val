# TRIDENT-Val — Residential Portfolio AVM & Risk Triage Engine (PoC)

End-to-end sandbox per PRD v1.0: a small **model risk inventory** (a LightGBM champion plus a
Ridge linear challenger, both trained on the Ames Housing Dataset's 2,930 assets), FastAPI
inference service, PostgreSQL portfolio book, and a multi-view React/Tailwind workbench for
risk officers and underwriters — plus two data-integration demos built on the same Ames book:
multi-source ingestion with provenance and quarantine (see [Data Ingestion](#data-ingestion-dlt))
and Docling+LLM document extraction scored against known ground truth (see
[Document Intake](#document-intake-docling-extraction)).

**Champion holdout accuracy:** MAPE 7.9%, R² 0.94. **Live inference latency:** ~40 ms round-trip.

**Champion/challenger governance:** exactly one registered model is the *champion* — its
valuation is what gets booked onto every asset. Every other model is a *challenger*: it scores
the whole portfolio in shadow, alongside the champion, and never books anything on its own.
Where the two disagree beyond a threshold, that asset routes to a disagreement queue for a
human decision (book the champion, book the challenger, or a manual override) — logged with a
rationale to the audit ledger. Promoting a challenger to champion is a separate, deliberate,
Admin-only act that re-books the whole portfolio in one pass. See
[Model Governance](#model-governance-championchallenger) below.

## Quickstart — Docker (recommended, matches PRD stack)

```bash
cp .env.example .env   # optional — only needed to enable the AI copilot, see below
docker compose up --build
```

- App: http://localhost:8080
- API docs (Swagger): http://localhost:8000/docs

This also builds and starts `vendor-api` (port 8001), the standalone mock valuation-vendor
feed the Data Ingestion tab's `valuation_vendor` source pulls from — see
[Data Ingestion](#data-ingestion-dlt).

First boot trains nothing (the fitted models ship in `model/lgbm_v1/` and `model/linear_v1/`)
and auto-seeds Postgres: 2,930 properties, simulated loan balances at 60–90% of baseline sale
price, both models registered and shadow-scoring the whole portfolio, variance-based audit
triage from the champion's valuation, a deterministic multi-photo labeled Unsplash mapping
per property, and three demo user logins (see
[Authentication & Roles](#authentication--roles-poc-grade)). Seeding is idempotent.

**Upgrading an existing checkout?** This adds a login and a new `users` table, and reshapes
`property_images` into a one-to-many, labeled table (`PropertyImage` gained `id`/`label`/
`sort_order` columns) — see the fresh-database note in
[Authentication & Roles](#authentication--roles-poc-grade) before
you boot against an existing Postgres volume or `trident.db`.

## Quickstart — no Docker (SQLite fallback)

```bash
cp .env.example .env   # optional — only needed to enable the AI copilot, see below
pip install -r backend/requirements.txt
PYTHONPATH=scripts python scripts/seed_db.py          # creates ./trident.db
cd vendor_api && pip install -r requirements.txt && uvicorn main:app --port 8001  # terminal 1
cd backend && uvicorn app.main:app --port 8000        # terminal 2
cd frontend && npm install && npm run dev             # terminal 3 -> http://localhost:5173
```

The `vendor_api` terminal is only needed for the Data Ingestion tab's `valuation_vendor`
source (see [Data Ingestion](#data-ingestion-dlt) below) — everything else works without it.

On Windows PowerShell replace the seed line with:
`$env:PYTHONPATH="scripts"; python scripts/seed_db.py`

Upgrading an existing checkout? Delete `trident.db` and rerun the seed script — see
[Authentication & Roles](#authentication--roles-poc-grade).

## Authentication & Roles (PoC-grade)

TRIDENT-Val requires a login. This is a lightweight foundation for governance — a real
login, a few roles with different permissions, and audit-trail entries that name the
human responsible — not production-grade IAM. See "Out of scope" below for what's
deliberately not here yet.

**No in-place upgrade — start from a fresh database.** There's no migration tool (schema
is managed via `Base.metadata.create_all`, which only ever adds tables, never columns to
existing ones), and the new `users` table only gets populated by a full reseed. If you
have an existing checkout:
- Docker: `docker compose down -v && docker compose up --build` (the `-v` is required —
  it drops the `pgdata` volume; skipping it leaves you with an empty `users` table and
  broken logging, since `system_logs` is also missing its new `actor` column).
- Local/SQLite: delete `trident.db` and rerun `python scripts/seed_db.py`.

### Demo credentials

Seeded by `scripts/seed_db.py`, printed to the console on every reseed. These are fixed
PoC fixtures, not secrets — don't reuse them anywhere, and don't expose this app beyond a
trusted local/demo network with the defaults intact.

| Username | Password | Role |
|---|---|---|
| `viewer` | `viewer123` | Viewer |
| `underwriter` | `underwriter123` | Underwriter |
| `admin` | `admin123` | Admin |

### Role matrix

| Role | View portfolio / properties / models | Read the audit log ledger (`/logs`) | Write audit / triage decisions | Promote a challenger to champion |
|---|---|---|---|---|
| Viewer | Yes | No | No | No |
| Underwriter | Yes | Yes | Yes | No |
| Admin | Yes | Yes | Yes | Yes |

Model promotion is Admin-only and Admin-only alone — it's the one place the role split isn't
a placeholder: re-booking the entire portfolio from a different model is a portfolio-level
model risk decision, not a per-asset override, so it sits one rung above the Underwriter's
day-to-day triage authority.

Every write is attributed: `PATCH /properties/{pid}/audit`, `POST
/properties/{pid}/triage-decision`, and `POST /models/{model_id}/promote` all record the
acting username (and, for the latter two, the rationale text) against the change in
`system_logs.actor`/`system_logs.context`, queryable via `GET /api/v1/logs`. The frontend
backs this with a server-enforced check — the Inspector's audit/triage controls and the
Model Card's "Promote to Champion" button are disabled or hidden for roles that can't use
them, but the real gate is the API's `require_role` dependency, not the disabled attribute.

### Out of scope (foundation for later)

Deliberately not built in this pass, so it's easy to pick up without re-deriving scope:

- Password reset, self-service signup, SSO, MFA
- Per-property or per-neighborhood row-level permissions (today's gating is per-action:
  read vs. write-audit vs. read-ledger)
- Rate limiting / lockout on failed logins
- Automatic HTTPS enforcement (no redirect/HSTS). The session cookie's `Secure` flag is
  configurable via `SESSION_COOKIE_SECURE` (defaults to `false`, appropriate for
  local/demo `http://localhost`) but nothing forces the connection itself onto HTTPS
- Alembic (or any) migration tooling — schema changes still require a full reseed
- Server-side session revocation before expiry (the signed cookie can only be
  invalidated early by rotating `SESSION_SECRET` for everyone)
- Any user-management UI — adding/removing/resetting a demo user means editing
  `scripts/seed_db.py` and doing a fresh reseed

## Model Governance (Champion/Challenger)

Model risk management, not just a second AVM for comparison's sake — this mirrors how a
bank's model validation function is expected to operate a model inventory (model cards,
shadow scoring, governed promotion) rather than swapping in whichever model scores best on
a leaderboard.

- **Registry** (`models` table, populated from `model/<id>/manifest.json` at seed time):
  every trained model's name, version, architecture, explainability method, holdout metrics,
  and governance status — `Champion` (exactly one; its valuation is booked), `Challenger`
  (scores the portfolio in shadow, never booked), or `Retired`.
- **Shadow scoring** (`model_valuations` table): every registered model is scored against
  every property at seed time — an append-only ledger, never overwritten in place — so
  champion-vs-challenger comparison and the disagreement queue are just queries against
  historical valuations, not live re-inference.
- **Two genuinely different architectures**, not a version bump, so their disagreement is a
  real signal: `lgbm_v1` (LightGBM gradient-boosted trees, `tree_shap` explainer — native
  TreeSHAP via `pred_contrib=True`) and `linear_v1` (Ridge linear regression, `linear_coef`
  explainer — exact per-feature attribution from the model's own coefficients, mapped back
  from the one-hot-encoded design matrix to the original feature names). The linear
  challenger tends to diverge most on high-end and unusual properties — it structurally
  can't represent the interaction effects the tree model captures — which is exactly what
  makes its disagreements worth routing to a human rather than averaging away.
- **Comparison & disagreement queue** (`GET /api/v1/models/compare`,
  `GET /api/v1/models/disagreements`, surfaced in the frontend's Compare tab): an agreement
  scatter, per-neighborhood MAPE/bias breakdown, and a divergence-ranked queue with a
  configurable threshold.
- **Triage decision** (`POST /api/v1/properties/{pid}/triage-decision`, Underwriter/Admin):
  for one asset, book the champion's value, book a specific challenger's value, or a manual
  override — each requires a rationale, logged to the audit ledger, and updates the booked
  `current_avm_value`/`avm_variance_pct`/`audit_status` in the same pass.
- **Promotion** (`POST /api/v1/models/{model_id}/promote`, Admin-only): designates a new
  champion at the portfolio level and re-books every asset's `current_avm_value` from that
  model's shadow valuations in one transaction — a deliberate, logged, all-or-nothing act,
  never a per-asset choice.

Out of scope for this pass: automatic retraining/CI for new model versions, drift
monitoring/alerting, and a fairness/disparate-impact audit across models — see the Model
Card's Limitations section for what each model doesn't cover.

## Retraining the models

```bash
python scripts/train_model.py   # writes model/lgbm_v1/ and model/linear_v1/, each with
                                 # model.joblib + feature_spec.json + manifest.json
```

Retraining alone doesn't change what's booked — rerun `scripts/seed_db.py` afterward to
re-register the models and re-score the portfolio, or use `POST /models/{model_id}/promote`
against a running app to promote a specific version without a full reseed.

## AI Copilot (page-agent)

The frontend ships [page-agent](https://github.com/alibaba/page-agent) — a floating,
in-page agent that reads the DOM as text and drives the UI on the user's behalf (open a
property, change a filter, walk through a chart) via natural-language requests. It talks
an OpenAI-compatible chat-completions API.

The LLM API key is never sent to the browser: `frontend/src/copilot.js` points
page-agent's `baseURL` at `/api/v1/copilot`, a same-origin FastAPI proxy
(`backend/app/main.py`) that attaches the real key and forwards to the provider.

Copy `.env.example` to `.env` and set `COPILOT_PROVIDER_API_KEY` to enable it — both
`docker compose` (which auto-loads a root `.env`) and the no-Docker `uvicorn` path (via
`python-dotenv`, loaded at the top of `main.py`) pick it up the same way. Leave `.env`
unset/absent and the proxy just returns 503; the rest of the app is unaffected.

| Env var | Default | Purpose |
|---|---|---|
| `COPILOT_PROVIDER_API_KEY` | *(empty)* | Provider API key. Unset = the proxy returns 503 and the widget is inert. |
| `COPILOT_PROVIDER_BASE_URL` | Gemini's OpenAI-compat endpoint | Swap for Anthropic's OpenAI-compatible endpoint, OpenAI itself, etc. |
| `COPILOT_MODEL` | `gemini-2.5-flash` | Server-controlled — the browser cannot override which model is billed. |

**Guardrails:** the audit status dropdown, underwriter notes field, and "Save audit
decision" button on the Inspector carry a `data-page-agent-not-interactive` attribute, so
the agent can read them but cannot click or type into them — an AI copilot should not be
able to write to the audit ledger unsupervised. The Risk Overview charts are SVG and
unreadable as DOM text; `transformPageContent` in `copilot.js` appends their underlying
JSON (LTV distribution, neighborhood concentration) to the agent's context so it can
answer chart questions without guessing.

**Reopening the widget:** the panel's own "X" button calls `agent.dispose()`, which is
terminal — a disposed `PageAgent` can't be reused. `App.jsx` tracks this via the agent's
`dispose` event and shows a "✦ Copilot" button in the header once the widget is closed,
which spins up a fresh instance.

**Activity log:** every history event (steps, retries, errors) is mirrored into the same
`system_logs` ledger as the rest of the app via `logger.track('copilot', ...)` — query
`GET /api/v1/logs?logger=copilot` to see what the agent has done. Note this persists
reflection/action summaries (not the full page-content payload sent to the LLM, which only
transits the network), so it's a smaller but real exposure of whatever's on screen when the
agent acts — worth keeping in mind alongside the audit-ledger fencing above.

## Report Export (IVS 103 / RICS Red Book VPS 6)

Two exportable PDF reports, rendered entirely server-side (FastAPI + Jinja2 + WeasyPrint —
`backend/app/reports.py`, `backend/app/templates/`; no browser rendering involved): a
per-asset **Underwriter Decision Report** and a portfolio-wide **Portfolio Review Summary**.
Both are structured against the IVS 103 / RICS Red Book VPS 6 minimum-content skeleton —
asset identification, valuation date, basis of value, approach and model used, key inputs and
significant assumptions, limitations, and sign-off — the professional anchor a RICS-trained
valuer (JN Bank's own included) will recognize, rather than a generic "export PDF" button.

**Framing matters.** Under IVS, no model output — an AVM included — constitutes a compliant
valuation without a valuer's professional judgement applied to it. So this is deliberately
*not* "the AVM's valuation report" — it's the **underwriter's decision record, supported by
AVM output**, built from the same audit lifecycle (`audit_status`, `underwriter_notes`, and
the `system_logs` decision trail) described above. Every report is explicit about what it is:
it is never labeled "RICS-compliant" (that requires a Registered Valuer's direct involvement),
only "structured in accordance with IVS 103 / RICS Red Book VPS 6 reporting requirements" —
and if an asset's audit status isn't yet Approved, the report says so in a banner up front
rather than reading like a completed sign-off.

**The LLM narrates, it never computes.** Every figure in a report is pulled straight from the
database or the same inference pipeline behind the Inspector page (`backend/app/inference.py`)
— nothing is calculated freshly for the PDF. The only generated text is a handful of short
narrative paragraphs — variance commentary from the SHAP driver table, a champion/challenger
disagreement explanation, a synthesis of the underwriter's own notes, and asset-specific
limitations context (portfolio report: one executive summary) — drafted at low temperature
(0.2, `backend/app/narrative.py`) from a prompt that embeds only the report's own structured
data and explicitly forbids introducing any number or claim not already in that payload.
Generated sections are visibly delimited in the document (dashed "AI-drafted" boxes) so a
reader always knows which paragraphs are narration versus structured data. Every report also
carries a standing **AI Use & Compliance Disclosure** box naming the drafting model, which
sections it drafted, and who reviewed/booked the underlying decision — RICS's responsible-AI
disclosure expectation made literal, not a compliance checkbox.

Reports still generate in full with no LLM configured — "AI-drafted" sections render a
clearly-labeled placeholder instead of prose, and every figure they would have referenced is
already in the report's structured data either way.

Routed through **OpenRouter** (an OpenAI-compatible model aggregator) so the drafting model
can be swapped by config alone; defaults to **Gemini 2.5 Flash**. This is a separate,
server-side-only LLM call from the AI copilot above, with its own provider config — the
narrative text is baked into the PDF at generation time, and (like the copilot) the provider
API key never has a code path to the browser.

| Env var | Default | Purpose |
|---|---|---|
| `REPORT_LLM_PROVIDER_API_KEY` | *(empty)* | OpenRouter API key. Unset = reports still generate in full; AI-drafted sections show a placeholder instead of prose. |
| `REPORT_LLM_PROVIDER_BASE_URL` | `https://openrouter.ai/api/v1` | Swap for any other OpenAI-compatible aggregator/provider. |
| `REPORT_LLM_MODEL` | `google/gemini-2.5-flash` | Drafting model, addressed by its OpenRouter slug. |

Document Intake's extraction pipeline (see below) reuses these same three variables by
default — the demo needs only one LLM key configured — with its own optional overrides:

| Env var | Default | Purpose |
|---|---|---|
| `EXTRACTION_LLM_PROVIDER_API_KEY` | falls back to `REPORT_LLM_PROVIDER_API_KEY` | Unset (both) = extraction has nothing to run — unlike report narration, there's no cosmetic fallback here. |
| `EXTRACTION_LLM_PROVIDER_BASE_URL` | falls back to `REPORT_LLM_PROVIDER_BASE_URL` | Point extraction at a different OpenAI-compatible provider than report narration. |
| `EXTRACTION_LLM_MODEL` | falls back to `REPORT_LLM_MODEL` | Extraction model, addressed by its OpenRouter slug. |
| `VENDOR_API_BASE_URL` | `http://localhost:8001` (`http://vendor-api:8001` in Docker) | Where the `valuation_vendor` dlt source pulls its paginated JSON feed from — see Data Ingestion. |

**Endpoints:** `GET /api/v1/properties/{pid}/report` and `GET /api/v1/portfolio/report`
(the latter takes optional `?champion=&challenger=` to pick which two registered models the
governance section compares). Both open to any logged-in role, same precedent as the CSV
export — exporting is a different format of data every role can already see live in-app, not
a new write privilege. Every export is itself logged to the audit ledger
(`GET /api/v1/logs`), naming who generated it and when.

**Running WeasyPrint locally (no Docker):** it needs Pango/Fontconfig's native libraries, not
just the `weasyprint` pip package. WeasyPrint itself needs no cairo/GDK-Pixbuf install — recent
versions render through a pure-Python backend.
- Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0 libfontconfig1 fonts-liberation`
  (see `backend/Dockerfile` for the Docker path, which installs these automatically).
- macOS: `brew install pango` (pulls in glib/harfbuzz/fontconfig transitively). If it still
  can't find the library after that — a known Homebrew + `cffi`/`dlopen` gotcha, more common
  on Apple Silicon, where Homebrew installs to `/opt/homebrew` instead of `/usr/local` — set
  `export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib"` in the same shell before starting
  uvicorn.

## Revaluation Cycles (Collateral Monitoring)

A one-time valuation is what a human valuer already delivers; the AVM's actual business case
is revaluing the whole book on a recurring cadence at near-zero marginal cost — collateral
monitoring, LTV drift, IFRS 9 provisioning inputs. The **Revaluation Cycles** tab turns the
static snapshot into that operating loop: run a cycle → the LTV distribution shifts → the
triage queue refills → underwriters work it via the same audit/triage endpoints described
above → a cycle report exports.

**Cycles, not a market simulator.** Each run (`revaluation_runs`, one row per cycle) applies a
neighborhood-level market index adjustment to every asset's currently booked AVM value and
refreshes LTV — this is deliberately not a time-series forecast, it's the same mechanism as
HPI-indexed AVM updating between full model-backed revaluations in conventional practice. A
champion promotion still re-anchors every value to raw model output; a cycle indexes on top of
whatever is currently booked. Four scenario types (`POST /api/v1/revaluations`):

- **Standard Quarterly Cycle** (`organic`) — small (±4%), deterministic per-neighborhood drift,
  not a forecast — just enough movement to shift LTV buckets and occasionally trip a flag
  between deliberate stress runs, the way a routine quarterly index update would.
- **Broad Market Stress** (`broad_stress`) — one uniform shock applied to every neighborhood.
- **Concentrated Neighborhood Shock** (`targeted_stress`) — an isolated shock to a single named
  neighborhood, for a concentration-risk story ("what if our largest neighborhood corrects
  15%?").
- **Custom** (`custom`) — a full operator-specified `{neighborhood: pct}` map.

**Triage gets a second signal.** Per-asset outcomes (`revaluation_results`) flag an asset where
its value dropped more than 10% since the prior booked value, or its LTV is at/above 80% after
the cycle — a period-over-period movement signal, distinct from (and additive to) the existing
variance-vs-original-sale-price triage. A flag from a cycle escalates `audit_status` to
`Flagged: High Variance` regardless of that asset's variance against the original sale price,
so a stress scenario visibly refills the queue even for assets that were otherwise Approved.
Gated the same as a triage decision (Underwriter/Admin) — this is routine collateral
monitoring, not the portfolio-wide model risk decision that gates model promotion.

**Cycle Report** (`GET /api/v1/revaluations/{run_id}/report`): the scenario and index
adjustments applied, the before/after LTV distribution, largest movers, and the triage queue
this cycle refilled, with an AI-drafted executive summary — same IVS 103 / Red Book framing,
`.disclosure-box`, and LLM-narrates-never-computes guarantee as the asset/portfolio reports
above (see [Report Export](#report-export-ivs-103--rics-red-book-vps-6)).

## Data Ingestion (dlt)

Champion/challenger governance and revaluation cycles are the "what does the model say"
half of a bank's demo needs. This is the other half: **how does data get into the book
safely** — meeting data where it lives, landing everything in one canonical model with
provenance, quarantining bad records instead of silently corrupting the book, and syncing
incrementally rather than a one-time load. No external dataset is needed to demonstrate
this: the existing 2,930-property Ames book is shattered into three fake "source systems"
that mirror what a bank's actual data estate looks like, each owning a different subset of
fields for the same properties.

- **`core_banking`** — a core-banking-style CSV drop (SFTP-shaped): loan/account fields,
  renamed columns, zero-padded string PIDs, dates in `DD/MM/YYYY`, dropped into
  `ingestion/dropzone/core_banking/`.
- **`valuation_vendor`** — a mock valuation-vendor feed: paginated JSON served by the
  standalone `vendor_api/` FastAPI service (its own process/port, not an in-process
  shortcut — "meeting data where it lives" is a literal separate service).
- **`valuations_team`** — a manual-review spreadsheet: xlsx with a merged two-row header
  and a free-text notes column, dropped into `ingestion/dropzone/valuations_team/`.

Each source deliberately includes a handful of malformed rows (a negative loan balance, an
unparseable PID, a non-numeric valuation figure). A [dlt](https://dlthub.com) pipeline
(`ingestion/pipeline.py`) lands each source into a local DuckDB staging file — never
straight into `properties`/`bank_portfolio_meta` — then a plain-Python merge step upserts
provenance (`property_source_records`: which source, when, the raw record as received) for
every row and, for `core_banking` only, refreshes `BankPortfolioMeta.current_loan_balance`.
It never touches `current_avm_value`/`avm_variance_pct`/`audit_status` — those stay owned
by the AVM scoring/triage logic in `scripts/seed_db.py`/`backend/app/main.py`, so a sync
can't silently perturb the numbers the rest of the app's demo depends on. Malformed rows
land in `ingestion_quarantine` with a human-readable reason instead of vanishing.

**Schema drift, live.** `python scripts/generate_ingestion_sources.py --drift` drops a
follow-up `core_banking` batch that introduces one new column
(`disbursement_channel`) on a handful of already-loaded PIDs. dlt's schema-evolution
default (`"evolve"`) picks it up automatically — nothing breaks, and the Data Ingestion
tab shows a schema-drift banner naming the new column and the run that introduced it.

**Generating the fake sources:**

```bash
python scripts/generate_ingestion_sources.py          # writes the dropzone CSVs/xlsx + vendor_api seed
python scripts/generate_ingestion_sources.py --drift  # + a follow-up core_banking batch with a new column
```

Both are deterministic (seeded RNG over Ames' own fields and PID variants — no
Faker-fabricated names/addresses, so this doesn't undercut the zero-scrape ingestion PRD
line below). Then trigger a sync from the **Data Ingestion** tab ("Sync Now" per source, or
"Sync All Sources"), or directly: `POST /api/v1/ingestion/sync {"source_system": "all"}`.

**Endpoints:** `POST /api/v1/ingestion/sync`, `GET /api/v1/ingestion/runs[/{run_id}]`,
`GET /api/v1/ingestion/records` (paginated provenance grid), `GET
/api/v1/ingestion/quarantine` + `POST /api/v1/ingestion/quarantine/{id}/resolve`. Sync is
Underwriter/Admin-gated (routine data-ops, not a portfolio-wide governance act); reads are
open to any logged-in role. Every sync and quarantine resolution is logged to the same
`system_logs` audit ledger as the rest of the app.

## Document Intake (Docling Extraction)

A measurable round-trip for document extraction, using the same "Ames is the source zoo"
trick: synthetic valuation-report PDFs are generated *from* existing property records (see
`backend/app/synthetic_reports.py`), so the ground truth is known, and extraction accuracy
can be scored exactly instead of eyeballed. **These are synthetic documents generated from
a public dataset to measure extraction accuracy against known ground truth — never
presented as real appraisals, surveys, or valuations.** Every generated PDF carries an
unmissable banner saying so, baked into the document itself, and the Document Intake tab
repeats the disclosure at the top of the page.

**The pipeline, two genuinely different jobs kept separate:**
1. [Docling](https://github.com/docling-project/docling) does the actual document
   understanding — layout analysis and OCR, turning a PDF into text/markdown. This is real
   extraction, not a mock.
2. An LLM then does *structured extraction only* from that already-extracted text —
   turning prose/table text into named fields with a confidence per field
   (`backend/app/extraction.py`, reusing the OpenRouter/`httpx` pattern from
   `backend/app/narrative.py`, but for a genuinely different task: extraction, not
   narration).
3. Every field is compared to the document's own `ground_truth` (numeric fields: a ±2%
   tolerance band; categorical fields: exact match) and a field routes to human triage when
   its confidence is below a threshold **or** it's simply wrong — deliberately including
   confident-but-wrong fields, not just low-confidence ones, since "we flagged what we
   weren't sure about" should hold even when a wrong guess happened to look plausible.

**Degradation.** A documented split of the generated documents is degraded to simulate the
paper reality of a decades-old mortgage file: rasterized (`pypdfium2`), skewed/blurred/
noised/contrast-faded (`Pillow`), and re-encoded through two low-quality JPEG passes before
being repackaged as a PDF (`img2pdf`) — see `backend/app/degrade.py`. This is what makes
"96% field accuracy overall, 99% on clean documents, 87% on degraded scans" a real,
measurable claim rather than a demo-day assertion.

**Generating the corpus:**

```bash
python scripts/generate_synthetic_reports.py                     # 200 documents, 30% degraded (defaults)
python scripts/generate_synthetic_reports.py --sample-size 50 --degraded-fraction 0.5
```

Requires the database to already be seeded (`scripts/seed_db.py`). Documents are written to
`data/synthetic_reports/` (gitignored, generated) and recorded as `SyntheticDocument` rows
with their `ground_truth` snapshot. Individual documents can also be generated from the
Document Intake tab, or `POST /api/v1/documents/generate`.

**Endpoints:** `POST /api/v1/documents/generate`, `GET /api/v1/documents`, `POST
/api/v1/documents/{document_id}/extract`, `GET /api/v1/extraction/runs[/{run_id}]`, `GET
/api/v1/extraction/accuracy` (overall/clean/degraded field accuracy + per-field breakdown —
the dashboard's headline numbers), `GET /api/v1/extraction/triage` + `POST
/api/v1/extraction/triage/{field_result_id}/resolve`.

**Two deployment prerequisites, unlike everything else in this README:**
- **Docling downloads layout/OCR models on first use** — from HuggingFace, and depending on
  the OCR engine, other model hosts (e.g. ModelScope for RapidOCR) — and it also pulls in
  `torch`. A deployment without outbound access to those hosts cannot run extraction —
  `docling` is lazy-imported inside `backend/app/extraction.py` (not at module import time)
  specifically so this fails as a clean `502` on the one affected endpoint (the failed
  `ExtractionRun` is still recorded with the error, queryable via `GET
  /api/v1/extraction/runs/{run_id}`) rather than crashing the whole backend at startup.
  `scripts/generate_synthetic_reports.py` is deliberately **not** part of the automatic
  `scripts/wait_and_seed.py` startup path for the same reason — the base app's boot never
  depends on Docling being installed or reachable.
- **Structured extraction needs an LLM key.** Unlike `app.narrative`'s graceful fallback (a
  cosmetic placeholder paragraph when no key is configured — harmless to the rest of a
  report), a missing key here means the demo's headline metric has nothing to score.
  Reuses `REPORT_LLM_PROVIDER_API_KEY`/`REPORT_LLM_MODEL` by default (see [Report
  Export](#report-export-ivs-103--rics-red-book-vps-6)) so the demo needs only one LLM key
  configured; override with `EXTRACTION_LLM_PROVIDER_API_KEY` /
  `EXTRACTION_LLM_PROVIDER_BASE_URL` / `EXTRACTION_LLM_MODEL` to point extraction at a
  different provider/model than report narration.

## Architecture

```
data/ames_raw.csv          De Cock Ames dataset (2,930 rows, zero-scrape ingestion)
data/synthetic_reports/    Generated synthetic valuation-report PDFs (gitignored)
scripts/train_model.py     Trains champion (LightGBM) + challenger (Ridge linear) into
                           model/<id>/{model.joblib, feature_spec.json, manifest.json}
scripts/seed_db.py         DB instantiation + model registry + shadow-scoring + image mapping
scripts/generate_ingestion_sources.py   Shatters Ames into the 3 fake dlt source systems
scripts/generate_synthetic_reports.py   Generates the synthetic-document extraction corpus
model/
  lgbm_v1/                 Champion artifact + manifest (architecture, explainer, metrics)
  linear_v1/               Challenger artifact + manifest
vendor_api/                Standalone mock valuation-vendor API (own FastAPI app, port 8001) —
                           see Data Ingestion above
ingestion/                 dlt pipelines for the 3 fake source systems — see Data Ingestion above
  sources/                 core_banking.py / valuation_vendor.py / valuations_team.py
  mapping.py                Per-source row validation + canonical field mapping
  pipeline.py               dlt.pipeline(...) + run_sync(): stage -> merge into canonical
                           tables + provenance -> quarantine rejected rows
  dropzone/                 Runtime CSV/xlsx drop folder (gitignored, generated)
backend/app/
  models.py                properties / bank_portfolio_meta / property_images / system_logs /
                           users / models (registry) / model_valuations (shadow-scoring ledger) /
                           revaluation_runs / revaluation_results (collateral monitoring cycles) /
                           ingestion_runs / property_source_records / ingestion_quarantine
                           (Data Ingestion) / synthetic_documents / extraction_runs /
                           extraction_field_results (Document Intake)
  auth.py                  bcrypt hashing + session-cookie get_current_user / require_role deps
  inference.py             Model-ID-keyed scoring; tree_shap (native TreeSHAP) and
                           linear_coef (exact coefficient attribution) explainers
  logging_config.py        loguru setup: console, rotating file, and DB sinks
  narrative.py             OpenRouter client for report narrative drafting (low-temperature,
                           grounded-only prompting; see Report Export above)
  reports.py               Report data assembly (IVS 103 / Red Book VPS 6 context) + Jinja2 ->
                           WeasyPrint PDF rendering
  synthetic_reports.py     Renders synthetic valuation-report PDFs from Ames records — the
                           Document Intake extraction-accuracy corpus (see above)
  degrade.py               Rasterize -> photocopy filter -> repackage as PDF (pypdfium2 +
                           Pillow + img2pdf) — simulates a scanned paper document
  extraction.py            Docling (layout/OCR) + LLM (structured extraction only) pipeline,
                           ground-truth scoring, triage routing — see Document Intake above
  templates/               report.css + asset_report.html + portfolio_report.html +
                           revaluation_report.html + synthetic_valuation_report.html
  main.py                  REST API (see below)
frontend/src/
  logger.js                loglevel wrapper: human-readable console + remote shipping
  copilot.js               page-agent setup: proxy baseURL, task context, chart summaries
  views/
    Login.jsx              Username/password login form
    Dashboard.jsx          View 1 — exposure, avg LTV, triage count, LTV histogram,
                           neighborhood concentration chart
    PortfolioGrid.jsx      View 2 — listing-style cards, filters, sort, CSV export
    Inspector.jsx          View 3 — glass-box matrix, SHAP/coefficient widget, what-if
                           scenario panel, delta meter, audit lifecycle box, model
                           comparison & triage decision panel (role-gated)
    RevaluationCycles.jsx  View 4 — collateral monitoring: run a cycle (standard/broad
                           stress/targeted stress/custom), cycle history, before/after LTV
                           shift, largest movers, triage queue refilled, cycle report export
    DataIngestion.jsx      View 5 — dlt source cards + sync trigger, sync history, provenance
                           grid, quarantine queue + resolve, schema-drift banner
    DocumentIntake.jsx     View 6 — extraction-accuracy dashboard (overall/clean/degraded,
                           per-field chart), synthetic-document corpus + generate/extract
                           actions, extraction triage queue + resolve
    ModelCard.jsx          View 7 — model risk inventory + plain-language model card per
                           registered model: what it does, holdout accuracy, training data
                           provenance, interactive global feature-importance chart,
                           limitations & appropriate use, promote-to-champion (Admin)
    ModelCompare.jsx       View 8 — champion vs. challenger agreement scatter,
                           per-neighborhood error/bias breakdown, disagreement queue,
                           promote-to-champion (Admin)
```

### Key API endpoints

All endpoints below require a logged-in session unless noted; ⚑ marks Underwriter/Admin-only,
⚑⚑ marks Admin-only.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | Log in, set the session cookie (open) |
| POST | `/api/v1/auth/logout` | Clear the session |
| GET | `/api/v1/auth/me` | Current user, or 401 (frontend's session check) |
| GET | `/api/v1/portfolio/summary` | Macro banners + chart data |
| GET | `/api/v1/properties` | Filtered/paginated grid |
| GET | `/api/v1/properties/{pid}` | Full asset file + baseline explainability (resolved model) |
| GET | `/api/v1/properties/{pid}/valuations` | Every registered model's shadow valuation for one property |
| POST | `/api/v1/valuate` | Live what-if inference against any model (±5% band + drivers) |
| PATCH | `/api/v1/properties/{pid}/audit` | ⚑ Underwriter notes + status writeback |
| POST | `/api/v1/properties/{pid}/triage-decision` | ⚑ Resolve a champion/challenger disagreement (book champion/challenger/manual + rationale) |
| GET | `/api/v1/properties/export` | Structural CSV download |
| GET | `/api/v1/properties/{pid}/report` | Underwriter Decision Report (PDF) — see Report Export |
| GET | `/api/v1/portfolio/report` | Portfolio Review Summary (PDF) — see Report Export |
| POST | `/api/v1/revaluations` | ⚑ Run a revaluation cycle (organic/broad_stress/targeted_stress/custom) — see Revaluation Cycles |
| GET | `/api/v1/revaluations` | Cycle history with per-run summary stats |
| GET | `/api/v1/revaluations/{run_id}` | One cycle's index adjustments, before/after LTV distribution, largest movers |
| GET | `/api/v1/revaluations/{run_id}/flagged` | Paginated triage queue this cycle flagged |
| GET | `/api/v1/revaluations/{run_id}/report` | Revaluation Cycle Report (PDF) — see Report Export |
| POST | `/api/v1/ingestion/sync` | ⚑ Trigger a dlt sync for one source system (or `all`) — see Data Ingestion |
| GET | `/api/v1/ingestion/runs` \| `/{run_id}` | Sync history, incl. schema-drift diff |
| GET | `/api/v1/ingestion/records` | Paginated provenance grid (filter by source/pid) |
| GET | `/api/v1/ingestion/quarantine` | Paginated quarantine queue |
| POST | `/api/v1/ingestion/quarantine/{id}/resolve` | ⚑ Resolve a quarantined record |
| POST | `/api/v1/documents/generate` | ⚑ Generate synthetic PDF(s) for pid(s)/style/degradation — see Document Intake |
| GET | `/api/v1/documents` | List synthetic documents (filter by degraded/style) |
| POST | `/api/v1/documents/{document_id}/extract` | ⚑ Run Docling + LLM extraction |
| GET | `/api/v1/extraction/runs` \| `/{run_id}` | Extraction run history + per-field breakdown |
| GET | `/api/v1/extraction/accuracy` | Overall/clean/degraded field accuracy + per-field breakdown |
| GET | `/api/v1/extraction/triage` | Paginated low-confidence/mismatch field queue |
| POST | `/api/v1/extraction/triage/{field_result_id}/resolve` | ⚑ Resolve a triaged field |
| GET | `/api/v1/models` | The model risk inventory: every registered model + governance status |
| GET | `/api/v1/models/{model_id}` \| `/spec` \| `/importance` | Per-model card, feature spec, portfolio-wide feature importance (cached) |
| POST | `/api/v1/models/{model_id}/promote` | ⚑⚑ Admin-only: designate a new champion, re-book the whole portfolio |
| GET | `/api/v1/models/compare` | Champion vs. challenger: scatter points, per-neighborhood error/bias, agreement stats |
| GET | `/api/v1/models/disagreements` | Paginated, divergence-ranked triage queue |
| GET | `/api/v1/logs` | ⚑ Query the unified operational/audit log ledger (supports `?actor=`) |
| POST | `/api/v1/logs/client` | Ingest batched frontend (loglevel) log entries (open — see Authentication & Roles) |
| POST | `/api/v1/copilot/chat/completions` | AI copilot LLM proxy (see below) |

### Design notes

- **Audit triage seeding** flags assets where |champion AVM − Sale| / Sale > 15%
  (Pending Review at 8–15%), producing a realistic queue: ~130 flagged, ~390 pending.
- **Explainability is real, not mocked, for every registered model**: the champion's
  LightGBM uses `pred_contrib=True` for exact TreeSHAP values; the linear challenger uses
  its own fitted coefficients (transformed-column contributions summed back to each
  original feature) — an exact attribution, not an approximation borrowed from a different
  model family. Both are converted to dollar impact the same way at the prediction point,
  so champion and challenger drivers are directly comparable.
- **Loan balances** use a seeded RNG (deterministic across rebuilds).
- **Logging**: the backend (`loguru`) and frontend (`loglevel`) both log in a
  human-readable, timestamped format, and both feed the same `system_logs` table —
  request/inference telemetry, underwriter audit-trail events (status/notes changes,
  scenario re-valuations), and frontend errors/usage events all land in one place,
  queryable via `GET /api/v1/logs`. Every event is attributed to the authenticated
  session via `system_logs.actor` where one exists (see
  [Authentication & Roles](#authentication--roles-poc-grade)). Backend logs also go to a
  rotating `logs/backend.log` file for local debugging.
- Out of scope per PRD: multi-tenancy, geospatial map servers. Document generation (exported
  PDF reports) is covered below — see
  [Report Export](#report-export-ivs-103--rics-red-book-vps-6). Auth now exists in
  lightweight, PoC-grade form — see
  [Authentication & Roles](#authentication--roles-poc-grade).
- **Data Ingestion and Document Intake are both still zero-scrape**: the three fake dlt
  source systems and the synthetic document corpus are generated entirely from Ames' own
  fields and a seeded RNG (PID variants, not Faker-fabricated names/addresses) — no
  external dataset or scrape is introduced anywhere in either feature.

## PRD success metrics

| Metric | Status |
|---|---|
| Zero-scrape ingestion | ✅ Ames CSV + programmatic image hooks only (also the source for the dlt/Docling demo data — see Data Ingestion / Document Intake) |
| Inference latency < 200 ms | ✅ ~40 ms measured round-trip |
| Cohesive UX story | ✅ Risk overview → listing grid → operational override panel |
