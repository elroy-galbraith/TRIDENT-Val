# ADR 0002: Track model artifact and dataset in the repository

**Status:** Accepted · **Date:** 2026-07

## Context
The fitted LightGBM model (~1–2 MB) and the Ames source CSV (~1 MB) are required at
startup. Standard practice excludes binaries and data from git in favour of artifact
stores or download-on-build steps.

## Decision
Commit both `model/avm_lgbm.joblib` and `data/ames_raw.csv`. The repo must work
out-of-the-box: clone → compose up → seeded, scored portfolio, with no registry
credentials, download scripts, or retraining step.

## Consequences
- ~3 MB of repo weight; acceptable at PoC scale.
- Model version is pinned to the commit — an accidental reproducibility win that
  later feeds the model-registry design (ADR 0008).
- Does not scale to many/large models; revisit with an artifact store (or git-lfs)
  when the registry holds more than a handful of artifacts.

## Alternatives considered
- **Artifact store / release assets:** correct at production scale; rejected for PoC
  as it adds a failure mode to every fresh clone.
- **Train-on-first-boot:** rejected; adds minutes to startup and makes first-run
  behaviour non-deterministic across environments.
