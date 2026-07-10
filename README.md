# TRIDENT-Val — Residential Portfolio AVM & Risk Triage Engine (PoC)

End-to-end sandbox per PRD v1.0: a small **model risk inventory** (a LightGBM champion plus a
Ridge linear challenger, both trained on the Ames Housing Dataset's 2,930 assets), FastAPI
inference service, PostgreSQL portfolio book, and a multi-view React/Tailwind workbench for
risk officers and underwriters.

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
cd backend && uvicorn app.main:app --port 8000        # terminal 1
cd frontend && npm install && npm run dev             # terminal 2 -> http://localhost:5173
```

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

## Analytics (dbt)

The operational schema (`properties`, `bank_portfolio_meta`, `models`, `model_valuations`,
`revaluation_runs`/`revaluation_results`, `assignments`, `users`) is owned by the FastAPI
backend's SQLAlchemy models — dbt does **not** manage that schema or replace migrations. It
sits on top as a read-only analytics/transformation layer, in `dbt/`, connecting to the same
Postgres database and building staging + mart models for portfolio reporting:

- `stg_*` — one thin, renamed/typed view per operational table (`dbt/models/staging/`).
- `dim_properties` / `fct_model_valuations` — core dimension/fact tables.
- `mart_champion_challenger_disagreement` — champion vs. every challenger's valuation per
  property, flagged at the same 10% threshold as `GET /api/v1/models/disagreements`.
- `mart_portfolio_risk_summary` — LTV / AVM variance / audit-status rollup by neighborhood
  and building type.
- `mart_revaluation_impact` — per-run aggregate impact of each revaluation cycle.
- `mart_audit_triage_queue` — every Flagged/Pending Review property with its active assignment.

**Setup:**

```bash
cd dbt
pip install -r requirements.txt
export DBT_PROFILES_DIR="$PWD"   # profiles.yml lives in this directory
dbt debug   # confirms it can reach Postgres
dbt run     # builds staging views + mart tables into the `analytics` schema
dbt test    # runs the schema tests in models/staging/_staging.yml and models/marts/_marts.yml
```

Defaults in `dbt/profiles.yml` match `docker-compose.yml`'s Postgres (`localhost:5432`,
db `trident`, user `trident`) — start the stack with `docker compose up --build` first, or
override any of `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` /
`POSTGRES_DB` / `DBT_SCHEMA` as env vars to point at a different Postgres (e.g. Render).

## Architecture

```
data/ames_raw.csv          De Cock Ames dataset (2,930 rows, zero-scrape ingestion)
scripts/train_model.py     Trains champion (LightGBM) + challenger (Ridge linear) into
                           model/<id>/{model.joblib, feature_spec.json, manifest.json}
scripts/seed_db.py         DB instantiation + model registry + shadow-scoring + image mapping
model/
  lgbm_v1/                 Champion artifact + manifest (architecture, explainer, metrics)
  linear_v1/               Challenger artifact + manifest
backend/app/
  models.py                properties / bank_portfolio_meta / property_images / system_logs /
                           users / models (registry) / model_valuations (shadow-scoring ledger) /
                           revaluation_runs / revaluation_results (collateral monitoring cycles)
  auth.py                  bcrypt hashing + session-cookie get_current_user / require_role deps
  inference.py             Model-ID-keyed scoring; tree_shap (native TreeSHAP) and
                           linear_coef (exact coefficient attribution) explainers
  logging_config.py        loguru setup: console, rotating file, and DB sinks
  narrative.py             OpenRouter client for report narrative drafting (low-temperature,
                           grounded-only prompting; see Report Export above)
  reports.py               Report data assembly (IVS 103 / Red Book VPS 6 context) + Jinja2 ->
                           WeasyPrint PDF rendering
  templates/               report.css + asset_report.html + portfolio_report.html +
                           revaluation_report.html
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
    ModelCard.jsx          View 5 — model risk inventory + plain-language model card per
                           registered model: what it does, holdout accuracy, training data
                           provenance, interactive global feature-importance chart,
                           limitations & appropriate use, promote-to-champion (Admin)
    ModelCompare.jsx       View 6 — champion vs. challenger agreement scatter,
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

## PRD success metrics

| Metric | Status |
|---|---|
| Zero-scrape ingestion | ✅ Ames CSV + programmatic image hooks only |
| Inference latency < 200 ms | ✅ ~40 ms measured round-trip |
| Cohesive UX story | ✅ Risk overview → listing grid → operational override panel |
