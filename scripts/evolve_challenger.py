"""Evolves a third TRIDENT-Val AVM challenger with OpenEvolve, then materializes the winning
program into model/evolved_v1/ in the same {model.joblib, feature_spec.json, manifest.json}
shape scripts/train_model.py writes for lgbm_v1/linear_v1 — so it drops straight into the
existing champion/challenger registry via scripts/seed_db.py.

Uses the Claude Code CLI as OpenEvolve's LLM backend (see scripts/evolve/config.yaml) — no
API key needed, authentication is the CLI's own OAuth session (`claude login`).

This is a dev/tooling script, not part of the running app, so its dependencies
(openevolve, scikit-learn, pandas, numpy, lightgbm, joblib) aren't in
backend/requirements.txt. Install them into a throwaway venv before running:

    python3 -m venv .venv-evolve && source .venv-evolve/bin/activate
    pip install openevolve scikit-learn pandas numpy lightgbm joblib pyyaml

Usage:
    python scripts/evolve_challenger.py [--iterations N] [--output DIR]

    # Re-materialize an already-evolved program (e.g. after inspecting
    # scripts/evolve/openevolve_output/best/best_program.py) without re-running evolution:
    python scripts/evolve_challenger.py --code scripts/evolve/openevolve_output/best/best_program.py
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
EVOLVE_DIR = ROOT / "scripts" / "evolve"
MODEL_ID = "evolved_v1"

sys.path.insert(0, str(ROOT / "scripts"))
from train_model import CATEGORICAL, FEATURES, NUMERIC, ORDINAL, load_frame, prepare, write_artifact  # noqa: E402


def _load_evolved_module(code: str):
    tmp_path = EVOLVE_DIR / "_best_program.py"
    tmp_path.write_text(code)
    try:
        spec = importlib.util.spec_from_file_location("evolved_best", tmp_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        tmp_path.unlink()
    if not hasattr(module, "build_model"):
        raise RuntimeError("Evolved program has no build_model(...) function")
    return module


def materialize(best_code: str, evolution_iterations: int | None) -> None:
    """Fit the evolved build_model() on the same split scripts/train_model.py uses, score it,
    and write model/evolved_v1/{model.joblib, feature_spec.json, manifest.json} (plus a
    evolved_program.py transparency copy of the winning code)."""
    module = _load_evolved_module(best_code)

    df = load_frame()
    df = df[~((df["gr_liv_area"] > 4000) & (df["saleprice"] < 300000))]
    X = prepare(df)
    y = np.log1p(df["saleprice"])
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    categories = {c: sorted(map(str, X[c].cat.categories)) for c in CATEGORICAL}
    numeric_ordinal = NUMERIC + list(ORDINAL)

    print("Fitting evolved challenger on the training split...")
    model = module.build_model(X_tr, y_tr, categories, numeric_ordinal, CATEGORICAL)

    pred = np.expm1(model.predict(X_te))
    truth = np.expm1(y_te)
    mape = float(mean_absolute_percentage_error(truth, pred))
    r2 = float(r2_score(truth, pred))
    print(f"  Holdout: MAPE={mape:.3%}  R2={r2:.3f}")

    # Baseline reference point for the occlusion explainer: median (numeric/ordinal) or mode
    # (categorical) of the training split, computed once here rather than at inference time.
    baseline = {c: float(X_tr[c].median()) for c in numeric_ordinal}
    baseline.update({c: str(X_tr[c].mode().iloc[0]) for c in CATEGORICAL})

    trained_at = datetime.now(timezone.utc).isoformat()
    spec_json = {
        "features": FEATURES, "numeric": NUMERIC, "ordinal": dict(ORDINAL),
        "categorical": categories, "target": "saleprice", "target_transform": "log1p",
        "baseline": baseline,
        "holdout_mape": round(mape, 4), "holdout_r2": round(r2, 4),
    }
    manifest = {
        "id": MODEL_ID, "name": "TRIDENT AVM — Evolved Challenger", "version": "1.0",
        "architecture": "OpenEvolve-Discovered Ensemble (Claude Code CLI, scikit-learn-only "
            "search space)",
        "explainer": "occlusion",
        "description": "This model's feature engineering, estimator choice, and "
            "hyperparameters were not hand-designed — they were searched for by OpenEvolve "
            "(github.com/elroy-galbraith/openevolve), an LLM-driven evolutionary code search, "
            "run against the Claude Code CLI and scored on the same holdout split as the "
            "other two registered models. A third, independently-derived architecture, not a "
            "version bump of either, so its disagreements with the champion and linear "
            "challenger are a genuine third signal. See scripts/evolve/ for the search setup "
            "and scripts/evolve_challenger.py to re-run it; the exact winning program is "
            "saved alongside this manifest as evolved_program.py.",
        "holdout_mape": round(mape, 4), "holdout_r2": round(r2, 4),
        "trained_at": trained_at, "default_status": "Challenger",
        "evolution_iterations": evolution_iterations,
    }

    write_artifact(MODEL_ID, model, spec_json, manifest)
    (ROOT / "model" / MODEL_ID / "evolved_program.py").write_text(best_code)
    print(f"Wrote model/{MODEL_ID}/evolved_program.py (the winning evolved source)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iterations", type=int, default=None,
                     help="override scripts/evolve/config.yaml's max_iterations")
    ap.add_argument("--output", default=str(EVOLVE_DIR / "openevolve_output"),
                     help="OpenEvolve output dir (checkpoints, logs, best/)")
    ap.add_argument("--code", default=None,
                     help="skip evolution; materialize an already-evolved program file "
                          "directly (e.g. an openevolve_output/best/best_program.py)")
    args = ap.parse_args()

    config_iterations = yaml.safe_load((EVOLVE_DIR / "config.yaml").read_text()).get("max_iterations")

    if args.code:
        best_code = Path(args.code).read_text()
        materialize(best_code, evolution_iterations=args.iterations or config_iterations)
        return

    from openevolve import run_evolution  # deferred: only needed for a live evolution run

    iterations = args.iterations or config_iterations
    result = run_evolution(
        initial_program=str(EVOLVE_DIR / "initial_program.py"),
        evaluator=str(EVOLVE_DIR / "evaluator.py"),
        config=str(EVOLVE_DIR / "config.yaml"),
        iterations=iterations,
        output_dir=args.output,
        cleanup=False,
    )
    print(f"Evolution finished. best_score={result.best_score:.4f} metrics={result.metrics}")
    if not result.best_code:
        raise RuntimeError(
            f"OpenEvolve returned no best program — inspect {args.output}/logs for failures.")

    materialize(result.best_code, evolution_iterations=iterations)


if __name__ == "__main__":
    main()
