# ADR 0018: OpenEvolve-searched architecture for the third AVM challenger

**Status:** Accepted · **Date:** 2026-07

## Context
The champion/challenger registry (ADR 0008) already supported any number of challengers,
not just the original two (`lgbm_v1`, `linear_v1`). The two existing models were both
hand-picked architectures. The question was whether a third challenger's architecture could
instead be *searched for* — using [OpenEvolve](https://github.com/elroy-galbraith/openevolve),
an LLM-driven evolutionary code search (MAP-Elites quality-diversity across islands), with
the Claude Code CLI as the LLM backend (no API key to provision — auth is the CLI's own
OAuth session) — and whether the result would be a legitimate registry entry rather than a
novelty.

## Decision
Use OpenEvolve to search for `evolved_v1`'s architecture, with a hard boundary between what
the search can and can't touch:

- `scripts/evolve/initial_program.py` — the `EVOLVE-BLOCK` wraps only `build_model(...)`, a
  function, not the whole pipeline. Data loading, feature prep, and the holdout split are
  fixed, identical to `scripts/train_model.py`, and live *outside* the block — not mutable.
- `scripts/evolve/evaluator.py` — scores every generation against the *exact same* holdout
  split and metrics (MAPE/R²) the champion and linear challenger are scored on, so results
  are comparable across the registry, not just internally consistent.
- `config.yaml`'s system message enforces hard constraints (scikit-learn/pandas/numpy only,
  fixed function signature, bounded fit time, no network access) — these aren't style
  guidance, they're what keeps every generation runnable at all.
- Explainability is handled generically (`occlusion`, in `backend/app/inference.py`) since
  the winning architecture isn't known ahead of time and can't rely on a native method the
  way the champion (TreeSHAP) or linear challenger (coefficients) can.
- The seed program is deliberately simple and a different family from both existing models
  (bagged `ExtraTreesRegressor`), not a strong baseline — see the seeding guidance below for
  why that was a deliberate choice tied to the goal, not a default.

## Consequences
- **It worked, not just as a demo.** 15 generations produced a `VotingRegressor` blend of
  `ExtraTreesRegressor`, `HistGradientBoostingRegressor`, and `KNeighborsRegressor` that beat
  the champion's holdout MAPE (7.82% vs. 7.88%) while tying its R² (0.9415) — a genuinely
  competitive, structurally independent result, not a toy.
- **Repo weight is no longer negligible.** Even joblib-compressed (`compress=3`, added to
  `scripts/train_model.py`'s `write_artifact`), `evolved_v1` is ~17 MB against the champion's
  ~1.2 MB. ADR 0002 flagged "revisit with an artifact store... when the registry holds more
  than a handful of artifacts" — three models is still fine, but this is real progress toward
  that threshold, not free.
- **Registering a new model still means a full reseed.** This repo has no incremental
  migration path (by design — see the "Out of scope" note in the README); adding a model to
  a *live* deployed environment means rerunning `scripts/seed_db.py`'s `drop_all`/`create_all`
  against production, not inserting one row. Discovered directly when deploying this model:
  the Cloud Run image redeploys automatically on push, but the Postgres registry does not
  update itself. Worth solving with an incremental registration path before evolving
  challengers becomes routine rather than a one-off.
- **Cost is real but small.** ~10–15 minutes and a modest number of Claude Code CLI calls per
  15-generation run — cheap enough to iterate on, not free enough to run on every push.

## Guidance for future runs
Two open questions came up while building this that are more useful as standing guidance
than as one-time decisions:

- **Never let the `EVOLVE-BLOCK` reach the evaluator or the data split.** The value of the
  comparison depends entirely on every model being scored the same way. An evolved program
  that can edit its own scoring function has an easy, uninteresting way to "win."
- **Whether to seed with a strong baseline (e.g. an AutoML-selected model) depends on which
  goal is active, and the two goals want opposite seeds:**
  - *Optimizing for raw accuracy:* seed with the AutoML result. OpenEvolve will still mutate
    it, but its comparatively expensive LLM-generation budget is then spent on the part
    that's genuinely hard to automate (feature engineering, blending in a different
    component, reacting to evaluator artifacts) rather than re-deriving a hyperparameter
    search an AutoML tool already does more efficiently.
  - *Optimizing for structural diversity* (the actual goal for `evolved_v1` — the registry's
    value comes from three models failing differently, not one model scoring highest): seed
    simply. AutoML on tabular data reliably converges on the same handful of families
    (gradient boosting variants, random forests) this exercise was trying to diversify away
    from; a strong AutoML seed risks anchoring the search on "refine this ensemble" instead
    of "find something structurally different."
  - Middle ground worth trying: don't seed with the AutoML program's *code* at all — feed its
    score into the evaluator's artifacts as a reference/calibration point instead, so the
    search has a target without inheriting AutoML's architectural bias.
  - This is empirically testable, not just arguable: run two populations under the same
    iteration budget, one naively seeded, one AutoML-seeded, and compare where they land
    before committing to a seeding strategy for a given goal.

## Alternatives considered
- **Hand-design a third architecture** (e.g. pick RandomForest or XGBoost by hand): not
  wrong, but doesn't test whether a search finds something a person wouldn't have picked,
  which was the point of trying this approach.
- **Seed `evolved_v1`'s search with a strong/AutoML baseline:** rejected for this run
  specifically, since the goal was a structurally distinct third model for the disagreement
  queue, not the single highest-scoring model — see the seeding guidance above for when to
  revisit this per-run.
- **A hosted LLM API (OpenAI/Gemini) as OpenEvolve's backend:** rejected in favor of the
  Claude Code CLI provider — no API key or secret to provision, rotate, or budget separately
  for a dev-tooling script; authentication is the CLI's own OAuth session.
