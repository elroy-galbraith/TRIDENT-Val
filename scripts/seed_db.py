"""Zero-scrape database instantiation for TRIDENT-Val.

- Ingests Ames raw CSV into `properties` (full model feature vector stored as JSON).
- Registers every model/<model_id>/manifest.json into the `models` table (the model risk
  inventory) and shadow-scores the *entire* portfolio against *every* registered model into
  `model_valuations` — champion and challenger(s) alike. See scripts/train_model.py.
- Books the champion's valuation onto `bank_portfolio_meta.current_avm_value` and derives
  variance-based audit triage from it:
      |AVM - Sale| / Sale > 15%  -> Flagged: High Variance
      8% - 15%                    -> Pending Review
      otherwise                   -> Approved
- Seeds `property_images` with a deterministic, labeled multi-photo set per property (see
  `property_image_set`), built from the same curated Unsplash pool keyed on structural category.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.auth import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.geo import property_latlng  # noqa: E402
from app.models import (AuditStatus, BankPortfolioMeta, ModelStatus,  # noqa: E402
                        ModelValuation, Property, PropertyImage, RegisteredModel,
                        User, UserRole)
from app import inference  # noqa: E402
from train_model import CATEGORICAL, FEATURES, NUMERIC, ORDINAL, load_frame  # noqa: E402

FLAG_HI, FLAG_LO = 0.15, 0.08

# PoC-only fixed demo credentials — not secrets. Do not reuse these anywhere,
# and don't expose this app beyond a trusted local/demo network with defaults intact.
DEMO_USERS = [
    ("viewer", "viewer123", UserRole.VIEWER),
    ("underwriter", "underwriter123", UserRole.UNDERWRITER),
    ("admin", "admin123", UserRole.ADMIN),
]


def seed_users(session) -> None:
    for username, password, role in DEMO_USERS:
        session.add(User(username=username, password_hash=hash_password(password), role=role))
    session.commit()
    print("Seeded demo users (PoC-only, not secrets):")
    for username, password, role in DEMO_USERS:
        print(f"  {username:12s} / {password:16s} ({role.value})")


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

# There's no real per-property photography behind this PoC (see module docstring) — just the
# one curated Unsplash asset per structural category above. To seed a multi-photo carousel
# with distinct labels per property, every asset's "Exterior Front" cover still uses its own
# category photo, and the remaining labeled slots deterministically reuse *other* categories'
# photos in rotation. Still entirely stock/placeholder, just spread across more labeled slots.
ROOM_LABELS = ["Kitchen", "Living Room", "Primary Bedroom", "Backyard"]


def image_category(bldg_type: str, house_style: str) -> str:
    if bldg_type == "1Fam":
        if house_style == "1Story":
            return "1Fam-1Story"
        if house_style in ("2Story", "2.5Fin", "2.5Unf"):
            return "1Fam-2Story"
        return "1Fam-Other"
    return bldg_type if bldg_type in UNSPLASH else "default"


def property_image_set(bldg_type: str, house_style: str) -> list[tuple[str, str, str]]:
    """(label, category, url) for every photo slot on one property, cover first."""
    cover_cat = image_category(bldg_type, house_style)
    fillers = [c for c in UNSPLASH if c != cover_cat][:len(ROOM_LABELS)]
    return [("Exterior Front", cover_cat, UNSPLASH[cover_cat])] + \
           [(label, cat, UNSPLASH[cat]) for label, cat in zip(ROOM_LABELS, fillers)]


def register_models(session) -> str:
    """Insert a `models` row per model/<id>/manifest.json. Returns the champion's model_id.

    Enforces the champion invariant here rather than trusting the manifests blindly: if more
    than one manifest claims default_status=Champion, the first (alphabetically, by id) wins
    and the rest are registered as challengers instead.
    """
    model_ids = inference.list_model_ids()
    if not model_ids:
        raise RuntimeError(
            "No trained models found under model/ — run `python scripts/train_model.py` first.")

    champion_id = None
    rows = {}
    for mid in model_ids:
        manifest = inference.get_manifest(mid)
        status = ModelStatus(manifest["default_status"])
        if status == ModelStatus.CHAMPION:
            if champion_id is not None:
                status = ModelStatus.CHALLENGER
            else:
                champion_id = mid
        rows[mid] = RegisteredModel(
            id=mid, name=manifest["name"], version=manifest["version"],
            architecture=manifest["architecture"], description=manifest.get("description", ""),
            explainer=manifest["explainer"], status=status,
            holdout_mape=manifest["holdout_mape"], holdout_r2=manifest["holdout_r2"],
            trained_at=datetime.fromisoformat(manifest["trained_at"]),
            promoted_at=datetime.now(timezone.utc) if status == ModelStatus.CHAMPION else None,
        )

    if champion_id is None:  # no manifest opted in; fall back to the first registered model
        champion_id = model_ids[0]
        rows[champion_id].status = ModelStatus.CHAMPION
        rows[champion_id].promoted_at = datetime.now(timezone.utc)

    session.add_all(rows.values())
    session.commit()
    print(f"Registered models {list(model_ids)}. Champion: {champion_id}")
    return champion_id


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

    session = SessionLocal()
    seed_users(session)  # committed on its own so login works even if property seeding fails partway
    champion_id = register_models(session)
    model_ids = inference.list_model_ids()

    print(f"Shadow-scoring {len(payloads)} properties against {len(model_ids)} model(s)...")
    valuations_by_model = {mid: inference.valuate_batch_with_drivers(payloads, mid)
                           for mid in model_ids}

    rng = np.random.default_rng(20260709)  # deterministic seeding
    ratios = rng.uniform(0.60, 0.90, size=len(df))

    for i, (_, row) in enumerate(df.iterrows()):
        pid = int(row["pid"])
        sale = float(row["saleprice"])
        avm = valuations_by_model[champion_id][i]["estimated_market_value"]
        variance = (avm - sale) / sale
        if abs(variance) > FLAG_HI:
            status = AuditStatus.FLAGGED_HIGH_VARIANCE
        elif abs(variance) > FLAG_LO:
            status = AuditStatus.PENDING_REVIEW
        else:
            status = AuditStatus.APPROVED

        lat, lng = property_latlng(pid, row["neighborhood"])
        session.add(Property(
            pid=pid,
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
                current_loan_balance=round(float(ratios[i]) * sale, 2),
                current_avm_value=round(avm, 2),
                avm_variance_pct=round(variance, 4),
                audit_status=status,
                underwriter_notes="",
                resolved_model_id=champion_id,
            ),
            images=[
                PropertyImage(url=url, label=label, category=cat, sort_order=i)
                for i, (label, cat, url) in enumerate(property_image_set(row["bldg_type"], row["house_style"]))
            ],
        ))
        for mid in model_ids:
            v = valuations_by_model[mid][i]
            session.add(ModelValuation(
                pid=pid, model_id=mid,
                estimated_value=v["estimated_market_value"],
                value_low=v["value_low"], value_high=v["value_high"],
                top_drivers=v["top_drivers"], top_detractors=v["top_detractors"],
            ))
    session.commit()

    counts = {s.value: session.query(BankPortfolioMeta).filter(
        BankPortfolioMeta.audit_status == s).count() for s in AuditStatus}
    print(f"Seeded {len(df)} properties. Audit triage: {counts}")
    session.close()


if __name__ == "__main__":
    main()
