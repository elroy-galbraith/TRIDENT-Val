"""Exported valuation reports — per-asset decision report and portfolio review summary.

Framing matters here: this is deliberately *not* "the AVM's valuation report". Under IVS, no
model output — an AVM included — constitutes a compliant valuation without a valuer's
professional judgement applied to it. What this module assembles is the underwriter's
decision record, supported by AVM output, structured against the IVS 103 / RICS Red Book
VPS 6 minimum-content skeleton (asset identification, valuation date, basis of value,
approach and model used, key inputs and significant assumptions, limitations, status of the
preparer) — see REPORT_STATUS_STATEMENT below for the exact, deliberately-hedged language.

Every figure in these reports is pulled from the database or the same inference pipeline
that powers the Inspector page — nothing is computed freshly for the PDF. The only generated
text is a handful of narrative paragraphs drafted by app.narrative from that same data, kept
in their own visibly-delimited section of the template.
"""
import logging as stdlib_logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlalchemy.orm import Session, aliased, joinedload
from weasyprint import HTML

from . import inference, narrative
from .models import (AuditStatus, BankPortfolioMeta, ModelStatus, ModelValuation,
                     Property, RegisteredModel, SystemLog, User)

# WeasyPrint logs unsupported-CSS-property warnings via stdlib logging at WARNING level;
# left at the default it competes with loguru's console formatting for no operational value.
stdlib_logging.getLogger("weasyprint").setLevel(stdlib_logging.ERROR)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),  # notes/rationale are free-text user input
    trim_blocks=True, lstrip_blocks=True,
)
_env.filters["usd"] = lambda v: "—" if v is None else f"${float(v):,.0f}"
_env.filters["pct"] = lambda v, digits=1: "—" if v is None else f"{float(v) * 100:.{digits}f}%"
_env.filters["pct_signed"] = (
    lambda v, digits=1: "—" if v is None else f"{'+' if v >= 0 else ''}{float(v) * 100:.{digits}f}%")
_env.filters["dt"] = lambda v: "—" if v is None else v.strftime("%Y-%m-%d %H:%M") + " UTC"

LTV_BUCKETS = [("<60%", 0.0, 0.60), ("60-80%", 0.60, 0.80), (">80%", 0.80, 99.0)]
DISAGREEMENT_THRESHOLD = 0.10  # matches ModelCompare's default triage threshold

BASIS_OF_VALUE = (
    "Market Value, as defined in IVS 104: the estimated amount for which the asset should "
    "exchange on the valuation date between a willing buyer and a willing seller in an "
    "arm’s-length transaction, after proper marketing, wherein the parties had each acted "
    "knowledgeably, prudently, and without compulsion."
)

APPROACH_TEXT = (
    "Market approach, statistical implementation. IVS 105 recognizes three valuation "
    "approaches (market, income, cost); this estimate is produced by an automated valuation "
    "model (AVM) trained on comparable transaction evidence — a statistical implementation "
    "of the market approach, not an income or cost approach."
)

REPORT_STATUS_STATEMENT = (
    "This is an underwriter decision record, supported by an automated valuation model (AVM) "
    "output — it is not, and does not purport to be, a RICS Red Book valuation report "
    "prepared by a Registered Valuer. Under IVS, no model output constitutes a compliant "
    "valuation without a valuer’s professional judgement applied to it; that judgement is "
    "exercised by the named underwriter in the sign-off section of this document, not by the "
    "model. This document is structured in accordance with IVS 103 / RICS Red Book VPS 6 "
    "reporting requirements — it is not represented as RICS-compliant, which requires a "
    "Registered Valuer’s direct involvement."
)

REPORT_STATUS_STATEMENT_PORTFOLIO = (
    "This is a portfolio governance summary, supported by automated valuation model (AVM) "
    "output — it is not a valuation opinion for any individual asset and does not purport to "
    "be a RICS Red Book valuation report prepared by a Registered Valuer. It aggregates "
    "individual underwriter decision records, each of which requires its own named "
    "reviewer's professional judgement (see the per-asset Decision Report for any property "
    "referenced here). This document is structured in accordance with IVS 103 / RICS Red "
    "Book VPS 6 reporting requirements — it is not represented as RICS-compliant, which "
    "requires a Registered Valuer’s direct involvement."
)

MODEL_LIMITATIONS = [
    "Trained on Ames, Iowa sales from 2006–2010 — not localized to any specific bank's "
    "actual markets. Treat estimates as directional, not a substitute for local comparable "
    "evidence.",
    "A static snapshot: the model has no knowledge of interest-rate, inflation, or market "
    "conditions after its training data was collected, and needs periodic retraining to stay "
    "current.",
    "Limited to its registered input set; quality/condition fields are ordinal ratings entered "
    "at assessment time, not independently re-verified by a human inspector for this report.",
    "Every output is a point estimate plus a statistical error band, not a certified appraisal "
    "— one input to underwriter review, not a substitute for it.",
    "No fairness or disparate-impact audit has been performed on this model; it is not "
    "approved for standalone credit decisions.",
]

