import csv
import io
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, case, cast, func, or_
from sqlalchemy.orm import Session, aliased, joinedload
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # picks up a repo-root .env for local (non-Docker) runs; no-op if absent

# The top-level ingestion/ package (dlt pipelines — see that package's docstrings) lives
# alongside backend/, scripts/, etc., not inside this app package, so it needs the repo root
# on sys.path — same explicit-insert convention scripts/seed_db.py uses for its own imports.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from . import extraction, inference, reports, synthetic_reports
from .auth import DUMMY_PASSWORD_HASH, get_current_user, require_role, verify_password
from .degrade import degrade_pdf
from .db import Base, engine, get_db
from .logging_config import setup_logging
from .models import (AuditStatus, BankPortfolioMeta, ExtractionFieldResult, ExtractionRun,
                     ExtractionRunStatus, IngestionQuarantine, IngestionRun, ModelStatus,
                     ModelValuation, Property, PropertyImage, PropertySourceRecord,
                     RegisteredModel, RevaluationResult, RevaluationRun, ScenarioType,
                     SourceSystem, SyntheticDocument, SyntheticReportStyle, SystemLog,
                     User, UserRole)
from ingestion.pipeline import run_sync as ingestion_run_sync

setup_logging()

app = FastAPI(title="TRIDENT-Val AVM & Risk Triage Engine", version="1.0-poc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Signed-cookie session for the PoC login (see app.auth). The frontend never calls the
# backend cross-origin (Vite/nginx both proxy /api same-origin), so a plain cookie
# session needs no CORS credentials plumbing. SESSION_SECRET falls back to a known,
# non-secret PoC placeholder (matches the docker-compose Postgres password convention)
# so the app still boots locally; rotate it before any non-local use.
SESSION_SECRET = os.environ.get("SESSION_SECRET") or "trident-poc-insecure-default-change-me"
if not os.environ.get("SESSION_SECRET"):
    logger.warning("SESSION_SECRET is not set; using an insecure PoC-only default. "
                   "Set SESSION_SECRET before any non-local use.")
# Defaults to False so the cookie still works over plain http://localhost; flip to true
# once this sits behind real HTTPS so the browser refuses to send the cookie over http.
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 8,
                   https_only=SESSION_COOKIE_SECURE)


@app.on_event("startup")
def log_startup():
    Base.metadata.create_all(bind=engine)  # idempotent: only creates system_logs on existing DBs
    logger.info("TRIDENT-Val backend starting up (version {v})", v=app.version)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.bind(context={
            "method": request.method, "path": request.url.path,
            "status_code": 500, "duration_ms": duration_ms, "error": str(e),
        }).error("{method} {path} -> 500 ({duration}ms) - unhandled exception: {error}",
                method=request.method, path=request.url.path, duration=duration_ms, error=str(e))
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    level = "ERROR" if response.status_code >= 500 else \
            "WARNING" if response.status_code >= 400 else "INFO"
    logger.bind(context={
        "method": request.method, "path": request.url.path,
        "status_code": response.status_code, "duration_ms": duration_ms,
    }).log(level, "{method} {path} -> {status} ({duration}ms)",
          method=request.method, path=request.url.path,
          status=response.status_code, duration=duration_ms)
    return response

LTV_BUCKETS = [("<60%", 0.0, 0.60), ("60-80%", 0.60, 0.80), (">80%", 0.80, 99.0)]

# ---------- revaluation cycle constants ----------
# Small quarterly HPI-style noise per neighborhood for the "organic" (standard cycle) scenario —
# deliberately not a market forecast, just enough drift to move LTV buckets and occasionally trip
# a triage flag between deliberate stress runs, the way a real quarterly index update would.
ORGANIC_DRIFT_RANGE = (-0.04, 0.04)
REVAL_VALUE_DROP_FLAG = -0.10   # period-over-period value drop beyond this triggers a flag
REVAL_LTV_FLAG = 0.80           # LTV at/above this after a cycle triggers a flag
SCENARIO_LABELS = {
    ScenarioType.ORGANIC.value: "Standard Quarterly Cycle",
    ScenarioType.BROAD_STRESS.value: "Broad Market Stress",
    ScenarioType.TARGETED_STRESS.value: "Concentrated Neighborhood Shock",
    ScenarioType.CUSTOM.value: "Custom Scenario",
}


# ---------- schemas ----------

class ValuateRequest(BaseModel):
    features: dict = Field(..., description="Model feature vector (see /api/v1/models/{model_id}/spec)")
    model_id: Optional[str] = Field(None, description="Defaults to the current champion")


class AuditUpdate(BaseModel):
    audit_status: Optional[AuditStatus] = None
    underwriter_notes: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class PromoteRequest(BaseModel):
    rationale: str = Field(..., min_length=1, description="Why this challenger is being promoted")


class TriageDecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(champion|challenger|manual)$")
    model_id: Optional[str] = Field(None, description="Required when decision == 'challenger'")
    manual_value: Optional[float] = Field(None, gt=0, description="Required when decision == 'manual'")
    rationale: str = Field(..., min_length=1)


class RevaluationRequest(BaseModel):
    as_of_date: Optional[str] = Field(None, description="ISO date/datetime; defaults to now")
    scenario_type: str = Field("organic", pattern="^(organic|broad_stress|targeted_stress|custom)$")
    scenario_name: Optional[str] = Field(None, description="Defaults to a label per scenario_type")
    broad_shock_pct: Optional[float] = Field(
        None, ge=-0.9, le=0.9, description="Required for broad_stress, e.g. -0.10 for -10%")
    target_neighborhood: Optional[str] = Field(None, description="Required for targeted_stress")
    target_shock_pct: Optional[float] = Field(
        None, ge=-0.9, le=0.9, description="Required for targeted_stress")
    custom_adjustments: Optional[dict[str, float]] = Field(
        None, description="Required for custom: {neighborhood: pct}, omitted neighborhoods default to 0")
    notes: Optional[str] = ""


class IngestionSyncRequest(BaseModel):
    source_system: str = Field(
        ..., pattern="^(core_banking|valuation_vendor|valuations_team|all)$",
        description="One source system, or 'all' to sync every source in one call")


class QuarantineResolveRequest(BaseModel):
    resolution_notes: str = Field("", description="How this quarantined record was resolved")


class DocumentGenerateRequest(BaseModel):
    pids: list[int] = Field(..., min_length=1, max_length=50)
    style: str = Field("legacy_urar", pattern="^(modern|legacy_urar)$")
    degrade: bool = Field(False, description="Simulate a scanned/photocopied paper document")


class TriageFieldResolveRequest(BaseModel):
    resolution: str = Field(..., min_length=1, description="The corrected/confirmed value or note")


# ---------- helpers ----------

def map_point(p: Property) -> dict:
    avm_value = float(p.meta.current_avm_value)
    return {
        "pid": p.pid,
        "neighborhood": p.neighborhood,
        "bldg_type": p.bldg_type,
        "lat": p.lat,
        "lng": p.lng,
        "avm_value": avm_value,
        "gr_liv_area": p.gr_liv_area,
        "overall_qual": p.overall_qual,
        "year_built": p.year_built,
        "ltv": round(float(p.meta.current_loan_balance) / avm_value, 4) if avm_value else 0.0,
        "audit_status": p.meta.audit_status.value,
    }


def user_out(u: User) -> dict:
    return {"username": u.username, "role": u.role.value}


def comp_score(subject: Property, candidate: Property) -> float:
    score = 0.0
    if candidate.neighborhood == subject.neighborhood:
        score += 100.0
    if candidate.bldg_type == subject.bldg_type:
        score += 20.0
    score -= abs((candidate.gr_liv_area or 0) - (subject.gr_liv_area or 0)) / 50.0
    score -= abs((candidate.overall_qual or 0) - (subject.overall_qual or 0)) * 5.0
    score -= abs((candidate.year_built or 0) - (subject.year_built or 0)) / 5.0
    return score


