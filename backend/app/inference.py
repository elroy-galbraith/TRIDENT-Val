"""AVM inference layer — model-registry aware.

Every registered model lives under model/<model_id>/ as three files:
  model.joblib       - fitted estimator (LightGBM booster, or an sklearn Pipeline)
  feature_spec.json  - feature names, types, categories, ordinal maps (drives the UI)
  manifest.json       - registry metadata: name, version, architecture, explainer, metrics

Both currently-supported architectures predict log1p(SalePrice), so `predict()` is
architecture-agnostic. Explainability is dispatched on manifest["explainer"]:
  - "tree_shap"   - LightGBM's pred_contrib=True returns exact TreeSHAP values natively.
  - "linear_coef" - exact per-feature attribution from a linear model's own coefficients
                    (transformed-column contributions summed back to the original feature).
Neither is an approximation of the model's own reasoning — both are the model explaining
itself, just via the mechanics native to its architecture.  Contributions are computed in
log-price space and converted to approximate dollar impact around the prediction point.
"""
import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parents[2] / "model"
ERROR_BAND = 0.05  # +/- 5% per PRD

LABELS = {
    "gr_liv_area": "Above Ground Living Area", "total_bsmt_sf": "Basement Area",
    "first_flr_sf": "First Floor Area", "garage_area": "Garage Area",
    "garage_cars": "Garage Capacity", "lot_area": "Lot Area",
    "year_built": "Year Built", "year_remod_add": "Year Remodeled",
    "full_bath": "Full Baths", "half_bath": "Half Baths",
    "bedroom_abvgr": "Bedrooms", "totrms_abvgrd": "Total Rooms",
    "fireplaces": "Fireplaces", "overall_qual": "Overall Quality",
    "overall_cond": "Overall Condition", "mas_vnr_area": "Masonry Veneer Area",
    "kitchen_qual": "Kitchen Quality", "exter_qual": "Exterior Quality",
    "bsmt_qual": "Basement Quality", "heating_qc": "Heating Quality",
    "functional": "Functional Deficiency", "neighborhood": "Neighborhood",
    "bldg_type": "Building Type", "house_style": "House Style",
    "ms_zoning": "Zoning", "central_air": "Central Air",
}

# One plain-language sentence per feature for the Model Card page — written for a
# non-technical auditor, not a data scientist.
FEATURE_EXPLANATIONS = {
    "gr_liv_area": "Total finished living space above ground, in square feet. Larger homes "
        "almost always score higher.",
    "total_bsmt_sf": "Total basement square footage, finished or not — extra usable area even "
        "when it isn't \"living space\" on paper.",
    "first_flr_sf": "Square footage of the first (ground) floor.",
    "garage_area": "Garage square footage.",
    "garage_cars": "How many cars the garage can hold.",
    "lot_area": "Total lot size in square feet, including yard and driveway.",
    "year_built": "Original construction year — newer homes generally score higher unless "
        "offset by a strong remodel.",
    "year_remod_add": "Year of the most recent remodel or addition (equals Year Built if the "
        "home was never remodeled).",
    "full_bath": "Number of full bathrooms above ground.",
    "half_bath": "Number of half bathrooms (sink + toilet, no shower/tub) above ground.",
    "bedroom_abvgr": "Bedrooms located above ground; basement bedrooms aren't counted here.",
    "totrms_abvgrd": "Total rooms above ground, excluding bathrooms.",
    "fireplaces": "Number of fireplaces.",
    "overall_qual": "Overall material and finish quality, rated 1 (very poor) to 10 "
        "(excellent) by the original assessor. Typically the single strongest driver.",
    "overall_cond": "Overall upkeep/condition, rated 1 to 10 — distinct from quality, which is "
        "about materials, not maintenance.",
    "mas_vnr_area": "Masonry veneer area (brick or stone facing), in square feet.",
    "kitchen_qual": "Kitchen quality rating: Excellent, Good, Typical/Average, Fair, or Poor.",
    "exter_qual": "Exterior material quality, same Excellent-to-Poor scale.",
    "bsmt_qual": "Basement quality rating, based on ceiling height and finish.",
    "heating_qc": "Heating system quality and condition rating.",
    "functional": "Functionality deductions — flags typical homes vs. ones with known "
        "deficiencies (e.g. needed repairs).",
    "neighborhood": "Ames, Iowa neighborhood or subdivision — the model's strongest proxy for "
        "location.",
    "bldg_type": "Building type: single-family, duplex, or townhouse variants.",
    "house_style": "Architectural style — e.g. one-story, two-story, split-level.",
    "ms_zoning": "General zoning classification (residential low/medium density, commercial, "
        "etc.).",
    "central_air": "Whether the home has central air conditioning.",
}