GOVERNANCE_METHODOLOGY = [
    "Exactly one registered model is the champion at any time; its valuation is what gets "
    "booked onto every asset. Every other registered model is a challenger — it scores the "
    "whole portfolio in shadow, alongside the champion, and never books a value on its own.",
    "Audit triage is variance-based: an asset is Flagged: High Variance where the booked AVM "
    "value diverges from its recorded baseline sale price by more than 15%, Pending Review "
    "between 8–15%, and Approved below 8%.",
    "Where champion and challenger diverge by more than 10% on an asset, it routes to the "
    "disagreement queue for a human decision — book the champion, book the challenger, or a "
    "manual override — logged with a rationale to the audit ledger.",
    "Promoting a challenger to champion is a separate, deliberate, admin-only act that "
    "re-books the whole portfolio in one pass; it is not a per-asset choice.",
]

STATUS_CLASS = {
    AuditStatus.APPROVED.value: "ok",
    AuditStatus.PENDING_REVIEW.value: "amber",
    AuditStatus.FLAGGED_HIGH_VARIANCE.value: "flag",
}


# ---------- small local helpers (deliberately not imported from app.main, which would
# import this module back for the endpoints below — see the module docstring) ----------

def _champion(db: Session) -> Optional[RegisteredModel]:
    return db.query(RegisteredModel).filter(RegisteredModel.status == ModelStatus.CHAMPION).one_or_none()


def _resolve_challenger(db: Session, model_id: Optional[str]) -> Optional[RegisteredModel]:
    if model_id:
        return db.query(RegisteredModel).get(model_id)
    return (db.query(RegisteredModel).filter(RegisteredModel.status == ModelStatus.CHALLENGER)
            .order_by(RegisteredModel.id).first())


def _recent_audit_trail(db: Session, pid: int, limit: int = 8) -> list[dict]:
    """The last few attributed system_logs entries for this asset — triage decisions, audit
    status changes, notes updates. This *is* the sign-off trail: the report doesn't maintain
    a separate signature table, it reads the same ledger the Inspector's audit lifecycle box
    already writes to."""
    rows = (db.query(SystemLog)
            .filter(SystemLog.pid == pid, SystemLog.actor.isnot(None))
            .order_by(SystemLog.timestamp.desc())
            .limit(limit)
            .all())
    if not rows:
        return []
    roles = {u.username: u.role.value for u in
             db.query(User).filter(User.username.in_({r.actor for r in rows}))}
    return [{"timestamp": r.timestamp, "actor": r.actor, "actor_role": roles.get(r.actor),
             "message": r.message} for r in rows]


def _valuation_date(db: Session, pid: int, resolved_model_id: Optional[str],
                    audit_trail: list[dict]) -> Optional[datetime]:
    """IVS 103's "valuation date" — the date the value opinion applies to. For a model-backed
    valuation that's when the shadow-scoring ledger computed it; a manual override has no
    model computation behind it, so fall back to when it was actually booked (the most recent
    audit-trail timestamp)."""
    if resolved_model_id:
        computed_at = db.query(ModelValuation.computed_at).filter(
            ModelValuation.pid == pid, ModelValuation.model_id == resolved_model_id).scalar()
        if computed_at:
            return computed_at
    return audit_trail[0]["timestamp"] if audit_trail else None


# ---------- per-asset decision report ----------