def model_row(m: RegisteredModel) -> dict:
    return {
        "id": m.id, "name": m.name, "version": m.version, "architecture": m.architecture,
        "description": m.description, "explainer": m.explainer, "status": m.status.value,
        "holdout_mape": m.holdout_mape, "holdout_r2": m.holdout_r2,
        "trained_at": m.trained_at.isoformat() if m.trained_at else None,
        "promoted_at": m.promoted_at.isoformat() if m.promoted_at else None,
    }


def revaluation_run_row(run: RevaluationRun, agg: tuple) -> dict:
    """agg = (asset_count, avg_value_delta_pct, flagged_count) from a grouped aggregate query —
    see list_revaluations, which computes this once for every run instead of per-row queries."""
    n, avg_delta, flagged = agg
    return {
        "run_id": run.id,
        "as_of_date": run.as_of_date.isoformat() if run.as_of_date else None,
        "scenario_name": run.scenario_name,
        "scenario_type": run.scenario_type.value,
        "model_id": run.model_id,
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "notes": run.notes,
        "asset_count": n or 0,
        "avg_value_delta_pct": round(float(avg_delta), 4) if avg_delta is not None else 0.0,
        "flagged_count": int(flagged or 0),
    }


def champion_id(db: Session) -> str:
    mid = db.query(RegisteredModel.id).filter(RegisteredModel.status == ModelStatus.CHAMPION).scalar()
    if not mid:
        raise HTTPException(500, "No champion model registered — run scripts/seed_db.py")
    return mid


def resolve_champion(db: Session, model_id: Optional[str]) -> RegisteredModel:
    m = db.query(RegisteredModel).get(model_id) if model_id else \
        db.query(RegisteredModel).filter(RegisteredModel.status == ModelStatus.CHAMPION).one_or_none()
    if not m:
        raise HTTPException(404, "Champion model not found")
    return m


def resolve_challenger(db: Session, model_id: Optional[str]) -> RegisteredModel:
    if model_id:
        m = db.query(RegisteredModel).get(model_id)
    else:
        m = (db.query(RegisteredModel).filter(RegisteredModel.status == ModelStatus.CHALLENGER)
             .order_by(RegisteredModel.id).first())
    if not m:
        raise HTTPException(404, "Challenger model not found")
    return m


def image_out(img: PropertyImage) -> dict:
    return {"url": img.url, "label": img.label, "category": img.category}


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
        "images": [image_out(img) for img in p.images],
    }


# ---------- endpoints ----------

@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    # `password_ok` must be computed unconditionally, outside the `if` below — `or` would
    # short-circuit and skip verify_password entirely when user is None, making "user not
    # found" respond faster than "wrong password" and leaking which usernames exist via
    # response timing. Checking against a dummy hash keeps both paths equally slow.
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash)
    if user is None or not password_ok:
        logger.bind(context={"attempted_username": body.username}).warning(
            "Failed login attempt for username '{username}'.", username=body.username)
        raise HTTPException(401, "Invalid username or password")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    logger.bind(actor=user.username, context={"role": user.role.value}).info(
        "User '{username}' logged in.", username=user.username)
    return user_out(user)


@app.post("/api/v1/auth/logout")
def logout(request: Request, user: User = Depends(get_current_user)):
    logger.bind(actor=user.username).info("User '{username}' logged out.", username=user.username)
    request.session.clear()
    return {"status": "ok"}