class UnknownModelError(KeyError):
    pass


def _model_path(model_id: str) -> Path:
    # model_id is attacker-controlled (a URL path parameter) — resolve and confirm the
    # result is still inside MODEL_DIR before touching the filesystem. Without this, a
    # value like "../../etc" or an absolute path resets the join entirely (a well-known
    # pathlib gotcha: Path("/a") / "/etc" == Path("/etc")) and escapes MODEL_DIR.
    d = (MODEL_DIR / model_id).resolve()
    model_root = MODEL_DIR.resolve()
    if d != model_root and model_root not in d.parents:
        raise UnknownModelError(f"No registered model artifact at model/{model_id}/")
    if not (d / "manifest.json").exists():
        raise UnknownModelError(f"No registered model artifact at model/{model_id}/")
    return d


@lru_cache(maxsize=None)
def list_model_ids() -> tuple[str, ...]:
    """Every model_id with a manifest under model/ — the on-disk registry."""
    if not MODEL_DIR.exists():
        return ()
    return tuple(sorted(
        d.name for d in MODEL_DIR.iterdir() if (d / "manifest.json").exists()
    ))


@lru_cache(maxsize=None)
def get_manifest(model_id: str) -> dict:
    return json.loads((_model_path(model_id) / "manifest.json").read_text())


@lru_cache(maxsize=None)
def get_model(model_id: str):
    return joblib.load(_model_path(model_id) / "model.joblib")


@lru_cache(maxsize=None)
def get_spec(model_id: str) -> dict:
    return json.loads((_model_path(model_id) / "feature_spec.json").read_text())


def build_frame(payloads: list[dict], model_id: str) -> pd.DataFrame:
    spec = get_spec(model_id)
    rows = []
    for p in payloads:
        row = {}
        for f in spec["numeric"]:
            row[f] = float(p.get(f, 0) or 0)
        for f, mapping in spec["ordinal"].items():
            v = p.get(f, 3)
            row[f] = int(mapping.get(v, v) if isinstance(v, str) else v)
        for f in spec["categorical"]:
            row[f] = str(p.get(f, "NA"))
        rows.append(row)
    X = pd.DataFrame(rows)[spec["features"]]
    for f, cats in spec["categorical"].items():
        X[f] = pd.Categorical(X[f], categories=cats)
    return X


def predict(payloads: list[dict], model_id: str) -> np.ndarray:
    X = build_frame(payloads, model_id)
    return np.expm1(get_model(model_id).predict(X))


def _tree_shap_contrib(model, X: pd.DataFrame) -> np.ndarray:
    contrib = model.predict(X, pred_contrib=True)  # (n, n_features + 1); last col is base value
    return contrib[:, :-1]


def _linear_contrib(model, spec: dict, X: pd.DataFrame) -> np.ndarray:
    """Exact per-original-feature attribution for an sklearn Pipeline(prep, reg) fit on
    log1p(price), where `prep` is a ColumnTransformer([("num", scaler, numeric+ordinal),
    ("cat", one_hot, categorical)]) built with explicit column order matching spec["features"]
    and explicit `categories=` matching spec["categorical"] (see scripts/train_model.py) —
    so transformed-column groups are contiguous and their boundaries are derivable from the
    spec alone, with no dependence on sklearn's get_feature_names_out().
    """
    prep, reg = model.named_steps["prep"], model.named_steps["reg"]
    Xt = prep.transform(X)
    if hasattr(Xt, "toarray"):
        Xt = Xt.toarray()
    contrib_t = Xt * reg.coef_

    n_num_ord = len(spec["numeric"]) + len(spec["ordinal"])
    out = np.zeros((X.shape[0], len(spec["features"])))
    out[:, :n_num_ord] = contrib_t[:, :n_num_ord]
    col = n_num_ord
    for i, catf in enumerate(spec["categorical"]):
        width = len(spec["categorical"][catf])
        out[:, n_num_ord + i] = contrib_t[:, col:col + width].sum(axis=1)
        col += width
    return out


def _contributions(model_id: str, X: pd.DataFrame) -> np.ndarray:
    manifest = get_manifest(model_id)
    model = get_model(model_id)
    spec = get_spec(model_id)
    if manifest["explainer"] == "tree_shap":
        return _tree_shap_contrib(model, X)
    if manifest["explainer"] == "linear_coef":
        return _linear_contrib(model, spec, X)
    raise ValueError(f"Unknown explainer type for model {model_id!r}: {manifest['explainer']!r}")