def asset_report_context(db: Session, pid: int, exported_by: User) -> Optional[dict]:
    prop = db.query(Property).options(joinedload(Property.meta)).get(pid)
    if not prop or not prop.meta:
        return None
    meta = prop.meta
    champion = _champion(db)
    effective_model_id = meta.resolved_model_id or (champion.id if champion else None)
    effective_model = db.query(RegisteredModel).get(effective_model_id) if effective_model_id else None
    baseline = inference.valuate_with_drivers(prop.features, effective_model_id) if effective_model_id else None

    rows = (db.query(ModelValuation, RegisteredModel)
            .join(RegisteredModel, RegisteredModel.id == ModelValuation.model_id)
            .filter(ModelValuation.pid == pid)
            .order_by(RegisteredModel.status, RegisteredModel.id).all())
    champ_value = next((float(mv.estimated_value) for mv, rm in rows
                        if rm.status == ModelStatus.CHAMPION), None)
    comparison = []
    max_abs_divergence = 0.0
    for mv, rm in rows:
        value = float(mv.estimated_value)
        divergence = None
        if champ_value and rm.status != ModelStatus.CHAMPION:
            divergence = (value - champ_value) / champ_value
            max_abs_divergence = max(max_abs_divergence, abs(divergence))
        comparison.append({
            "model_id": rm.id, "model_name": rm.name, "status": rm.status.value,
            "value": value, "divergence_pct": divergence,
            "is_booked": rm.id == meta.resolved_model_id,
        })
    has_disagreement = max_abs_divergence > DISAGREEMENT_THRESHOLD

    audit_trail = _recent_audit_trail(db, pid)
    last_action = audit_trail[0] if audit_trail else None
    valuation_date = _valuation_date(db, pid, meta.resolved_model_id, audit_trail)
    sale = float(prop.sale_price) if prop.sale_price else 0.0

    llm_payload = {
        "asset": {"pid": pid, "neighborhood": prop.neighborhood, "building_type": prop.bldg_type,
                  "house_style": prop.house_style, "year_built": prop.year_built},
        "valuation": {
            "booked_value_usd": float(meta.current_avm_value),
            "value_band_low_usd": baseline["value_low"] if baseline else None,
            "value_band_high_usd": baseline["value_high"] if baseline else None,
            "baseline_recorded_sale_price_usd": sale,
            "variance_vs_baseline_pct": meta.avm_variance_pct,
            "loan_balance_usd": float(meta.current_loan_balance), "ltv": round(meta.ltv, 4),
        },
        "audit_status": meta.audit_status.value,
        "top_value_drivers": baseline["top_drivers"] if baseline else [],
        "top_value_detractors": baseline["top_detractors"] if baseline else [],
        "champion_challenger_comparison": [
            {"model_name": c["model_name"], "status": c["status"], "value_usd": c["value"],
             "divergence_vs_champion_pct": c["divergence_pct"], "is_booked": c["is_booked"]}
            for c in comparison
        ],
        "disagreement_beyond_10pct": has_disagreement,
        "manual_override": meta.resolved_model_id is None,
        "underwriter_notes": meta.underwriter_notes or "",
        "most_recent_recorded_action": last_action["message"] if last_action else None,
    }
    drafted = narrative.draft_asset_narrative(llm_payload, pid)

    return {
        "pid": pid, "prop": prop, "meta": meta,
        "asset_label": f"{prop.neighborhood} · {prop.bldg_type} · {prop.house_style}",
        "total_sqft": (prop.gr_liv_area or 0) + (prop.total_bsmt_sf or 0),
        "effective_model": effective_model,
        "baseline": baseline,
        "comparison": comparison,
        "has_disagreement": has_disagreement,
        "audit_trail": audit_trail,
        "last_action": last_action,
        "valuation_date": valuation_date,
        "generated_at": datetime.now(timezone.utc),
        "exported_by": exported_by,
        "basis_of_value": BASIS_OF_VALUE,
        "approach_text": APPROACH_TEXT,
        "report_status_statement": REPORT_STATUS_STATEMENT,
        "model_limitations": MODEL_LIMITATIONS,
        "status_class": STATUS_CLASS,
        "narrative": drafted,
        "llm_used": narrative.is_configured(),
        "llm_model_label": f"{narrative.REPORT_LLM_MODEL} (via OpenRouter)",
    }


def render_asset_report_pdf(db: Session, pid: int, exported_by: User) -> Optional[bytes]:
    ctx = asset_report_context(db, pid, exported_by)
    if ctx is None:
        return None
    html = _env.get_template("asset_report.html").render(**ctx)
    return HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()


# ---------- portfolio review summary ----------

