# TRIDENT-Val — Residential Portfolio AVM & Risk Triage Engine (PoC)

End-to-end sandbox per PRD v1.0: LightGBM AVM trained on the Ames Housing Dataset (2,930 assets),
FastAPI inference service, PostgreSQL portfolio book, and a three-view React/Tailwind workbench
for risk officers and underwriters.

**Holdout accuracy:** MAPE 7.9%, R² 0.94. **Live inference latency:** ~40 ms round-trip.

## Quickstart — Docker (recommended, matches PRD stack)

```bash
docker compose up --build
```

- App: http://localhost:8080
- API docs (Swagger): http://localhost:8000/docs

First boot trains nothing (the fitted model ships in `model/`) and auto-seeds Postgres:
2,930 properties, simulated loan balances at 60–90% of baseline sale price, variance-based
audit triage, and deterministic Unsplash image mapping. Seeding is idempotent.

## Quickstart — no Docker (SQLite fallback)

```bash
pip install -r backend/requirements.txt
PYTHONPATH=scripts python scripts/seed_db.py          # creates ./trident.db
cd backend && uvicorn app.main:app --port 8000        # terminal 1
cd frontend && npm install && npm run dev             # terminal 2 -> http://localhost:5173
```

On Windows PowerShell replace the seed line with:
`$env:PYTHONPATH="scripts"; python scripts/seed_db.py`

## Retraining the model

```bash
python scripts/train_model.py   # rewrites model/avm_lgbm.joblib + model/feature_spec.json
```

## Architecture

```
data/ames_raw.csv          De Cock Ames dataset (2,930 rows, zero-scrape ingestion)
scripts/train_model.py     LightGBM on log1p(SalePrice); 26 curated features
scripts/seed_db.py         DB instantiation + bank_portfolio_meta + image mapping
backend/app/
  models.py                properties / bank_portfolio_meta / property_images / system_logs
  inference.py             AVM scoring + native TreeSHAP contributions (pred_contrib)
  logging_config.py        loguru setup: console, rotating file, and DB sinks
  main.py                  REST API (see below)
frontend/src/
  logger.js                loglevel wrapper: human-readable console + remote shipping
  views/
    Dashboard.jsx          View 1 — exposure, avg LTV, triage count, LTV histogram,
                           neighborhood concentration chart
    PortfolioGrid.jsx      View 2 — listing-style cards, filters, sort, CSV export
    Inspector.jsx          View 3 — glass-box matrix, SHAP widget, what-if scenario
                           panel, delta meter, audit lifecycle box
```

### Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/portfolio/summary` | Macro banners + chart data |
| GET | `/api/v1/properties` | Filtered/paginated grid |
| GET | `/api/v1/properties/{pid}` | Full asset file + baseline SHAP |
| POST | `/api/v1/valuate` | Live what-if inference (±5% band + drivers) |
| PATCH | `/api/v1/properties/{pid}/audit` | Underwriter notes + status writeback |
| GET | `/api/v1/properties/export` | Structural CSV download |
| GET | `/api/v1/logs` | Query the unified operational/audit log ledger |
| POST | `/api/v1/logs/client` | Ingest batched frontend (loglevel) log entries |

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
  queryable via `GET /api/v1/logs`. Backend logs also go to a rotating `logs/backend.log`
  file for local debugging.
- Out of scope per PRD: auth/multi-tenancy, geospatial map servers, document generation.

## PRD success metrics

| Metric | Status |
|---|---|
| Zero-scrape ingestion | ✅ Ames CSV + programmatic image hooks only |
| Inference latency < 200 ms | ✅ ~40 ms measured round-trip |
| Cohesive UX story | ✅ Risk overview → listing grid → operational override panel |
