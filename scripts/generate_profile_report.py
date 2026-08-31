"""Generate a static ydata-profiling EDA report over the AVM training data.

Run at Docker build time (see backend/Dockerfile), not at container startup or on
request: this is the same static `data/ames_raw.csv` scripts/seed_db.py loads, so
no DB connection is needed, and baking it into the image keeps the report available
with zero added container-boot time. Re-run manually (`python
scripts/generate_profile_report.py`) after changing the source data to refresh
model/data_profile/report.html locally.

Profiles the same feature-normalized view of the data that scripts/train_model.py
trains on and scripts/seed_db.py writes into `properties.features`, plus the sale
price target, so the report reflects what the models actually see.
"""
from pathlib import Path

import pandas as pd
from ydata_profiling import ProfileReport

from train_model import CATEGORICAL, FEATURES, NUMERIC, ORDINAL, load_frame

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model" / "data_profile"


def prepared_frame() -> pd.DataFrame:
    df = load_frame()
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col, mapping in ORDINAL.items():
        df[col] = df[col].map(mapping).fillna(3).astype(int)
    for col in CATEGORICAL:
        df[col] = df[col].fillna("NA").astype(str)
    return df[FEATURES + ["saleprice"]]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = prepared_frame()
    # Full mode (correlations + pairwise interactions): ~2,930 rows makes this cheap
    # (~1 minute, ~14 MB) and bivariate relationships are the point of this page for a
    # data analyst/scientist doing EDA, not just univariate distributions. See ADR 0019.
    report = ProfileReport(df, title="TRIDENT-Val Training Data Profile")
    out_path = OUT / "report.html"
    report.to_file(out_path)
    print(f"Wrote data profile report ({out_path.stat().st_size / 1024:.0f} KB) to {out_path}")


if __name__ == "__main__":
    main()
