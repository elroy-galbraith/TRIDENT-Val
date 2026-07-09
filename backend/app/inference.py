"""AVM inference layer.

LightGBM's pred_contrib=True returns exact TreeSHAP values natively, so the
"Explainable AI widget" is backed by real per-feature contributions, not a mockup.
Contributions are computed in log-price space and converted to approximate dollar
impact around the prediction point.
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


@lru_cache(maxsize=1)
def get_model():
    return joblib.load(MODEL_DIR / "avm_lgbm.joblib")


@lru_cache(maxsize=1)
def get_spec() -> dict:
    return json.loads((MODEL_DIR / "feature_spec.json").read_text())


def build_frame(payloads: list[dict]) -> pd.DataFrame:
    spec = get_spec()
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


def predict(payloads: list[dict]) -> np.ndarray:
    X = build_frame(payloads)
    return np.expm1(get_model().predict(X))


def valuate_with_drivers(payload: dict, top_k: int = 3) -> dict:
    spec = get_spec()
    X = build_frame([payload])
    model = get_model()

    log_pred = model.predict(X)[0]
    value = float(np.expm1(log_pred))

    contrib = model.predict(X, pred_contrib=True)[0]  # per-feature SHAP + base value
    feat_contrib = contrib[:-1]
    # Convert log-space SHAP to approximate dollar impact at the prediction point.
    dollar = value * (1 - np.exp(-feat_contrib))

    pairs = sorted(zip(spec["features"], dollar), key=lambda t: t[1], reverse=True)
    fmt = lambda f, d: {"feature": f, "label": LABELS.get(f, f),
                        "value": payload.get(f), "impact_usd": round(float(d))}
    drivers = [fmt(f, d) for f, d in pairs[:top_k] if d > 0]
    detractors = [fmt(f, d) for f, d in sorted(pairs, key=lambda t: t[1])[:top_k] if d < 0]

    return {
        "estimated_market_value": round(value, 2),
        "error_band_pct": ERROR_BAND,
        "value_low": round(value * (1 - ERROR_BAND), 2),
        "value_high": round(value * (1 + ERROR_BAND), 2),
        "top_drivers": drivers,
        "top_detractors": detractors,
    }


def global_importance(payloads: list[dict]) -> dict:
    """Average |dollar impact| per feature across a population of properties.

    Same TreeSHAP (pred_contrib) machinery as valuate_with_drivers, run in one batch over
    the whole portfolio instead of a single property — this is what backs the Model Card's
    "what drives the model" chart. The caller is expected to cache the result: property
    feature vectors are immutable after seeding, so this doesn't need to re-run per request.
    """
    spec = get_spec()
    model = get_model()
    X = build_frame(payloads)

    log_pred = model.predict(X)
    values = np.expm1(log_pred)
    contrib = model.predict(X, pred_contrib=True)  # (n, n_features + 1); last col is base value
    feat_contrib = contrib[:, :-1]
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
