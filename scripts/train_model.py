"""Train the TRIDENT-Val AVM model registry on the Ames Housing dataset.

Trains two architecturally distinct models against the same feature set and target so their
disagreement is a real, structural signal (not a version bump): a LightGBM gradient-boosted
ensemble (the champion — captures nonlinear interactions like quality x size) and a
regularized linear model (a challenger — a genuinely different architecture that visibly
underfits high-end and unusual properties, which is exactly what makes its disagreements
with the champion worth routing to a human).

Each model is written as a self-contained artifact under model/<model_id>/:
  model.joblib       - fitted estimator
  feature_spec.json  - feature names/types/categories/ordinal maps (drives the UI + inference)
  manifest.json       - registry metadata: name, version, architecture, explainer, metrics

scripts/seed_db.py reads every model/<model_id>/manifest.json to populate the `models`
registry table and shadow-scores the whole portfolio against each one.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "ames_raw.csv"
OUT = ROOT / "model"
OUT.mkdir(exist_ok=True)

QUAL_MAP = {"Ex": 5, "Gd": 4, "TA": 3, "Fa": 2, "Po": 1}
FUNC_MAP = {"Typ": 8, "Min1": 7, "Min2": 6, "Mod": 5, "Maj1": 4, "Maj2": 3, "Sev": 2, "Sal": 1}

NUMERIC = [
    "gr_liv_area", "total_bsmt_sf", "first_flr_sf", "garage_area", "garage_cars",
    "lot_area", "year_built", "year_remod_add", "full_bath", "half_bath",
    "bedroom_abvgr", "totrms_abvgrd", "fireplaces", "overall_qual", "overall_cond",
    "mas_vnr_area",
]
ORDINAL = {"kitchen_qual": QUAL_MAP, "exter_qual": QUAL_MAP, "bsmt_qual": QUAL_MAP,
           "heating_qc": QUAL_MAP, "functional": FUNC_MAP}
CATEGORICAL = ["neighborhood", "bldg_type", "house_style", "ms_zoning", "central_air"]
FEATURES = NUMERIC + list(ORDINAL) + CATEGORICAL
NUMERIC_ORDINAL = NUMERIC + list(ORDINAL)  # fixed prefix order shared with FEATURES


def snake(col: str) -> str:
    s = re.sub(r"[ /]", "_", col.strip()).lower()
    s = s.replace("1st_flr_sf", "first_flr_sf").replace("year_remod_add", "year_remod_add")
    return s


def load_frame() -> pd.DataFrame:
    df = pd.read_csv(RAW, index_col=0)
    df.columns = [snake(c) for c in df.columns]
    df = df.rename(columns={"year_remod/add": "year_remod_add"})
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    X = df.copy()
    for col in NUMERIC:
        X[col] = pd.to_numeric(X[col], errors="coerce").fillna(0)
    for col, mapping in ORDINAL.items():
        X[col] = X[col].map(mapping).fillna(3).astype(int)
    for col in CATEGORICAL:
        X[col] = X[col].fillna("NA").astype("category")
    return X[FEATURES]


def write_artifact(model_id: str, model, spec: dict, manifest: dict) -> None:
    d = OUT / model_id
    d.mkdir(exist_ok=True)
    joblib.dump(model, d / "model.joblib")
    (d / "feature_spec.json").write_text(json.dumps(spec, indent=2))
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  -> wrote {d}/{{model.joblib, feature_spec.json, manifest.json}}")


def main() -> None:
    df = load_frame()
    # Drop the handful of partial/abnormal sales outliers De Cock flags (huge GrLivArea, low price)
    df = df[~((df["gr_liv_area"] > 4000) & (df["saleprice"] < 300000))]
    X = prepare(df)
    y = np.log1p(df["saleprice"])

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    categories = {c: sorted(map(str, X[c].cat.categories)) for c in CATEGORICAL}
    trained_at = datetime.now(timezone.utc).isoformat()

    base_spec = {
        "features": FEATURES,
        "numeric": NUMERIC,
        "ordinal": {k: v for k, v in ORDINAL.items()},
        "categorical": categories,
        "target": "saleprice",
        "target_transform": "log1p",
    }

    # ---- Champion: LightGBM gradient-boosted trees ----
    print("Training champion: LightGBM...")
    lgbm = lgb.LGBMRegressor(
        n_estimators=1200, learning_rate=0.03, num_leaves=48,
        subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1,
    )
    lgbm.fit(X_tr, y_tr, eval_set=[(X_te, y_te)],
             callbacks=[lgb.early_stopping(80, verbose=False)])
    lgbm_pred = np.expm1(lgbm.predict(X_te))
    truth = np.expm1(y_te)
    lgbm_mape = mean_absolute_percentage_error(truth, lgbm_pred)
    lgbm_r2 = r2_score(truth, lgbm_pred)
    print(f"  Holdout: MAPE={lgbm_mape:.3%}  R2={lgbm_r2:.3f}  best_iter={lgbm.best_iteration_}")

    write_artifact(
        "lgbm_v1", lgbm,
        {**base_spec, "holdout_mape": round(float(lgbm_mape), 4),
         "holdout_r2": round(float(lgbm_r2), 4)},
        {
            "id": "lgbm_v1", "name": "TRIDENT AVM — LightGBM", "version": "1.0",
            "architecture": "LightGBM Gradient-Boosted Trees",
            "explainer": "tree_shap",
            "description": "Hundreds of shallow decision trees built sequentially, each "
                "correcting the errors of the ones before it. Captures nonlinear effects and "
                "feature interactions (e.g. size matters more in some neighborhoods than "
                "others) that a linear model cannot represent.",
            "holdout_mape": round(float(lgbm_mape), 4),
            "holdout_r2": round(float(lgbm_r2), 4),
            "trained_at": trained_at,
            "default_status": "Champion",
        },
    )

    # ---- Challenger: regularized linear model (genuinely different architecture) ----
    print("Training challenger: Ridge linear regression...")
    prep = ColumnTransformer(transformers=[
        ("num", StandardScaler(), NUMERIC_ORDINAL),
        ("cat", OneHotEncoder(categories=[categories[c] for c in CATEGORICAL],
                              handle_unknown="ignore"), CATEGORICAL),
    ])
    linear = Pipeline(steps=[("prep", prep), ("reg", Ridge(alpha=5.0, random_state=42))])
    linear.fit(X_tr, y_tr)
    linear_pred = np.expm1(linear.predict(X_te))
    linear_mape = mean_absolute_percentage_error(truth, linear_pred)
    linear_r2 = r2_score(truth, linear_pred)
    print(f"  Holdout: MAPE={linear_mape:.3%}  R2={linear_r2:.3f}")

    write_artifact(
        "linear_v1", linear,
        {**base_spec, "holdout_mape": round(float(linear_mape), 4),
         "holdout_r2": round(float(linear_r2), 4)},
        {
            "id": "linear_v1", "name": "TRIDENT AVM — Ridge Linear", "version": "1.0",
            "architecture": "Ridge Linear Regression (L2-regularized)",
            "explainer": "linear_coef",
            "description": "A single weighted sum of the inputs — every feature gets one "
                "fixed coefficient applied the same way to every property. Simpler and more "
                "transparent than the champion, but structurally unable to represent "
                "interaction effects, so it tends to diverge most on high-end and unusual "
                "properties where those interactions matter most.",
            "holdout_mape": round(float(linear_mape), 4),
            "holdout_r2": round(float(linear_r2), 4),
            "trained_at": trained_at,
            "default_status": "Challenger",
        },
    )

    print(f"Done. Registered models: lgbm_v1 (champion), linear_v1 (challenger) under {OUT}")


if __name__ == "__main__":
    main()
