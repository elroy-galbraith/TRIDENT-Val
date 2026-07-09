import csv
import io
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from . import inference
from .db import get_db
from .models import AuditStatus, BankPortfolioMeta, Property

app = FastAPI(title="TRIDENT-Val AVM & Risk Triage Engine", version="1.0-poc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

LTV_BUCKETS = [("<60%", 0.0, 0.60), ("60-80%", 0.60, 0.80), (">80%", 0.80, 99.0)]


# ---------- schemas ----------

class ValuateRequest(BaseModel):
    features: dict = Field(..., description="Model feature vector (see /api/v1/model/spec)")


class AuditUpdate(BaseModel):
    audit_status: Optional[AuditStatus] = None
    underwriter_notes: Optional[str] = None


# ---------- helpers ----------

def card(p: Property) -> dict:
    return {
        "pid": p.pid,
        "neighborhood": p.neighborhood,
        "bldg_type": p.bldg_type,
        "house_style": p.house_style,
        "year_built": p.year_built,
        "beds": p.bedroom_abvgr,
        "baths": p.full_bath + 0.5 * (p.half_bath or 0),
        "total_sqft": (p.gr_liv_area or 0) + (p.total_bsmt_sf or 0),
        "gr_liv_area": p.gr_liv_area,
        "overall_qual": p.overall_qual,
        "avm_value": float(p.meta.current_avm_value),
        "loan_balance": float(p.meta.current_loan_balance),
        "ltv": round(p.meta.ltv, 4),
        "audit_status": p.meta.audit_status.value,
        "image_url": p.image.url if p.image else None,
    }


# ---------- endpoints ----------

@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/model/spec")
def model_spec():
    return inference.get_spec()


@app.get("/api/v1/portfolio/summary")
def portfolio_summary(db: Session = Depends(get_db)):
    exposure, valuation, n = db.query(
        func.sum(BankPortfolioMeta.current_loan_balance),
        func.sum(BankPortfolioMeta.current_avm_value),
        func.count(BankPortfolioMeta.pid),
    ).one()

    metas = db.query(BankPortfolioMeta.current_loan_balance,
                     BankPortfolioMeta.current_avm_value).all()
    ltvs = [float(b) / float(v) for b, v in metas]
    buckets = [{"bucket": name,
                "count": sum(1 for l in ltvs if lo <= l < hi)}
               for name, lo, hi in LTV_BUCKETS]

    flagged = db.query(func.count(BankPortfolioMeta.pid)).filter(
        BankPortfolioMeta.audit_status == AuditStatus.FLAGGED_HIGH_VARIANCE).scalar()
    pending = db.query(func.count(BankPortfolioMeta.pid)).filter(
        BankPortfolioMeta.audit_status == AuditStatus.PENDING_REVIEW).scalar()

    geo = (db.query(Property.neighborhood,
                    func.count(Property.pid),
                    func.sum(BankPortfolioMeta.current_loan_balance))
           .join(BankPortfolioMeta)
           .group_by(Property.neighborhood)
           .order_by(func.sum(BankPortfolioMeta.current_loan_balance).desc())
           .all())

    return {
        "asset_count": n,
        "total_exposure": float(exposure or 0),
        "total_valuation": float(valuation or 0),
        "avg_ltv": round(sum(ltvs) / len(ltvs), 4) if ltvs else 0,
        "triage_flagged": flagged,
        "triage_pending": pending,
        "ltv_distribution": buckets,
        "neighborhood_concentration": [
            {"neighborhood": g[0], "count": g[1], "exposure": float(g[2])} for g in geo
        ],
    }


@app.get("/api/v1/properties")
def list_properties(
    db: Session = Depends(get_db),
    neighborhood: Optional[str] = None,
    bldg_type: Optional[str] = None,
    audit_status: Optional[AuditStatus] = None,
    search: Optional[str] = None,
    sort: str = Query("ltv_desc", pattern="^(ltv_desc|ltv_asc|value_desc|value_asc|pid)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    q = db.query(Property).join(BankPortfolioMeta).options(
        joinedload(Property.meta), joinedload(Property.image))
    if neighborhood:
        q = q.filter(Property.neighborhood == neighborhood)
    if bldg_type:
        q = q.filter(Property.bldg_type == bldg_type)
    if audit_status:
        q = q.filter(BankPortfolioMeta.audit_status == audit_status)
    if search:
        q = q.filter(or_(Property.neighborhood.ilike(f"%{search}%"),
                         func.cast(Property.pid, str).like(f"%{search}%")))

    order = {
        "ltv_desc": (BankPortfolioMeta.current_loan_balance /
                     BankPortfolioMeta.current_avm_value).desc(),
        "ltv_asc": (BankPortfolioMeta.current_loan_balance /
                    BankPortfolioMeta.current_avm_value).asc(),
        "value_desc": BankPortfolioMeta.current_avm_value.desc(),
        "value_asc": BankPortfolioMeta.current_avm_value.asc(),
        "pid": Property.pid.asc(),
    }[sort]

    total = q.count()
    rows = q.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    return {"total": total, "page": page, "page_size": page_size,
            "items": [card(p) for p in rows]}


@app.get("/api/v1/properties/filters")
def filter_options(db: Session = Depends(get_db)):
    hoods = [r[0] for r in db.query(Property.neighborhood).distinct().order_by(Property.neighborhood)]
    types = [r[0] for r in db.query(Property.bldg_type).distinct().order_by(Property.bldg_type)]
    return {"neighborhoods": hoods, "bldg_types": types,
            "audit_statuses": [s.value for s in AuditStatus]}


@app.get("/api/v1/properties/export")
def export_csv(db: Session = Depends(get_db)):
    rows = db.query(Property).join(BankPortfolioMeta).options(
        joinedload(Property.meta)).order_by(Property.pid).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["pid", "neighborhood", "bldg_type", "year_built", "gr_liv_area",
                "sale_price", "avm_value", "loan_balance", "ltv", "audit_status"])
    for p in rows:
        w.writerow([p.pid, p.neighborhood, p.bldg_type, p.year_built, p.gr_liv_area,
                    p.sale_price, p.meta.current_avm_value, p.meta.current_loan_balance,
                    round(p.meta.ltv, 4), p.meta.audit_status.value])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=portfolio.csv"})


@app.get("/api/v1/properties/{pid}")
def get_property(pid: int, db: Session = Depends(get_db)):
    p = db.query(Property).options(joinedload(Property.meta),
                                   joinedload(Property.image)).get(pid)
    if not p:
        raise HTTPException(404, "Property not found")
    baseline = inference.valuate_with_drivers(p.features)
    return {
        **card(p),
        "sale_price": float(p.sale_price),
        "avm_variance_pct": p.meta.avm_variance_pct,
        "underwriter_notes": p.meta.underwriter_notes,
        "features": p.features,
        "feature_labels": inference.LABELS,
        "baseline_valuation": baseline,
    }


@app.post("/api/v1/valuate")
def valuate(req: ValuateRequest):
    try:
        return inference.valuate_with_drivers(req.features)
    except Exception as e:  # malformed feature vector
        raise HTTPException(422, f"Invalid feature vector: {e}")


@app.patch("/api/v1/properties/{pid}/audit")
def update_audit(pid: int, body: AuditUpdate, db: Session = Depends(get_db)):
    meta = db.query(BankPortfolioMeta).get(pid)
    if not meta:
        raise HTTPException(404, "Property not found")
    if body.audit_status is not None:
        meta.audit_status = body.audit_status
    if body.underwriter_notes is not None:
        meta.underwriter_notes = body.underwriter_notes
    db.commit()
    return {"pid": pid, "audit_status": meta.audit_status.value,
            "underwriter_notes": meta.underwriter_notes}