def valuate_with_drivers(payload: dict, model_id: str, top_k: int = 3) -> dict:
    spec = get_spec(model_id)
    X = build_frame([payload], model_id)
    model = get_model(model_id)

    log_pred = model.predict(X)[0]
    value = float(np.expm1(log_pred))

    feat_contrib = _contributions(model_id, X)[0]
    # Convert log-space contributions to approximate dollar impact at the prediction point.
    dollar = value * (1 - np.exp(-feat_contrib))

    pairs = sorted(zip(spec["features"], dollar), key=lambda t: t[1], reverse=True)
    fmt = lambda f, d: {"feature": f, "label": LABELS.get(f, f),
                        "value": payload.get(f), "impact_usd": round(float(d))}
    drivers = [fmt(f, d) for f, d in pairs[:top_k] if d > 0]
    detractors = [fmt(f, d) for f, d in sorted(pairs, key=lambda t: t[1])[:top_k] if d < 0]

    return {
        "model_id": model_id,
        "estimated_market_value": round(value, 2),
        "error_band_pct": ERROR_BAND,
        "value_low": round(value * (1 - ERROR_BAND), 2),
        "value_high": round(value * (1 + ERROR_BAND), 2),
        "top_drivers": drivers,
        "top_detractors": detractors,
    }


def valuate_batch_with_drivers(payloads: list[dict], model_id: str, top_k: int = 3) -> list[dict]:
    """Same output shape as valuate_with_drivers, vectorized over a whole population in one
    pass — used at seed time to shadow-score every registered model against the full
    portfolio without re-running build_frame/contributions once per property."""
    if not payloads:
        return []

    spec = get_spec(model_id)
    model = get_model(model_id)
    X = build_frame(payloads, model_id)

    log_pred = model.predict(X)
    values = np.expm1(log_pred)
    feat_contrib = _contributions(model_id, X)
    dollar = values[:, None] * (1 - np.exp(-feat_contrib))

    fmt = lambda p, f, d: {"feature": f, "label": LABELS.get(f, f),
                           "value": p.get(f), "impact_usd": round(float(d))}
    results = []
    for i, payload in enumerate(payloads):
        pairs = sorted(zip(spec["features"], dollar[i]), key=lambda t: t[1], reverse=True)
        value = float(values[i])
        results.append({
            "model_id": model_id,
            "estimated_market_value": round(value, 2),
            "error_band_pct": ERROR_BAND,
            "value_low": round(value * (1 - ERROR_BAND), 2),
            "value_high": round(value * (1 + ERROR_BAND), 2),
            "top_drivers": [fmt(payload, f, d) for f, d in pairs[:top_k] if d > 0],
            "top_detractors": [fmt(payload, f, d) for f, d in
                               sorted(pairs, key=lambda t: t[1])[:top_k] if d < 0],
        })
    return results


def global_importance(payloads: list[dict], model_id: str) -> dict:
    """Average |dollar impact| per feature across a population of properties.

    Same explainability machinery as valuate_with_drivers, run in one batch over the whole
    portfolio instead of a single property — this is what backs each model's Model Card
    "what drives the model" chart. The caller is expected to cache the result per model_id:
    property feature vectors are immutable after seeding, so this doesn't need to re-run
    per request.
    """
    if not payloads:  # e.g. requested before seeding has populated the properties table
        return {"sample_size": 0, "drivers": []}

    spec = get_spec(model_id)
    model = get_model(model_id)
    X = build_frame(payloads, model_id)

    log_pred = model.predict(X)
    values = np.expm1(log_pred)
    feat_contrib = _contributions(model_id, X)
    dollar = values[:, None] * (1 - np.exp(-feat_contrib))

    mean_abs = np.abs(dollar).mean(axis=0)
    mean_signed = dollar.mean(axis=0)
    total = float(mean_abs.sum()) or 1.0

    ranked = sorted(zip(spec["features"], mean_abs, mean_signed), key=lambda t: t[1], reverse=True)
    return {
        "sample_size": len(payloads),
        "drivers": [
            {
                "feature": f,
                "label": LABELS.get(f, f),
                "explanation": FEATURE_EXPLANATIONS.get(f, ""),
                "mean_abs_impact_usd": round(float(a)),
                "mean_signed_impact_usd": round(float(s)),
                "share_pct": round(float(a) / total, 4),
            }
            for f, a, s in ranked
        ],
    }