def portfolio_report_context(db: Session, exported_by: User, champion_id: Optional[str] = None,
                             challenger_id: Optional[str] = None) -> dict:
    champ = db.query(RegisteredModel).get(champion_id) if champion_id else _champion(db)
    chal = _resolve_challenger(db, challenger_id)

    exposure, valuation, n = db.query(
        func.sum(BankPortfolioMeta.current_loan_balance),
        func.sum(BankPortfolioMeta.current_avm_value),
        func.count(BankPortfolioMeta.pid)).one()
    metas = db.query(BankPortfolioMeta.current_loan_balance, BankPortfolioMeta.current_avm_value).all()
    ltvs = [float(b) / float(v) for b, v in metas if v]
    ltv_buckets = [{"bucket": name, "count": sum(1 for l in ltvs if lo <= l < hi)}
                   for name, lo, hi in LTV_BUCKETS]
    status_counts = {s.value: db.query(func.count(BankPortfolioMeta.pid)).filter(
        BankPortfolioMeta.audit_status == s).scalar() for s in AuditStatus}

    geo_rows = (db.query(Property.neighborhood, func.count(Property.pid),
                         func.sum(BankPortfolioMeta.current_loan_balance))
               .join(BankPortfolioMeta).group_by(Property.neighborhood)
               .order_by(func.sum(BankPortfolioMeta.current_loan_balance).desc()).all())
    neighborhoods = [{"neighborhood": g[0], "count": g[1], "exposure": float(g[2])} for g in geo_rows]

    decided_assets = db.query(func.count(func.distinct(SystemLog.pid))).filter(
        SystemLog.message.ilike("%triage decision for PID%")).scalar()

    compare = None
    if champ and chal:
        mv_champ, mv_chal = aliased(ModelValuation), aliased(ModelValuation)
        rows = (db.query(Property.pid, Property.neighborhood, Property.sale_price,
                         mv_champ.estimated_value, mv_chal.estimated_value)
                .join(mv_champ, (mv_champ.pid == Property.pid) & (mv_champ.model_id == champ.id))
                .join(mv_chal, (mv_chal.pid == Property.pid) & (mv_chal.model_id == chal.id))
                .all())
        divergences, champ_err, chal_err = [], [], []
        seg: dict[str, dict] = {}
        for pid_, nbhd, sale_price, va_dec, vb_dec in rows:
            va, vb, sale = float(va_dec), float(vb_dec), float(sale_price)
            divergence_pct = (vb - va) / va if va else 0.0
            divergences.append(abs(divergence_pct))
            champ_err.append(abs(va - sale) / sale if sale else 0.0)
            chal_err.append(abs(vb - sale) / sale if sale else 0.0)
            s = seg.setdefault(nbhd, {"neighborhood": nbhd, "n": 0, "err_champ": 0.0, "err_chal": 0.0})
            s["n"] += 1
            s["err_champ"] += abs(va - sale) / sale if sale else 0.0
            s["err_chal"] += abs(vb - sale) / sale if sale else 0.0
        nrows = len(rows) or 1
        compare = {
            "champion": champ, "challenger": chal,
            "n": len(rows),
            "mape_champion": sum(champ_err) / nrows,
            "mape_challenger": sum(chal_err) / nrows,
            "mean_abs_divergence_pct": sum(divergences) / nrows,
            "agreement_within_10pct_share": sum(1 for d in divergences if d <= 0.10) / nrows,
            "segment_breakdown": sorted(
                [{"neighborhood": s["neighborhood"], "n": s["n"],
                  "mape_champion": s["err_champ"] / s["n"], "mape_challenger": s["err_chal"] / s["n"]}
                 for s in seg.values()], key=lambda s: s["n"], reverse=True)[:8],
        }

    as_of = db.query(func.max(ModelValuation.computed_at)).scalar()

    llm_payload = {
        "portfolio": {
            "asset_count": n, "total_exposure_usd": float(exposure or 0),
            "total_avm_valuation_usd": float(valuation or 0),
            "avg_ltv": round(sum(ltvs) / len(ltvs), 4) if ltvs else None,
        },
        "ltv_distribution": ltv_buckets,
        "audit_triage_outcomes": status_counts,
        "assets_with_a_logged_triage_decision": decided_assets,
        "champion_vs_challenger": (
            {"champion_model": compare["champion"].name, "challenger_model": compare["challenger"].name,
             "mape_champion": compare["mape_champion"], "mape_challenger": compare["mape_challenger"],
             "mean_abs_divergence_pct": compare["mean_abs_divergence_pct"],
             "agreement_within_10pct_share": compare["agreement_within_10pct_share"]}
            if compare else None),
        "top_neighborhoods_by_exposure": neighborhoods[:10],
    }
    drafted = narrative.draft_portfolio_narrative(llm_payload)

    return {
        "asset_count": n, "total_exposure": float(exposure or 0), "total_valuation": float(valuation or 0),
        "equity_cushion": float(valuation or 0) - float(exposure or 0),
        "avg_ltv": (sum(ltvs) / len(ltvs)) if ltvs else None,
        "ltv_buckets": ltv_buckets, "status_counts": status_counts,
        "neighborhoods": neighborhoods[:10], "neighborhoods_total": len(neighborhoods),
        "decided_assets": decided_assets,
        "champion": champ, "challenger": chal, "compare": compare,
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc),
        "exported_by": exported_by,
        "report_status_statement": REPORT_STATUS_STATEMENT_PORTFOLIO,
        "status_class": STATUS_CLASS,
        "governance_methodology": GOVERNANCE_METHODOLOGY,
        "narrative": drafted,
        "llm_used": narrative.is_configured(),
        "llm_model_label": f"{narrative.REPORT_LLM_MODEL} (via OpenRouter)",
    }


def render_portfolio_report_pdf(db: Session, exported_by: User, champion_id: Optional[str] = None,
                                challenger_id: Optional[str] = None) -> bytes:
    ctx = portfolio_report_context(db, exported_by, champion_id, challenger_id)
    html = _env.get_template("portfolio_report.html").render(**ctx)
    return HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
