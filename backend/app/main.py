import csv
import io
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, aliased, joinedload
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # picks up a repo-root .env for local (non-Docker) runs; no-op if absent

from . import inference, reports
from .auth import DUMMY_PASSWORD_HASH, get_current_user, require_role, verify_password
from .db import Base, engine, get_db
from .logging_config import setup_logging
from .models import (AuditStatus, BankPortfolioMeta, ModelStatus, ModelValuation,
                     Property, PropertyImage, RegisteredModel, SystemLog, User, UserRole)

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
    p = db.query(Property).options(joinedload(Property.meta),
                                   joinedload(Property.images)).get(pid)
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
