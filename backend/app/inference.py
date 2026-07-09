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
