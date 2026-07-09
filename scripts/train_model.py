"""Train the TRIDENT-Val AVM on the Ames Housing dataset.

Outputs:
  model/avm_lgbm.joblib   - fitted LightGBM regressor (target = log1p(SalePrice))
  model/feature_spec.json - feature names, types, categories, ordinal maps (drives the UI)
"""
import json
import re
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split

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


def main() -> None:
    df = load_frame()
    # Drop the handful of partial/abnormal sales outliers De Cock flags (huge GrLivArea, low price)
    df = df[~((df["gr_liv_area"] > 4000) & (df["saleprice"] < 300000))]
    X = prepare(df)
    y = np.log1p(df["saleprice"])

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    model = lgb.LGBMRegressor(
        n_estimators=1200, learning_rate=0.03, num_leaves=48,
        subsample=0.8, colsample_bytree=0.8, random_state=42, verbosity=-1,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_te, y_te)],
              callbacks=[lgb.early_stopping(80, verbose=False)])

    pred = np.expm1(model.predict(X_te))
    truth = np.expm1(y_te)
    mape = mean_absolute_percentage_error(truth, pred)
    r2 = r2_score(truth, pred)
    print(f"Holdout: MAPE={mape:.3%}  R2={r2:.3f}  best_iter={model.best_iteration_}")

    joblib.dump(model, OUT / "avm_lgbm.joblib")

    spec = {
        "features": FEATURES,
        "numeric": NUMERIC,
        "ordinal": {k: v for k, v in ORDINAL.items()},
        "categorical": {c: sorted(map(str, X[c].cat.categories)) for c in CATEGORICAL},
        "target": "saleprice",
        "target_transform": "log1p",
        "holdout_mape": round(float(mape), 4),
        "holdout_r2": round(float(r2), 4),
    }
    (OUT / "feature_spec.json").write_text(json.dumps(spec, indent=2))
    print(f"Saved model + spec to {OUT}")


if __name__ == "__main__":
    main()
