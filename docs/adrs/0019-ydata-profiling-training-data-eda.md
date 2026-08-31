# ADR 0019: ydata-profiling for training-data EDA, baked at Docker build time

**Status:** Accepted · **Date:** 2026-08

## Context
There was no way for a data analyst or scientist to inspect the distribution,
missingness, or summary statistics of the Ames training data the AVM models are fit
on — only the curated, already-scored `properties` view the rest of the app shows.
[ydata-profiling](https://github.com/ydataai/ydata-profiling) generates a standard,
self-contained HTML EDA report from a DataFrame. The backend already depends on
pandas/numpy/scikit-learn, so adding it is a `pip install`, not a new stack.

## Decision
Add `ydata-profiling` to `backend/requirements.txt`. A new script,
`scripts/generate_profile_report.py`, builds the report over the same
feature-normalized view of `data/ames_raw.csv` that `scripts/train_model.py` and
`scripts/seed_db.py` already derive (via `train_model.load_frame`), plus the sale
price target, and writes it to `model/data_profile/report.html`.

The report is generated once, at Docker image build time (a `RUN` step in
`backend/Dockerfile`, after `COPY data`/`COPY scripts`), not at container startup or
on demand per request:
- No DB connection is needed — it's the same static Ames CSV `seed_db.py` loads.
- Keeps the request path free of an expensive computation (~1 minute locally in full
  mode, including correlations and pairwise interactions, over the full 2,930-row
  dataset).
- Follows ADR-0002's precedent: bake data-derived artifacts into the image rather
  than add a job queue or object store this PoC doesn't otherwise need.

`GET /api/v1/reports/data-profile` (Admin-gated, same as the Manager dashboard)
serves the built HTML file directly. The frontend adds an Admin-only "Data Profile"
tab that embeds it in an iframe — ydata-profiling's report bundles its own
Bootstrap/jQuery, which would collide with the app's Tailwind/React DOM if inlined
directly.

## Consequences
- +1 dependency, and a build step that adds report-generation time (~1 minute at
  ~2,930 rows, full mode) to every image build.
- The report reflects `data/ames_raw.csv` as of that image's build. It does not
  cover properties added at seed time beyond the raw CSV (there are none today), and
  needs a rebuild, not just a redeploy, to refresh after the source data changes.
- Full mode (correlations + pairwise interactions) is on by default: bivariate
  relationships are central to EDA, and at this dataset's size the cost (~1 minute
  build time, ~14 MB report vs. ~9s/~1.7 MB in `minimal` mode) is easily worth it.
  Revisit toward `minimal=True` only if the dataset grows enough that build time or
  report size becomes a real problem.
- Admin-gated because the report exposes full per-feature distributions and sample
  rows of the underlying data — the same sensitivity bar as the Manager dashboard.

## Alternatives considered
- **Generate at container startup (`scripts/wait_and_seed.py`):** rejected — adds to
  boot time on every container start for output that doesn't change between deploys
  of the same data.
- **On-demand endpoint profiling live `properties` rows per request:** most
  flexible (reflects live DB state), but needs response caching/streaming to avoid
  blocking a request thread on every hit, and there's no background-job
  infrastructure yet to do that cleanly. Revisit once real data ingestion (ADR-0012)
  lands and "training data" is no longer a static, in-repo CSV.
