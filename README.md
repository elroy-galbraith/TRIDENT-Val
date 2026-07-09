# TRIDENT-Val — Residential Portfolio AVM & Risk Triage Engine (PoC)

End-to-end sandbox per PRD v1.0: LightGBM AVM trained on the Ames Housing Dataset (2,930 assets),
FastAPI inference service, PostgreSQL portfolio book, and a three-view React/Tailwind workbench
for risk officers and underwriters.

**Holdout accuracy:** MAPE 7.9%, R² 0.94. **Live inference latency:** ~40 ms round-trip.

## Quickstart — Docker (recommended, matches PRD stack)

```bash
cp .env.example .env   # optional — only needed to enable the AI copilot, see below
docker compose up --build
```

- App: http://localhost:8080
- API docs (Swagger): http://localhost:8000/docs

First boot trains nothing (the fitted model ships in `model/`) and auto-seeds Postgres:
2,930 properties, simulated loan balances at 60–90% of baseline sale price, variance-based
audit triage, deterministic Unsplash image mapping, and three demo user logins (see
[Authentication & Roles](#authentication--roles-poc-grade)). Seeding is idempotent.

**Upgrading an existing checkout?** This adds a login and a new `users` table — see the
fresh-database note in [Authentication & Roles](#authentication--roles-poc-grade) before
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

| Role | View portfolio / properties / model | Read the audit log ledger (`/logs`) | Write audit decisions |
|---|---|---|---|
| Viewer | Yes | No | No |
| Underwriter | Yes | Yes | Yes |
| Admin | Yes | Yes | Yes |

Admin is currently permission-identical to Underwriter — it's a taxonomy placeholder for
future admin-only capability (e.g. user management), not wired to anything distinct yet.

Every write is attributed: `PATCH /properties/{pid}/audit` records the acting
username against the status/notes change in `system_logs.actor`, queryable via
`GET /api/v1/logs`. The frontend backs this with a server-enforced check — the
Inspector's audit controls are disabled for non-Underwriter/Admin roles, but the real
gate is the API's `require_role` dependency, not the disabled attribute.

### Out of scope (foundation for later)

Deliberately not built in this pass, so it's easy to pick up without re-deriving scope:

- Password reset, self-service signup, SSO, MFA
- Per-property or per-neighborhood row-level permissions (today's gating is per-action:
  read vs. write-audit vs. read-ledger)
- Rate limiting / lockout on failed logins
- HTTPS/secure-cookie enforcement (the session cookie is `https_only=False`, appropriate
  for local/demo `http://localhost` only)
- Alembic (or any) migration tooling — schema changes still require a full reseed
- Server-side session revocation before expiry (the signed cookie can only be
  invalidated early by rotating `SESSION_SECRET` for everyone)
- Any user-management UI — adding/removing/resetting a demo user means editing
  `scripts/seed_db.py` and doing a fresh reseed
- A wired-up distinction between Admin and Underwriter

## Retraining the model

```bash
python scripts/train_model.py   # rewrites model/avm_lgbm.joblib + model/feature_spec.json
```

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

## Architecture

```
data/ames_raw.csv          De Cock Ames dataset (2,930 rows, zero-scrape ingestion)
scripts/train_model.py     LightGBM on log1p(SalePrice); 26 curated features
scripts/seed_db.py         DB instantiation + bank_portfolio_meta + image mapping
backend/app/
  models.py                properties / bank_portfolio_meta / property_images / system_logs / users
  auth.py                  bcrypt hashing + session-cookie get_current_user / require_role deps
  inference.py             AVM scoring + native TreeSHAP contributions (pred_contrib)
  logging_config.py        loguru setup: console, rotating file, and DB sinks
  main.py                  REST API (see below)
frontend/src/
  logger.js                loglevel wrapper: human-readable console + remote shipping
  copilot.js               page-agent setup: proxy baseURL, task context, chart summaries
  views/
    Login.jsx              Username/password login form
    Dashboard.jsx          View 1 — exposure, avg LTV, triage count, LTV histogram,
                           neighborhood concentration chart
    PortfolioGrid.jsx      View 2 — listing-style cards, filters, sort, CSV export
    Inspector.jsx          View 3 — glass-box matrix, SHAP widget, what-if scenario
                           panel, delta meter, audit lifecycle box (role-gated)
    ModelCard.jsx          View 4 — plain-language model card for non-technical auditors:
                           what the model does, holdout accuracy, training data
                           provenance, interactive global feature-importance chart,
                           limitations & appropriate use
```

### Key API endpoints

All endpoints below require a logged-in session unless noted; ⚑ marks Underwriter/Admin-only.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | Log in, set the session cookie (open) |
| POST | `/api/v1/auth/logout` | Clear the session |
| GET | `/api/v1/auth/me` | Current user, or 401 (frontend's session check) |
| GET | `/api/v1/portfolio/summary` | Macro banners + chart data |
| GET | `/api/v1/properties` | Filtered/paginated grid |
| GET | `/api/v1/properties/{pid}` | Full asset file + baseline SHAP |
| POST | `/api/v1/valuate` | Live what-if inference (±5% band + drivers) |
| PATCH | `/api/v1/properties/{pid}/audit` | ⚑ Underwriter notes + status writeback |
| GET | `/api/v1/properties/export` | Structural CSV download |
| GET | `/api/v1/model/spec` | Feature spec + holdout MAPE/R² (drives the UI + Model Card) |
| GET | `/api/v1/model/importance` | Portfolio-wide average TreeSHAP $ impact per feature, cached (Model Card chart) |
| GET | `/api/v1/logs` | ⚑ Query the unified operational/audit log ledger (supports `?actor=`) |
| POST | `/api/v1/logs/client` | Ingest batched frontend (loglevel) log entries (open — see Authentication & Roles) |
| POST | `/api/v1/copilot/chat/completions` | AI copilot LLM proxy (see below) |

### Design notes

- **Audit triage seeding** flags assets where |AVM − Sale| / Sale > 15%
  (Pending Review at 8–15%), producing a realistic queue: ~130 flagged, ~390 pending.
- **Explainability is real, not mocked**: LightGBM's `pred_contrib=True` returns exact
  TreeSHAP values; contributions are converted to dollar impact at the prediction point.
- **Loan balances** use a seeded RNG (deterministic across rebuilds).
- **Logging**: the backend (`loguru`) and frontend (`loglevel`) both log in a
  human-readable, timestamped format, and both feed the same `system_logs` table —
  request/inference telemetry, underwriter audit-trail events (status/notes changes,
  scenario re-valuations), and frontend errors/usage events all land in one place,
  queryable via `GET /api/v1/logs`. Every event is attributed to the authenticated
  session via `system_logs.actor` where one exists (see
  [Authentication & Roles](#authentication--roles-poc-grade)). Backend logs also go to a
  rotating `logs/backend.log` file for local debugging.
- Out of scope per PRD: multi-tenancy, geospatial map servers, document generation.
  Auth now exists in lightweight, PoC-grade form — see
  [Authentication & Roles](#authentication--roles-poc-grade).

## PRD success metrics

| Metric | Status |
|---|---|
| Zero-scrape ingestion | ✅ Ames CSV + programmatic image hooks only |
| Inference latency < 200 ms | ✅ ~40 ms measured round-trip |
| Cohesive UX story | ✅ Risk overview → listing grid → operational override panel |
