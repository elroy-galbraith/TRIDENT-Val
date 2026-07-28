"""OpenEvolve evaluator for the evolved TRIDENT-Val AVM challenger.

Trains the candidate program's build_model() against the exact same Ames Housing split
scripts/train_model.py uses for lgbm_v1/linear_v1 (same outlier drop, same 80/20 holdout
via train_test_split(test_size=0.2, random_state=42), same log1p(SalePrice) target) so the
resulting holdout MAPE/R2 is directly comparable to the champion's stated 7.9% MAPE / 0.94 R2.
"""
import importlib.util
import sys
import traceback
from pathlib import Path

import numpy as np
from openevolve.evaluation_result import EvaluationResult
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from train_model import CATEGORICAL, FEATURES, NUMERIC, ORDINAL, load_frame, prepare  # noqa: E402

NUMERIC_ORDINAL = NUMERIC + list(ORDINAL)

_SPLIT_CACHE = None


def _load_split():
    """Cached per-process: the CSV load/prep/split is identical every generation."""
    global _SPLIT_CACHE
    if _SPLIT_CACHE is None:
        df = load_frame()
        # Mirrors scripts/train_model.py main(): drop De Cock's flagged partial/abnormal
        # sale outliers before splitting.
        df = df[~((df["gr_liv_area"] > 4000) & (df["saleprice"] < 300000))]
        X = prepare(df)
        y = np.log1p(df["saleprice"])
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
        categories = {c: sorted(map(str, X[c].cat.categories)) for c in CATEGORICAL}
        _SPLIT_CACHE = (X_tr, X_te, y_tr, y_te, categories)
    return _SPLIT_CACHE


def _error_result(error_type: str, message: str, suggestion: str) -> EvaluationResult:
    return EvaluationResult(
        metrics={"combined_score": 0.0, "error": message},
        artifacts={"error_type": error_type, "error_message": message, "suggestion": suggestion},
    )


def evaluate(program_path):
    try:
        spec = importlib.util.spec_from_file_location("evolved_program", program_path)
        program = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(program)
    except Exception as e:
        return EvaluationResult(
            metrics={"combined_score": 0.0, "error": str(e)},
            artifacts={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "full_traceback": traceback.format_exc()[-2000:],
                "suggestion": "Program failed to import — check for syntax errors or "
                              "disallowed imports (only sklearn/pandas/numpy are available).",
            },
        )

    if not hasattr(program, "build_model"):
        return _error_result(
            "MissingFunction", "Program is missing required 'build_model' function",
            "Define build_model(X_train, y_train, categories, numeric_ordinal, categorical) "
            "returning a fitted estimator with .predict(X).",
        )

    X_tr, X_te, y_tr, y_te, categories = _load_split()

    try:
        model = program.build_model(X_tr, y_tr, categories, NUMERIC_ORDINAL, CATEGORICAL)
    except Exception as e:
        return EvaluationResult(
            metrics={"combined_score": 0.0, "error": str(e)},
            artifacts={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "full_traceback": traceback.format_exc()[-2000:],
                "suggestion": "build_model raised during fit — check estimator params and "
                              "that only scikit-learn/pandas/numpy are used.",
            },
        )

    if model is None or not hasattr(model, "predict"):
        return _error_result(
            "InvalidReturn", "build_model did not return an object with .predict(X)",
            "Return the fitted estimator/pipeline itself, not None or a metrics dict.",
        )

    try:
        pred_log = np.asarray(model.predict(X_te), dtype=float)
    except Exception as e:
        return EvaluationResult(
            metrics={"combined_score": 0.0, "error": str(e)},
            artifacts={
                "error_type": type(e).__name__,
                "error_message": str(e),
                "full_traceback": traceback.format_exc()[-2000:],
                "suggestion": "predict(X) raised on the holdout split — make sure it accepts "
                              "a DataFrame with the same columns/dtypes as X_train.",
            },
        )

    if pred_log.shape[0] != len(X_te) or not np.all(np.isfinite(pred_log)):
        return _error_result(
            "NonFinitePredictions", "predict(X) returned NaN/Inf or the wrong shape",
            "Check for divide-by-zero, log of a non-positive value, or unfitted transformers.",
        )

    pred = np.expm1(pred_log)
    truth = np.expm1(y_te)
    mape = float(mean_absolute_percentage_error(truth, pred))
    r2 = float(r2_score(truth, pred))

    # Reward both accuracy metrics, weighted toward MAPE (the headline metric the champion
    # and challenger are already scored on). Clamp r2 at 0 so a badly negative R2 doesn't
    # push combined_score negative and destabilize MAP-Elites binning.
    mape_score = max(0.0, 1.0 - mape)
    r2_component = max(0.0, r2)
    combined_score = float(0.7 * mape_score + 0.3 * r2_component)

    return EvaluationResult(
        metrics={
            "mape": round(mape, 4),
            "r2": round(r2, 4),
            "combined_score": combined_score,
        },
        artifacts={
            "holdout_mape_pct": f"{mape:.2%}",
            "holdout_r2": f"{r2:.3f}",
            "champion_reference": "LightGBM champion holdout: MAPE 7.9%, R2 0.94 — beating "
                                   "this isn't required, but a challenger this far off is "
                                   "not a useful governance signal.",
        },
    )