@app.get("/api/v1/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@app.get("/api/v1/models")
def list_models(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The model risk inventory: every registered model and its governance status."""
    rows = db.query(RegisteredModel).order_by(RegisteredModel.status, RegisteredModel.id).all()
    return {"items": [model_row(m) for m in rows]}


@app.get("/api/v1/models/{model_id}/spec")
def model_spec(model_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.query(RegisteredModel).get(model_id):
        raise HTTPException(404, "Model not found")
    try:
        return inference.get_spec(model_id)
    except inference.UnknownModelError:
        raise HTTPException(404, "Model artifact not found on disk")


_importance_cache: dict[str, dict] = {}


@app.get("/api/v1/models/{model_id}/importance")
def model_importance(model_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Global feature importance for a model's Model Card page, cached per model_id after the
    first request — property feature vectors are immutable after seeding, so re-scoring the
    whole portfolio on every page load would be wasted work."""
    if not db.query(RegisteredModel).get(model_id):
        raise HTTPException(404, "Model not found")
    if model_id not in _importance_cache:
        rows = db.query(Property.features).all()
        if not rows:  # don't cache an empty result if requested before seeding completes
            return {"sample_size": 0, "drivers": []}
        _importance_cache[model_id] = inference.global_importance([r[0] for r in rows], model_id)
    return _importance_cache[model_id]


@app.post("/api/v1/models/{model_id}/promote")
def promote_model(model_id: str, body: PromoteRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_role(UserRole.ADMIN))):
    """Governed promotion: designate a new champion at the portfolio level. This is a
    deliberate, logged act — not a per-asset choice — so it re-books every property's
    current_avm_value from the promoted model's shadow valuations in one pass. Restricted
    to Admin: this is a portfolio-wide model risk decision, not a per-asset override."""
    target = db.query(RegisteredModel).get(model_id)
    if not target:
        raise HTTPException(404, "Model not found")
    if target.status == ModelStatus.RETIRED:
        raise HTTPException(400, "Cannot promote a retired model")
    if target.status == ModelStatus.CHAMPION:
        raise HTTPException(400, "Model is already champion")

    prev_champion = db.query(RegisteredModel).filter(
        RegisteredModel.status == ModelStatus.CHAMPION).one_or_none()
    if prev_champion:
        prev_champion.status = ModelStatus.CHALLENGER
    target.status = ModelStatus.CHAMPION
    target.promoted_at = datetime.now(timezone.utc)

    rows = (db.query(BankPortfolioMeta, Property.sale_price, ModelValuation)
            .join(Property, Property.pid == BankPortfolioMeta.pid)
            .join(ModelValuation, (ModelValuation.pid == BankPortfolioMeta.pid) &
                                  (ModelValuation.model_id == model_id))
            .all())
    for meta, sale_price, val in rows:
        sale = float(sale_price) if sale_price else 0.0
        avm = float(val.estimated_value)
        variance = (avm - sale) / sale if sale else 0.0
        meta.current_avm_value = val.estimated_value
        meta.avm_variance_pct = round(variance, 4)
        meta.resolved_model_id = model_id
        meta.audit_status = (
            AuditStatus.FLAGGED_HIGH_VARIANCE if abs(variance) > 0.15 else
            AuditStatus.PENDING_REVIEW if abs(variance) > 0.08 else AuditStatus.APPROVED)
    db.commit()

    logger.bind(actor=user.username, context={
        "previous_champion": prev_champion.id if prev_champion else None,
        "new_champion": model_id, "rationale": body.rationale, "assets_rebooked": len(rows),
    }).info("Model promotion: {new} is now champion (was {prev}). Rationale: {rationale}",
           new=model_id, prev=prev_champion.id if prev_champion else "none", rationale=body.rationale)

    return {"champion": model_id, "previous_champion": prev_champion.id if prev_champion else None,
            "assets_rebooked": len(rows)}


@app.get("/api/v1/models/compare")
def compare_models(champion: Optional[str] = None, challenger: Optional[str] = None,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Champion vs. challenger, computed from the shadow-scoring ledger: per-property
    values for the scatter plot, per-neighborhood error/bias breakdown, and portfolio-wide
    agreement stats. Defaults to the current champion vs. the first available challenger."""
    champ = resolve_champion(db, champion)
    chal = resolve_challenger(db, challenger)

    # Single joined query instead of one full-table scan per model — inner joins on both
    # valuations naturally drop any property missing either model's score, matching the
    # previous "skip if either value is None" behavior.
    mv_champ, mv_chal = aliased(ModelValuation), aliased(ModelValuation)
    rows = (db.query(Property.pid, Property.neighborhood, Property.bldg_type,
                     Property.sale_price, mv_champ.estimated_value, mv_chal.estimated_value)
            .join(mv_champ, (mv_champ.pid == Property.pid) & (mv_champ.model_id == champ.id))
            .join(mv_chal, (mv_chal.pid == Property.pid) & (mv_chal.model_id == chal.id))
            .all())

    points, divergences, champ_err, chal_err = [], [], [], []
    seg: dict[str, dict] = {}
    for pid, nbhd, bldg, sale_price, va_dec, vb_dec in rows:
        va, vb = float(va_dec), float(vb_dec)
        sale = float(sale_price)
        divergence_pct = (vb - va) / va if va else 0.0
        points.append({
            "pid": pid, "neighborhood": nbhd, "bldg_type": bldg, "sale_price": sale,
            "champion_value": round(va, 2), "challenger_value": round(vb, 2),
            "divergence_pct": round(divergence_pct, 4),
        })
        divergences.append(abs(divergence_pct))
        champ_err.append(abs(va - sale) / sale)
        chal_err.append(abs(vb - sale) / sale)
        s = seg.setdefault(nbhd, {"neighborhood": nbhd, "n": 0, "err_champ": 0.0, "err_chal": 0.0,
                                  "bias_champ": 0.0, "bias_chal": 0.0})
        s["n"] += 1
        s["err_champ"] += abs(va - sale) / sale
        s["err_chal"] += abs(vb - sale) / sale
        s["bias_champ"] += (va - sale) / sale
        s["bias_chal"] += (vb - sale) / sale

    segment_breakdown = [
        {"neighborhood": s["neighborhood"], "n": s["n"],
         "mape_champion": round(s["err_champ"] / s["n"], 4),
         "mape_challenger": round(s["err_chal"] / s["n"], 4),
         "bias_champion": round(s["bias_champ"] / s["n"], 4),
         "bias_challenger": round(s["bias_chal"] / s["n"], 4)}
        for s in sorted(seg.values(), key=lambda s: s["n"], reverse=True)
    ]

    n = len(points) or 1
    return {
        "champion": model_row(champ), "challenger": model_row(chal),
        "points": points,
        "segment_breakdown": segment_breakdown,
        "overall": {
            "n": len(points),
            "mape_champion": round(sum(champ_err) / n, 4),
            "mape_challenger": round(sum(chal_err) / n, 4),
            "mean_abs_divergence_pct": round(sum(divergences) / n, 4),
            "agreement_within_10pct_share": round(
                sum(1 for d in divergences if d <= 0.10) / n, 4),
        },
    }


@app.get("/api/v1/models/disagreements")
def model_disagreements(
    champion: Optional[str] = None, challenger: Optional[str] = None,
    threshold: float = Query(0.10, ge=0, le=2),
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """The triage queue: assets where champion and challenger diverge beyond `threshold`,
    ranked by divergence. This is where a disagreement becomes a human decision, logged via
    POST /properties/{pid}/triage-decision."""
    champ = resolve_champion(db, champion)
    chal = resolve_challenger(db, challenger)

    # Single joined query instead of one full-table scan per model (see compare_models).
    mv_champ, mv_chal = aliased(ModelValuation), aliased(ModelValuation)
    rows = (db.query(Property, mv_champ.estimated_value, mv_chal.estimated_value)
            .join(BankPortfolioMeta)
            .join(mv_champ, (mv_champ.pid == Property.pid) & (mv_champ.model_id == champ.id))
            .join(mv_chal, (mv_chal.pid == Property.pid) & (mv_chal.model_id == chal.id))
            .options(joinedload(Property.meta), joinedload(Property.images))
            .all())
    items = []
    for p, va_dec, vb_dec in rows:
        va, vb = float(va_dec), float(vb_dec)
        divergence = (vb - va) / va if va else 0.0
        if abs(divergence) < threshold:
            continue
        items.append({**card(p), "champion_value": round(va, 2), "challenger_value": round(vb, 2),
                      "divergence_pct": round(divergence, 4)})
    items.sort(key=lambda it: abs(it["divergence_pct"]), reverse=True)

    total = len(items)
    start = (page - 1) * page_size
    return {"champion": model_row(champ), "challenger": model_row(chal), "threshold": threshold,
            "total": total, "page": page, "page_size": page_size,
            "items": items[start:start + page_size]}


# NB: registered after the static /models/compare and /models/disagreements routes above —
# FastAPI matches path operations in registration order, and /models/{model_id} would
# otherwise swallow those two literal paths as model_id="compare"/"disagreements".
@app.get("/api/v1/models/{model_id}")
def get_model(model_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    m = db.query(RegisteredModel).get(model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    return model_row(m)


@app.get("/api/v1/portfolio/summary")
def portfolio_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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


@app.get("/api/v1/portfolio/map")
def portfolio_map(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(Property).join(BankPortfolioMeta).options(joinedload(Property.meta)).all()
    points = [map_point(p) for p in rows]
    return {"count": len(points), "points": points}


@app.get("/api/v1/portfolio/report")
def portfolio_report(champion: Optional[str] = None, challenger: Optional[str] = None,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Portfolio Review Summary (PDF): exposure, LTV distribution, audit triage outcomes, and
    champion/challenger governance stats, with an AI-drafted executive summary grounded on
    that same data. See app.reports for the IVS 103 / Red Book framing this follows. Open to
    any logged-in role — same precedent as the CSV export below, since it's a different
    format of data every role can already see live in-app, not a new write privilege."""
    start = time.perf_counter()
    try:
        pdf_bytes = reports.render_portfolio_report_pdf(db, user, champion, challenger)
    except Exception as e:
        logger.bind(actor=user.username, context={"error": str(e)}).error(
            "Portfolio report generation failed: {error}", error=str(e))
        raise HTTPException(500, "Report generation failed")
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.bind(actor=user.username, context={
        "report_type": "portfolio_summary", "generation_ms": latency_ms,
        "champion": champion, "challenger": challenger,
    }).info("Exported portfolio review summary ({latency}ms).", latency=latency_ms)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="trident-val_portfolio_review_summary.pdf"'})


@app.get("/api/v1/properties")
def list_properties(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    neighborhood: Optional[str] = None,
    bldg_type: Optional[str] = None,
    audit_status: Optional[AuditStatus] = None,
    search: Optional[str] = None,
    sort: str = Query("ltv_desc", pattern="^(ltv_desc|ltv_asc|value_desc|value_asc|pid)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    q = db.query(Property).join(BankPortfolioMeta).options(
        joinedload(Property.meta), joinedload(Property.images))
    if neighborhood:
        q = q.filter(Property.neighborhood == neighborhood)
    if bldg_type:
        q = q.filter(Property.bldg_type == bldg_type)
    if audit_status:
        q = q.filter(BankPortfolioMeta.audit_status == audit_status)
    if search:
        conditions = [Property.neighborhood.ilike(f"%{search}%")]
        digits = re.sub(r"\D", "", search)
        if digits:
            conditions.append(cast(Property.pid, String).like(f"%{digits}%"))
        q = q.filter(or_(*conditions))

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
def filter_options(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    hoods = [r[0] for r in db.query(Property.neighborhood).distinct().order_by(Property.neighborhood)]
    types = [r[0] for r in db.query(Property.bldg_type).distinct().order_by(Property.bldg_type)]
    return {"neighborhoods": hoods, "bldg_types": types,
            "audit_statuses": [s.value for s in AuditStatus]}


@app.get("/api/v1/properties/export")
def export_csv(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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
def get_property(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = db.query(Property).options(joinedload(Property.meta), joinedload(Property.images)) \
        .filter(Property.pid == pid).one_or_none()
    if not p:
        raise HTTPException(404, "Property not found")
    # A manual override has no model backing it; explain against whichever model IS
    # currently booked, falling back to the champion.
    effective_model_id = p.meta.resolved_model_id or champion_id(db)
    baseline = inference.valuate_with_drivers(p.features, effective_model_id)
    return {
        **card(p),
        "sale_price": float(p.sale_price),
        "avm_variance_pct": p.meta.avm_variance_pct,
        "underwriter_notes": p.meta.underwriter_notes,
        "resolved_model_id": p.meta.resolved_model_id,
        "features": p.features,
        "feature_labels": inference.LABELS,
        "baseline_valuation": baseline,
    }


@app.get("/api/v1/properties/{pid}/valuations")
def property_valuations(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Every registered model's shadow valuation for one property, side by side — backs the
    Inspector's model-comparison panel."""
    prop = db.query(Property).options(joinedload(Property.meta)).get(pid)
    if not prop:
        raise HTTPException(404, "Property not found")
    rows = (db.query(ModelValuation, RegisteredModel)
            .join(RegisteredModel, RegisteredModel.id == ModelValuation.model_id)
            .filter(ModelValuation.pid == pid)
            .order_by(RegisteredModel.status, RegisteredModel.id)
            .all())
    resolved = prop.meta.resolved_model_id
    return {
        "pid": pid,
        "resolved_model_id": resolved,
        "booked_value": float(prop.meta.current_avm_value),
        "items": [
            {
                "model_id": mv.model_id, "model_name": rm.name, "status": rm.status.value,
                "estimated_value": float(mv.estimated_value),
                "value_low": float(mv.value_low), "value_high": float(mv.value_high),
                "top_drivers": mv.top_drivers, "top_detractors": mv.top_detractors,
                "is_booked": mv.model_id == resolved,
            }
            for mv, rm in rows
        ],
    }


@app.get("/api/v1/properties/{pid}/comps")
def get_comps(pid: int, limit: int = Query(6, ge=1, le=20), db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    subject = db.query(Property).options(joinedload(Property.meta)).get(pid)
    if not subject:
        raise HTTPException(404, "Property not found")

    candidates = (db.query(Property)
                  .join(BankPortfolioMeta)
                  .options(joinedload(Property.meta))
                  .filter(Property.pid != pid)
                  .all())
    ranked = sorted(candidates, key=lambda c: comp_score(subject, c), reverse=True)[:limit]

    return {"subject": map_point(subject), "comps": [map_point(c) for c in ranked]}


@app.get("/api/v1/properties/{pid}/report")
def property_report(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Underwriter Decision Report (PDF) for one asset — AVM-supported, IVS 103 / RICS Red
    Book VPS 6 structured. Not "the AVM's valuation report": see app.reports for why that
    framing matters and what the sign-off block is grounded on. Open to any logged-in role —
    same precedent as the CSV export, since it's a different format of data every role can
    already see live on this asset's Inspector page, not a new write privilege."""
    start = time.perf_counter()
    try:
        pdf_bytes = reports.render_asset_report_pdf(db, pid, user)
    except Exception as e:
        logger.bind(pid=pid, actor=user.username, context={"error": str(e)}).error(
            "Asset decision report generation failed for PID {pid}: {error}", pid=pid, error=str(e))
        raise HTTPException(500, "Report generation failed")
    if pdf_bytes is None:
        raise HTTPException(404, "Property not found")
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.bind(pid=pid, actor=user.username, context={
        "report_type": "asset_decision", "generation_ms": latency_ms,
    }).info("Exported asset decision report for PID {pid} ({latency}ms).", pid=pid, latency=latency_ms)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="trident-val_asset_{pid}_decision_report.pdf"'})


@app.post("/api/v1/valuate")
def valuate(req: ValuateRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    model_id = req.model_id or champion_id(db)
    start = time.perf_counter()
    try:
        result = inference.valuate_with_drivers(req.features, model_id)
    except inference.UnknownModelError:
        raise HTTPException(404, f"Unknown model_id {model_id!r}")
    except Exception as e:  # malformed feature vector
        logger.bind(context={"error": str(e), "model_id": model_id}).warning(
            "AVM inference rejected an invalid feature vector.")
        raise HTTPException(422, f"Invalid feature vector: {e}")
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.bind(context={
        "model_id": model_id, "inference_latency_ms": latency_ms,
        "estimated_market_value": result["estimated_market_value"],
        "error_band_pct": result["error_band_pct"],
    }).info("AVM inference ({model}) completed in {latency}ms -> {value}",
           model=model_id, latency=latency_ms, value=result["estimated_market_value"])
    return result


@app.patch("/api/v1/properties/{pid}/audit")
def update_audit(pid: int, body: AuditUpdate, db: Session = Depends(get_db),
                 user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    meta = db.query(BankPortfolioMeta).get(pid)
    if not meta:
        raise HTTPException(404, "Property not found")
    prev_status, prev_notes = meta.audit_status.value, meta.underwriter_notes
    if body.audit_status is not None:
        meta.audit_status = body.audit_status
    if body.underwriter_notes is not None:
        meta.underwriter_notes = body.underwriter_notes
    db.commit()

    if body.audit_status is not None and body.audit_status.value != prev_status:
        logger.bind(pid=pid, actor=user.username, context={
            "previous_status": prev_status, "new_status": meta.audit_status.value,
        }).info("Underwriter changed audit status for PID {pid}: {prev} -> {new}",
               pid=pid, prev=prev_status, new=meta.audit_status.value)
    if body.underwriter_notes is not None and body.underwriter_notes != prev_notes:
        logger.bind(pid=pid, actor=user.username, context={"notes_length": len(body.underwriter_notes)}).info(
            "Underwriter updated audit notes for PID {pid}.", pid=pid)

    return {"pid": pid, "audit_status": meta.audit_status.value,
            "underwriter_notes": meta.underwriter_notes}


@app.post("/api/v1/properties/{pid}/triage-decision")
def triage_decision(pid: int, body: TriageDecisionRequest, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    """Resolve a champion/challenger disagreement for one asset: book the champion's value,
    book a specific challenger's value, or a manual underwriter override. Every decision is
    logged to the audit ledger with its rationale — this is the human-in-the-loop half of
    shadow scoring."""
    prop = db.query(Property).options(joinedload(Property.meta)).get(pid)
    if not prop:
        raise HTTPException(404, "Property not found")
    meta = prop.meta
    sale = float(prop.sale_price) if prop.sale_price else 0.0
    prev_value, prev_model = float(meta.current_avm_value), meta.resolved_model_id

    if body.decision == "manual":
        if body.manual_value is None:
            raise HTTPException(422, "manual_value is required for a manual decision")
        new_value, new_model_id = body.manual_value, None
    else:
        if body.decision == "champion":
            model_id = champion_id(db)
        else:  # "challenger"
            if not body.model_id:
                raise HTTPException(422, "model_id is required for a challenger decision")
            model_id = body.model_id
        val = db.query(ModelValuation).filter(ModelValuation.pid == pid,
                                              ModelValuation.model_id == model_id).one_or_none()
        if not val:
            raise HTTPException(404, f"No valuation on file for model_id {model_id!r} on this property")
        new_value, new_model_id = float(val.estimated_value), model_id

    variance = (new_value - sale) / sale if sale else 0.0
    meta.current_avm_value = round(new_value, 2)
    meta.avm_variance_pct = round(variance, 4)
    meta.resolved_model_id = new_model_id
    meta.audit_status = (
        AuditStatus.FLAGGED_HIGH_VARIANCE if abs(variance) > 0.15 else
        AuditStatus.PENDING_REVIEW if abs(variance) > 0.08 else AuditStatus.APPROVED)
    db.commit()

    logger.bind(pid=pid, actor=user.username, context={
        "decision": body.decision, "previous_booked_value": prev_value,
        "previous_model_id": prev_model, "new_booked_value": float(meta.current_avm_value),
        "new_model_id": new_model_id, "rationale": body.rationale,
    }).info("Underwriter triage decision for PID {pid}: {decision} -> {value} ({rationale})",
           pid=pid, decision=body.decision, value=meta.current_avm_value, rationale=body.rationale)

    return {"pid": pid, "decision": body.decision, "resolved_model_id": new_model_id,
            "avm_value": float(meta.current_avm_value), "avm_variance_pct": meta.avm_variance_pct,
            "audit_status": meta.audit_status.value}


# ---------- data ingestion (dlt) ----------
# Multi-source ingestion demo: three fake "source systems" (a core-banking-style CSV drop, a
# mock valuation-vendor API, a valuations-team spreadsheet — see the top-level ingestion/
# package and scripts/generate_ingestion_sources.py) land through a dlt pipeline into a
# canonical provenance ledger, with malformed rows quarantined rather than silently dropped.
# dlt only ever refreshes BankPortfolioMeta.current_loan_balance (core_banking only) — it
# never touches current_avm_value/avm_variance_pct/audit_status, so a sync can't silently
# perturb the AVM/triage numbers the rest of the app's demo depends on.

def ingestion_run_row(run: IngestionRun) -> dict:
    return {
        "run_id": run.id, "source_system": run.source_system.value, "status": run.status.value,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "records_seen": run.records_seen, "records_loaded": run.records_loaded,
        "records_quarantined": run.records_quarantined,
        "schema_columns_added": run.schema_columns_added,
        "triggered_by": run.triggered_by, "error": run.error,
    }


@app.post("/api/v1/ingestion/sync")
def sync_ingestion(body: IngestionSyncRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    """Trigger a dlt sync for one source system, or every source via source_system="all".
    Synchronous — matches the rest of the app's heavy-but-synchronous operations (report
    generation, revaluation cycles). Each source is isolated: if one fails (e.g. the
    vendor_api service being down), the others still run rather than the whole "all" sync
    aborting — the same "one bad thing shouldn't take down everything else" ethos as
    quarantine. Only raises when every requested source failed."""
    targets = list(SourceSystem) if body.source_system == "all" else [SourceSystem(body.source_system)]
    runs = []
    failures = []
    for source_system in targets:
        try:
            run = ingestion_run_sync(db, source_system, user.username)
        except Exception as e:
            logger.bind(actor=user.username, context={
                "source_system": source_system.value, "error": str(e),
            }).error("Ingestion sync failed for {source}: {error}",
                    source=source_system.value, error=str(e))
            failures.append(source_system.value)
            # ingestion_run_sync already persisted this attempt as a failed IngestionRun
            # (status=failed, error set) before re-raising — fetch it so the response still
            # reports it instead of vanishing, then keep going to the next source.
            failed_run = (db.query(IngestionRun)
                         .filter(IngestionRun.source_system == source_system)
                         .order_by(IngestionRun.id.desc()).first())
            if failed_run:
                runs.append(failed_run)
            continue
        runs.append(run)
        logger.bind(actor=user.username, context={
            "run_id": run.id, "source_system": source_system.value,
            "records_loaded": run.records_loaded, "records_quarantined": run.records_quarantined,
            "schema_columns_added": run.schema_columns_added,
        }).info("Ingestion sync #{run_id} ({source}): {loaded} loaded, {quarantined} quarantined.",
               run_id=run.id, source=source_system.value, loaded=run.records_loaded,
               quarantined=run.records_quarantined)

    if failures and len(failures) == len(targets):
        raise HTTPException(502, f"Sync failed for: {', '.join(failures)}")
    return {"runs": [ingestion_run_row(r) for r in runs], "failures": failures}


@app.get("/api/v1/ingestion/runs")
def list_ingestion_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    runs = db.query(IngestionRun).order_by(IngestionRun.id.desc()).limit(100).all()
    return {"items": [ingestion_run_row(r) for r in runs]}


@app.get("/api/v1/ingestion/runs/{run_id}")
def get_ingestion_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(IngestionRun).get(run_id)
    if not run:
        raise HTTPException(404, "Ingestion run not found")
    return ingestion_run_row(run)


@app.get("/api/v1/ingestion/records")
def list_ingestion_records(
    source_system: Optional[str] = None, pid: Optional[int] = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    q = db.query(PropertySourceRecord)
    if source_system:
        q = q.filter(PropertySourceRecord.source_system == SourceSystem(source_system))
    if pid is not None:
        q = q.filter(PropertySourceRecord.pid == pid)
    total = q.count()
    rows = (q.order_by(PropertySourceRecord.loaded_at.desc())
           .offset((page - 1) * page_size).limit(page_size).all())
    items = [{
        "pid": r.pid, "source_system": r.source_system.value, "source_record_id": r.source_record_id,
        "ingestion_run_id": r.ingestion_run_id, "loaded_at": r.loaded_at.isoformat() if r.loaded_at else None,
        "raw_payload": r.raw_payload, "mapped_fields": r.mapped_fields,
    } for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/v1/ingestion/quarantine")
def list_quarantine(
    source_system: Optional[str] = None, resolved: Optional[bool] = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    q = db.query(IngestionQuarantine)
    if source_system:
        q = q.filter(IngestionQuarantine.source_system == SourceSystem(source_system))
    if resolved is not None:
        q = q.filter(IngestionQuarantine.resolved.is_(resolved))
    total = q.count()
    rows = (q.order_by(IngestionQuarantine.detected_at.desc())
           .offset((page - 1) * page_size).limit(page_size).all())
    items = [{
        "id": r.id, "source_system": r.source_system.value, "ingestion_run_id": r.ingestion_run_id,
        "raw_record": r.raw_record, "reason_code": r.reason_code, "reason_detail": r.reason_detail,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        "resolved": r.resolved, "resolved_by": r.resolved_by,
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        "resolution_notes": r.resolution_notes,
    } for r in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.post("/api/v1/ingestion/quarantine/{quarantine_id}/resolve")
def resolve_quarantine(quarantine_id: int, body: QuarantineResolveRequest, db: Session = Depends(get_db),
                       user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    rec = db.query(IngestionQuarantine).get(quarantine_id)
    if not rec:
        raise HTTPException(404, "Quarantined record not found")
    rec.resolved = True
    rec.resolved_by = user.username
    rec.resolved_at = datetime.now(timezone.utc)
    rec.resolution_notes = body.resolution_notes
    db.commit()

    logger.bind(actor=user.username, context={
        "quarantine_id": quarantine_id, "source_system": rec.source_system.value,
        "reason_code": rec.reason_code, "resolution_notes": body.resolution_notes,
    }).info("Underwriter resolved quarantined record #{id} ({source}, {reason}).",
           id=quarantine_id, source=rec.source_system.value, reason=rec.reason_code)
    return {"id": quarantine_id, "resolved": True, "resolved_by": user.username}


# ---------- document intake (synthetic reports + Docling extraction) ----------
# Extraction-accuracy demo: synthetic valuation-report PDFs are generated from Ames property
# records (see app.synthetic_reports) — sometimes degraded to simulate an old scanned document
# (see app.degrade) — then run through Docling (layout/OCR) + an LLM (structured extraction
# only, see app.extraction) and scored against the known ground truth. Every document is
# clearly disclosed as synthetic, both in the PDF itself and in the API/UI.

def document_row(doc: SyntheticDocument) -> dict:
    return {
        "id": doc.id, "pid": doc.pid, "style": doc.style.value, "degraded": doc.degraded,
        "degradation_method": doc.degradation_method, "file_path": doc.file_path,
        "ground_truth": doc.ground_truth,
        "generated_at": doc.generated_at.isoformat() if doc.generated_at else None,
        "generated_by": doc.generated_by,
    }


def extraction_run_row(run: ExtractionRun, include_fields: bool = False) -> dict:
    out = {
        "run_id": run.id, "document_id": run.document_id, "status": run.status.value,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "docling_latency_ms": run.docling_latency_ms, "llm_latency_ms": run.llm_latency_ms,
        "llm_used": run.llm_used, "overall_field_accuracy": run.overall_field_accuracy,
        "error": run.error, "triggered_by": run.triggered_by,
    }
    if include_fields:
        out["fields"] = [{
            "id": f.id, "field_name": f.field_name, "extracted_value": f.extracted_value,
            "ground_truth_value": f.ground_truth_value, "match": f.match, "confidence": f.confidence,
            "routed_to_triage": f.routed_to_triage, "triage_resolved": f.triage_resolved,
            "triage_resolution": f.triage_resolution,
        } for f in run.fields]
    return out


@app.post("/api/v1/documents/generate")
def generate_documents(body: DocumentGenerateRequest, db: Session = Depends(get_db),
                       user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    style = SyntheticReportStyle(body.style)
    synthetic_reports.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    created = []
    not_found = []
    for pid in body.pids:
        result = synthetic_reports.render_synthetic_report_pdf(db, pid, style)
        if result is None:
            not_found.append(pid)  # no Property on file for this pid — surfaced below, not silently dropped
            continue
        pdf_bytes, ground_truth = result
        degradation_method = None
        if body.degrade:
            pdf_bytes = degrade_pdf(pdf_bytes, seed=str(pid))
            degradation_method = "img2pdf_photocopy_v1"
        suffix = "degraded" if body.degrade else "clean"
        path = synthetic_reports.DOCS_DIR / f"{pid}_{style.value}_{suffix}_{int(time.time())}.pdf"
        path.write_bytes(pdf_bytes)
        doc = SyntheticDocument(
            pid=pid, style=style, degraded=body.degrade, degradation_method=degradation_method,
            file_path=str(path.relative_to(_REPO_ROOT)), ground_truth=ground_truth,
            generated_by=user.username,
        )
        db.add(doc)
        db.flush()
        created.append(doc)
    db.commit()

    logger.bind(actor=user.username, context={
        "pids_requested": body.pids, "documents_created": len(created), "not_found": not_found,
        "style": style.value, "degraded": body.degrade,
    }).info("Generated {n} synthetic document(s) ({style}, degraded={degraded}); {nf} pid(s) not found.",
           n=len(created), style=style.value, degraded=body.degrade, nf=len(not_found))
    return {"documents": [document_row(d) for d in created], "not_found": not_found}


@app.get("/api/v1/documents")
def list_documents(
    degraded: Optional[bool] = None, style: Optional[str] = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    q = db.query(SyntheticDocument)
    if degraded is not None:
        q = q.filter(SyntheticDocument.degraded.is_(degraded))
    if style:
        q = q.filter(SyntheticDocument.style == SyntheticReportStyle(style))
    total = q.count()
    rows = (q.order_by(SyntheticDocument.id.desc())
           .offset((page - 1) * page_size).limit(page_size).all())
    return {"total": total, "page": page, "page_size": page_size,
            "items": [document_row(d) for d in rows]}


@app.get("/api/v1/documents/{document_id}/pdf")
def get_document_pdf(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Serves the actual generated (possibly degraded) PDF — the only way to see for
    yourself that Docling is reading a real document, not a mocked-up accuracy number."""
    doc = db.query(SyntheticDocument).get(document_id)
    if not doc:
        raise HTTPException(404, "Synthetic document not found")
    path = _REPO_ROOT / doc.file_path
    if not path.is_file():
        raise HTTPException(404, f"Document file missing on disk: {doc.file_path}")
    return Response(
        content=path.read_bytes(), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'})


@app.post("/api/v1/documents/{document_id}/extract")
def run_extraction(document_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    """Runs Docling + LLM extraction for one synthetic document. Docling requires a working
    model download from HuggingFace on first use in this deployment — if that (or the LLM
    call) fails, the ExtractionRun is still recorded as failed with the error message rather
    than silently vanishing; this endpoint surfaces it as a 502 pointing at that run."""
    try:
        run = extraction.extract_document(db, document_id, user.username)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Extraction failed — see the run detail for diagnostics: {e}")
    return extraction_run_row(run, include_fields=True)


@app.get("/api/v1/extraction/runs")
def list_extraction_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    runs = db.query(ExtractionRun).order_by(ExtractionRun.id.desc()).limit(100).all()
    return {"items": [extraction_run_row(r) for r in runs]}


@app.get("/api/v1/extraction/runs/{run_id}")
def get_extraction_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    run = db.query(ExtractionRun).get(run_id)
    if not run:
        raise HTTPException(404, "Extraction run not found")
    return extraction_run_row(run, include_fields=True)


@app.get("/api/v1/extraction/accuracy")
def extraction_accuracy(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Dashboard aggregate: overall/clean/degraded field accuracy and a per-field breakdown —
    "we extracted X% of fields correctly and flagged the ones we weren't sure about,"
    measurable because every synthetic document carries its own known ground truth."""
    rows = (db.query(ExtractionFieldResult, ExtractionRun, SyntheticDocument)
            .join(ExtractionRun, ExtractionRun.id == ExtractionFieldResult.run_id)
            .join(SyntheticDocument, SyntheticDocument.id == ExtractionRun.document_id)
            .filter(ExtractionRun.status == ExtractionRunStatus.SUCCEEDED)
            .all())
    if not rows:
        return {"overall_accuracy": None, "clean_accuracy": None, "degraded_accuracy": None,
                "per_field": [], "runs_scored": 0, "triage_queue_size": 0}

    scored = [(fr, doc) for fr, run, doc in rows if fr.match is not None]

    def accuracy_of(pairs):
        return (sum(1 for fr, _ in pairs if fr.match) / len(pairs)) if pairs else None

    clean_scored = [(fr, doc) for fr, doc in scored if not doc.degraded]
    degraded_scored = [(fr, doc) for fr, doc in scored if doc.degraded]

    per_field: dict = {}
    for fr, _run, _doc in rows:
        if fr.match is None:
            continue
        stat = per_field.setdefault(fr.field_name, {"n": 0, "correct": 0})
        stat["n"] += 1
        stat["correct"] += 1 if fr.match else 0
    per_field_list = sorted(
        [{"field": name, "accuracy": s["correct"] / s["n"], "n": s["n"]} for name, s in per_field.items()],
        key=lambda x: x["field"])

    triage_queue_size = db.query(ExtractionFieldResult).filter(
        ExtractionFieldResult.routed_to_triage.is_(True),
        ExtractionFieldResult.triage_resolved.is_(False)).count()

    return {
        "overall_accuracy": accuracy_of(scored), "clean_accuracy": accuracy_of(clean_scored),
        "degraded_accuracy": accuracy_of(degraded_scored), "per_field": per_field_list,
        "runs_scored": len({run.id for _fr, run, _doc in rows}), "triage_queue_size": triage_queue_size,
    }


@app.get("/api/v1/extraction/triage")
def list_extraction_triage(
    resolved: Optional[bool] = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    q = db.query(ExtractionFieldResult, ExtractionRun, SyntheticDocument) \
        .join(ExtractionRun, ExtractionRun.id == ExtractionFieldResult.run_id) \
        .join(SyntheticDocument, SyntheticDocument.id == ExtractionRun.document_id) \
        .filter(ExtractionFieldResult.routed_to_triage.is_(True))
    if resolved is not None:
        q = q.filter(ExtractionFieldResult.triage_resolved.is_(resolved))
    total = q.count()
    rows = (q.order_by(ExtractionFieldResult.id.desc())
           .offset((page - 1) * page_size).limit(page_size).all())
    items = [{
        "id": fr.id, "run_id": fr.run_id, "document_id": doc.id, "pid": doc.pid,
        "field_name": fr.field_name, "extracted_value": fr.extracted_value,
        "ground_truth_value": fr.ground_truth_value, "match": fr.match, "confidence": fr.confidence,
        "degraded": doc.degraded, "triage_resolved": fr.triage_resolved,
        "triage_resolution": fr.triage_resolution, "resolved_by": fr.resolved_by,
    } for fr, run, doc in rows]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.post("/api/v1/extraction/triage/{field_result_id}/resolve")
def resolve_extraction_triage(field_result_id: int, body: TriageFieldResolveRequest,
                              db: Session = Depends(get_db),
                              user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    fr = db.query(ExtractionFieldResult).get(field_result_id)
    if not fr:
        raise HTTPException(404, "Extraction field result not found")
    fr.triage_resolved = True
    fr.triage_resolution = body.resolution
    fr.resolved_by = user.username
    fr.resolved_at = datetime.now(timezone.utc)
    db.commit()

    logger.bind(actor=user.username, context={
        "field_result_id": field_result_id, "field_name": fr.field_name, "resolution": body.resolution,
    }).info("Underwriter resolved extraction triage field #{id} ({field}).",
           id=field_result_id, field=fr.field_name)
    return {"id": field_result_id, "resolved": True, "resolved_by": user.username}


# ---------- revaluation cycles ----------
# The periodic collateral-monitoring loop: run a cycle -> LTV distribution shifts -> triage
# queue refills -> underwriters work the queue (existing audit/triage endpoints above) -> cycle
# report exports. Market movement between cycles is injected as neighborhood-level index
# adjustments (see RevaluationRun docstring), never a market/time-series forecast.

@app.post("/api/v1/revaluations")
def run_revaluation(body: RevaluationRequest, db: Session = Depends(get_db),
                    user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    """Execute a new revaluation cycle: apply this run's neighborhood index adjustments to
    every asset's currently booked AVM value, refresh LTV, and flag assets whose
    period-over-period movement itself is a risk signal — a value drop beyond
    REVAL_VALUE_DROP_FLAG or an LTV at/above REVAL_LTV_FLAG — on top of the existing
    variance-vs-original-sale triage. This is a portfolio-wide write, gated the same as a
    triage decision (Underwriter/Admin), not Admin-only like model promotion: it's routine
    collateral monitoring, not a model risk decision."""
    # Parsed first, before any query/setup work, so an invalid date fails fast — and made
    # timezone-aware (naive ISO input defaults to UTC) to avoid PostgreSQL comparing it against
    # the column's tz-aware values under an implicit offset.
    try:
        as_of = datetime.fromisoformat(body.as_of_date) if body.as_of_date else datetime.now(timezone.utc)
    except ValueError:
        raise HTTPException(422, "as_of_date must be an ISO date/datetime string")
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    neighborhoods = sorted({r[0] for r in db.query(Property.neighborhood).distinct() if r[0]})
    if not neighborhoods:
        raise HTTPException(400, "No properties on file — seed the portfolio first")

    scenario_type = body.scenario_type
    if scenario_type == ScenarioType.BROAD_STRESS.value:
        if body.broad_shock_pct is None:
            raise HTTPException(422, "broad_shock_pct is required for a broad_stress scenario")
        adjustments = {n: float(body.broad_shock_pct) for n in neighborhoods}
    elif scenario_type == ScenarioType.TARGETED_STRESS.value:
        if not body.target_neighborhood or body.target_shock_pct is None:
            raise HTTPException(422, "target_neighborhood and target_shock_pct are required "
                                     "for a targeted_stress scenario")
        if body.target_neighborhood not in neighborhoods:
            raise HTTPException(422, f"Unknown neighborhood {body.target_neighborhood!r}")
        adjustments = {n: (float(body.target_shock_pct) if n == body.target_neighborhood else 0.0)
                       for n in neighborhoods}
    elif scenario_type == ScenarioType.CUSTOM.value:
        supplied = body.custom_adjustments or {}
        unknown = sorted(set(supplied) - set(neighborhoods))
        if unknown:
            raise HTTPException(422, f"Unknown neighborhood(s): {unknown}")
        adjustments = {n: float(supplied.get(n, 0.0)) for n in neighborhoods}
    else:  # organic — deterministic per-(as_of_date, neighborhood) small drift, not a forecast
        # Falling back to a fixed literal here (e.g. "auto") would make every date-omitting
        # caller draw the exact same "random" adjustments on every run; as_of.isoformat() carries
        # microsecond resolution from datetime.now(), so omitted-date runs still get distinct seeds.
        as_of_key = body.as_of_date or as_of.isoformat()
        adjustments = {
            n: round(random.Random(f"reval:{as_of_key}:{n}").uniform(*ORGANIC_DRIFT_RANGE), 4)
            for n in neighborhoods
        }

    champ = db.query(RegisteredModel).filter(RegisteredModel.status == ModelStatus.CHAMPION).one_or_none()
    run = RevaluationRun(
        as_of_date=as_of, scenario_type=scenario_type,
        scenario_name=body.scenario_name or SCENARIO_LABELS[scenario_type],
        index_adjustments=adjustments, notes=body.notes or "",
        model_id=champ.id if champ else None, created_by=user.username,
    )
    db.add(run)

    rows = (db.query(Property, BankPortfolioMeta)
            .join(BankPortfolioMeta, BankPortfolioMeta.pid == Property.pid).all())
    flagged_count = 0
    value_deltas = []
    for prop, meta in rows:
        prior_value = float(meta.current_avm_value)
        prior_ltv = float(meta.current_loan_balance) / prior_value if prior_value else 0.0
        idx = adjustments.get(prop.neighborhood, 0.0)
        new_value = round(prior_value * (1 + idx), 2)
        new_ltv = float(meta.current_loan_balance) / new_value if new_value else 0.0
        value_delta_pct = (new_value - prior_value) / prior_value if prior_value else 0.0
        ltv_delta = new_ltv - prior_ltv
        value_deltas.append(value_delta_pct)

        reasons = []
        if value_delta_pct <= REVAL_VALUE_DROP_FLAG:
            reasons.append("value_drop_gt_10pct")
        if new_ltv >= REVAL_LTV_FLAG:
            reasons.append("ltv_crossed_80" if prior_ltv < REVAL_LTV_FLAG else "ltv_remains_gte_80")
        flagged = bool(reasons)
        if flagged:
            flagged_count += 1

        sale = float(prop.sale_price) if prop.sale_price else 0.0
        variance = (new_value - sale) / sale if sale else 0.0
        base_status = (
            AuditStatus.FLAGGED_HIGH_VARIANCE if abs(variance) > 0.15 else
            AuditStatus.PENDING_REVIEW if abs(variance) > 0.08 else AuditStatus.APPROVED)
        status_after = AuditStatus.FLAGGED_HIGH_VARIANCE if flagged else base_status

        meta.current_avm_value = new_value
        meta.avm_variance_pct = round(variance, 4)
        meta.audit_status = status_after

        db.add(RevaluationResult(
            pid=prop.pid, prior_value=prior_value, new_value=new_value,
            value_delta_pct=round(value_delta_pct, 4), prior_ltv=round(prior_ltv, 4),
            new_ltv=round(new_ltv, 4), ltv_delta=round(ltv_delta, 4),
            flagged=flagged, flag_reasons=reasons, audit_status_after=status_after,
            run=run,
        ))

    db.commit()
    avg_delta = sum(value_deltas) / len(value_deltas) if value_deltas else 0.0

    logger.bind(actor=user.username, context={
        "run_id": run.id, "scenario_type": scenario_type, "scenario_name": run.scenario_name,
        "assets_revalued": len(rows), "flagged_count": flagged_count,
        "avg_value_delta_pct": round(avg_delta, 4),
    }).info("Revaluation cycle #{run_id} ({scenario}) completed: {n} assets, {flagged} flagged.",
           run_id=run.id, scenario=run.scenario_name, n=len(rows), flagged=flagged_count)

    return {"run_id": run.id, "scenario_name": run.scenario_name, "assets_revalued": len(rows),
            "flagged_count": flagged_count, "avg_value_delta_pct": round(avg_delta, 4)}


@app.get("/api/v1/revaluations")
def list_revaluations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Cycle history, newest first, with per-run summary stats aggregated in one grouped
    query rather than one query per run."""
    runs = db.query(RevaluationRun).order_by(RevaluationRun.id.desc()).all()
    if not runs:
        return {"items": []}
    agg_rows = (db.query(
            RevaluationResult.run_id, func.count(RevaluationResult.id),
            func.avg(RevaluationResult.value_delta_pct),
            func.sum(case((RevaluationResult.flagged.is_(True), 1), else_=0)),
        ).group_by(RevaluationResult.run_id).all())
    agg_by_run = {r[0]: r[1:] for r in agg_rows}
    return {"items": [revaluation_run_row(r, agg_by_run.get(r.id, (0, 0.0, 0))) for r in runs]}


@app.get("/api/v1/revaluations/{run_id}")
def get_revaluation(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """One cycle's full detail: the index adjustments actually applied, before/after LTV
    distribution, and the largest movers — backs the Revaluation Cycles run-detail panel."""
    run = db.query(RevaluationRun).get(run_id)
    if not run:
        raise HTTPException(404, "Revaluation run not found")
    results = db.query(RevaluationResult).filter(RevaluationResult.run_id == run_id).all()
    n = len(results) or 1
    flagged = sum(1 for r in results if r.flagged)
    avg_delta = sum(r.value_delta_pct for r in results) / n

    ltv_before = [{"bucket": name, "count": sum(1 for r in results if lo <= r.prior_ltv < hi)}
                  for name, lo, hi in LTV_BUCKETS]
    ltv_after = [{"bucket": name, "count": sum(1 for r in results if lo <= r.new_ltv < hi)}
                 for name, lo, hi in LTV_BUCKETS]

    top_movers = sorted(results, key=lambda r: abs(r.value_delta_pct), reverse=True)[:10]
    mover_pids = [r.pid for r in top_movers]
    props = {p.pid: p for p in db.query(Property).filter(Property.pid.in_(mover_pids))} if mover_pids else {}

    return {
        "run_id": run.id, "as_of_date": run.as_of_date.isoformat() if run.as_of_date else None,
        "scenario_name": run.scenario_name, "scenario_type": run.scenario_type.value,
        "model_id": run.model_id, "created_by": run.created_by,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "notes": run.notes, "index_adjustments": run.index_adjustments,
        "asset_count": len(results), "flagged_count": flagged,
        "avg_value_delta_pct": round(avg_delta, 4),
        "ltv_distribution_before": ltv_before, "ltv_distribution_after": ltv_after,
        "top_movers": [
            {"pid": r.pid, "neighborhood": props[r.pid].neighborhood if r.pid in props else None,
             "prior_value": float(r.prior_value), "new_value": float(r.new_value),
             "value_delta_pct": r.value_delta_pct, "prior_ltv": r.prior_ltv, "new_ltv": r.new_ltv,
             "flagged": r.flagged, "flag_reasons": r.flag_reasons}
            for r in top_movers
        ],
    }


@app.get("/api/v1/revaluations/{run_id}/flagged")
def revaluation_flagged(
    run_id: int, page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """The triage queue this cycle refilled: assets flagged for a period-over-period value
    drop or an LTV breach, ranked by |value_delta_pct|. Asset cards reflect current (not
    as-of-this-run) state, since later cycles or triage decisions may have moved on since."""
    if not db.query(RevaluationRun.id).filter(RevaluationRun.id == run_id).scalar():
        raise HTTPException(404, "Revaluation run not found")
    rows = (db.query(RevaluationResult, Property)
            .join(Property, Property.pid == RevaluationResult.pid)
            .options(joinedload(Property.meta), joinedload(Property.images))
            .filter(RevaluationResult.run_id == run_id, RevaluationResult.flagged.is_(True))
            .all())
    items = [
        {**card(p), "value_delta_pct": r.value_delta_pct, "prior_value": float(r.prior_value),
         "new_value": float(r.new_value), "prior_ltv": r.prior_ltv, "new_ltv": r.new_ltv,
         "flag_reasons": r.flag_reasons}
        for r, p in rows
    ]
    items.sort(key=lambda it: abs(it["value_delta_pct"]), reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    return {"run_id": run_id, "total": total, "page": page, "page_size": page_size,
            "items": items[start:start + page_size]}


@app.get("/api/v1/revaluations/{run_id}/report")
def revaluation_report(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Revaluation Cycle Report (PDF): scenario, index adjustments applied, LTV distribution
    shift, and the flagged/top-mover assets from this cycle, with an AI-drafted executive
    summary grounded on that same data — same IVS 103 / Red Book framing and LLM-narrates-
    never-computes guarantee as the other exported reports (see app.reports)."""
    start = time.perf_counter()
    try:
        pdf_bytes = reports.render_revaluation_report_pdf(db, run_id, user)
    except Exception as e:
        logger.bind(actor=user.username, context={"run_id": run_id, "error": str(e)}).error(
            "Revaluation cycle report generation failed for run {run_id}: {error}",
            run_id=run_id, error=str(e))
        raise HTTPException(500, "Report generation failed")
    if pdf_bytes is None:
        raise HTTPException(404, "Revaluation run not found")
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.bind(actor=user.username, context={
        "report_type": "revaluation_cycle", "run_id": run_id, "generation_ms": latency_ms,
    }).info("Exported revaluation cycle report for run {run_id} ({latency}ms).",
           run_id=run_id, latency=latency_ms)
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="trident-val_revaluation_cycle_{run_id}.pdf"'})


# ---------- AI copilot proxy ----------
# page-agent (frontend) speaks the OpenAI chat-completions schema. This proxy keeps the
# real LLM API key server-side and lets us pin/swap the model without a frontend change.
# page-agent's OpenAI client never sets `stream`, so this proxy is intentionally non-streaming.
COPILOT_PROVIDER_BASE_URL = os.environ.get(
    "COPILOT_PROVIDER_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
COPILOT_PROVIDER_API_KEY = os.environ.get("COPILOT_PROVIDER_API_KEY", "")
COPILOT_MODEL = os.environ.get("COPILOT_MODEL", "gemini-2.5-flash")
copilot_http_client = httpx.AsyncClient(timeout=60)


@app.on_event("shutdown")
async def close_copilot_http_client():
    await copilot_http_client.aclose()


@app.post("/api/v1/copilot/chat/completions")
async def copilot_chat_completions(request: Request, user: User = Depends(get_current_user)):
    if not COPILOT_PROVIDER_API_KEY:
        raise HTTPException(503, "Copilot is not configured: set COPILOT_PROVIDER_API_KEY")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object")
    body["model"] = COPILOT_MODEL  # the browser never chooses the model or sees the key
    try:
        upstream = await copilot_http_client.post(
            f"{COPILOT_PROVIDER_BASE_URL}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {COPILOT_PROVIDER_API_KEY}"},
        )
    except httpx.TimeoutException:
        raise HTTPException(504, "Upstream LLM provider timed out")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Upstream LLM provider error: {e}")
    return Response(content=upstream.content, status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/json"))


# ---------- logging / audit trail ----------

class ClientLogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    level: str = Field("INFO", description="DEBUG | INFO | WARN | ERROR")
    logger_name: str = Field("frontend", alias="logger")
    message: str
    pid: Optional[int] = None
    context: Optional[dict] = None


def log_row(r: SystemLog) -> dict:
    return {
        "id": r.id, "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "source": r.source, "level": r.level, "logger": r.logger_name,
        "message": r.message, "pid": r.pid, "context": r.context, "actor": r.actor,
    }


@app.get("/api/v1/logs")
def list_logs(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN)),
    source: Optional[str] = Query(None, pattern="^(backend|frontend)$"),
    level: Optional[str] = None,
    pid: Optional[int] = None,
    actor: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Query the unified audit/operational log ledger. Restricted to Underwriter/Admin —
    this is the compliance-sensitive record of everyone's actions, not just current-state
    data. Flip to Depends(get_current_user) if Viewers should read it too."""
    q = db.query(SystemLog)
    if source:
        q = q.filter(SystemLog.source == source)
    if level:
        q = q.filter(SystemLog.level == level.upper())
    if actor:
        q = q.filter(SystemLog.actor == actor)
    if pid is not None:
        q = q.filter(SystemLog.pid == pid)
    if search:
        q = q.filter(SystemLog.message.ilike(f"%{search}%"))

    total = q.count()
    rows = (q.order_by(SystemLog.timestamp.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return {"total": total, "page": page, "page_size": page_size,
            "items": [log_row(r) for r in rows]}


VALID_LOG_LEVELS = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}
LEVEL_ALIASES = {"TRACE": "DEBUG", "WARN": "WARNING"}


CLIENT_LOG_BATCH_LIMIT = 50


@app.post("/api/v1/logs/client", status_code=204)
def log_client_event(entries: list[ClientLogEntry], request: Request):
    """Ingest a batch of frontend (loglevel) log entries into the shared ledger.

    Deliberately left open (no login required) — this is the endpoint through which
    the frontend reports its own errors, including pre-login and 401s themselves;
    gating it risks a 401-reporting-a-401 loop. Since it's unauthenticated, batch size
    is capped so it can't be used to flood system_logs with unbounded writes. `actor` is
    attached opportunistically from the session when one exists, never required, and
    never trusts a client-supplied value (ClientLogEntry has no actor field at all)."""
    if len(entries) > CLIENT_LOG_BATCH_LIMIT:
        raise HTTPException(400, f"Batch exceeds the {CLIENT_LOG_BATCH_LIMIT}-entry limit per request.")
    actor = request.session.get("username")
    for e in entries:
        raw = e.level.upper()
        level = LEVEL_ALIASES.get(raw, raw)
        if level not in VALID_LOG_LEVELS:
            level = "INFO"
        logger.bind(source="frontend", pid=e.pid, context=e.context,
                   logger_name=e.logger_name, actor=actor).log(
            level, "[frontend:{logger}] {message}", logger=e.logger_name, message=e.message)
