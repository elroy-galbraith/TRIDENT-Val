"""Zero-scrape database instantiation for TRIDENT-Val.

- Ingests Ames raw CSV into `properties` (full model feature vector stored as JSON).
- Seeds `bank_portfolio_meta`: loan balance = U(0.60, 0.90) * SalePrice (deterministic RNG),
  precomputed AVM value, and variance-based audit triage:
      |AVM - Sale| / Sale > 15%  -> Flagged: High Variance
      8% - 15%                    -> Pending Review
      otherwise                   -> Approved
- Seeds `property_images` with deterministic Unsplash URLs keyed on structural category.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.geo import property_latlng  # noqa: E402
from app.models import (AuditStatus, BankPortfolioMeta, Property,  # noqa: E402
                        PropertyImage)
from app import inference  # noqa: E402
from train_model import CATEGORICAL, FEATURES, NUMERIC, ORDINAL, load_frame  # noqa: E402

FLAG_HI, FLAG_LO = 0.15, 0.08

# Deterministic mapping: structural category -> curated open-source Unsplash asset.
UNSPLASH = {
    "1Fam-1Story": "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=640&q=70",
    "1Fam-2Story": "https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=640&q=70",
    "1Fam-Other": "https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=640&q=70",
    "TwnhsE": "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=640&q=70",
    "Twnhs": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=640&q=70",
    "Duplex": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=640&q=70",
    "2fmCon": "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=640&q=70",
    "default": "https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde?w=640&q=70",
}


def image_category(bldg_type: str, house_style: str) -> str:
    if bldg_type == "1Fam":
        if house_style == "1Story":
            return "1Fam-1Story"
        if house_style in ("2Story", "2.5Fin", "2.5Unf"):
            return "1Fam-2Story"
        return "1Fam-Other"
    return bldg_type if bldg_type in UNSPLASH else "default"


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    df = load_frame()
    # Normalize feature columns exactly as the trainer does
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col, mapping in ORDINAL.items():
        df[col] = df[col].map(mapping).fillna(3).astype(int)
    for col in CATEGORICAL:
        df[col] = df[col].fillna("NA").astype(str)

    payloads = df[FEATURES].to_dict("records")
    print(f"Scoring {len(payloads)} properties with the AVM...")
    avm_values = inference.predict(payloads)

    rng = np.random.default_rng(20260709)  # deterministic seeding
    ratios = rng.uniform(0.60, 0.90, size=len(df))

    session = SessionLocal()
    for i, (_, row) in enumerate(df.iterrows()):
        sale = float(row["saleprice"])
        avm = float(avm_values[i])
        variance = (avm - sale) / sale
        if abs(variance) > FLAG_HI:
            status = AuditStatus.FLAGGED_HIGH_VARIANCE
        elif abs(variance) > FLAG_LO:
            status = AuditStatus.PENDING_REVIEW
        else:
            status = AuditStatus.APPROVED

        cat = image_category(row["bldg_type"], row["house_style"])
        lat, lng = property_latlng(int(row["pid"]), row["neighborhood"])
        session.add(Property(
            pid=int(row["pid"]),
            neighborhood=row["neighborhood"], bldg_type=row["bldg_type"],
            house_style=row["house_style"], ms_zoning=row["ms_zoning"],
            year_built=int(row["year_built"]),
            overall_qual=int(row["overall_qual"]), overall_cond=int(row["overall_cond"]),
            gr_liv_area=int(row["gr_liv_area"]), total_bsmt_sf=int(row["total_bsmt_sf"]),
            full_bath=int(row["full_bath"]), half_bath=int(row["half_bath"]),
            bedroom_abvgr=int(row["bedroom_abvgr"]),
            sale_price=sale,
            lat=lat, lng=lng,
            features=payloads[i],
            meta=BankPortfolioMeta(
                current_loan_balance=round(ratios[i] * sale, 2),
                current_avm_value=round(avm, 2),
                avm_variance_pct=round(variance, 4),
                audit_status=status,
                underwriter_notes="",
            ),
            image=PropertyImage(url=UNSPLASH[cat], category=cat),
        ))
    session.commit()

    counts = {s.value: session.query(BankPortfolioMeta).filter(
        BankPortfolioMeta.audit_status == s).count() for s in AuditStatus}
    print(f"Seeded {len(df)} properties. Audit triage: {counts}")
    session.close()


if __name__ == "__main__":
    main()
