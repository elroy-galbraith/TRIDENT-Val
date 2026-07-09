import enum

from sqlalchemy import (JSON, BigInteger, Boolean, Column, DateTime, Enum, Float,
                        ForeignKey, Integer, Numeric, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class AuditStatus(str, enum.Enum):
    APPROVED = "Approved"
    PENDING_REVIEW = "Pending Review"
    FLAGGED_HIGH_VARIANCE = "Flagged: High Variance"


class ModelStatus(str, enum.Enum):
    CHAMPION = "Champion"      # exactly one at a time; the value that gets booked
    CHALLENGER = "Challenger"  # scores the whole portfolio in shadow, never booked
    RETIRED = "Retired"        # kept for history/audit, no longer scored at seed time


class Property(Base):
    __tablename__ = "properties"

    pid = Column(BigInteger, primary_key=True)
    neighborhood = Column(String(32), index=True)
    bldg_type = Column(String(16), index=True)
    house_style = Column(String(16))
    ms_zoning = Column(String(8))
    year_built = Column(Integer)
    overall_qual = Column(Integer)
    overall_cond = Column(Integer)
    gr_liv_area = Column(Integer)
    total_bsmt_sf = Column(Integer)
    full_bath = Column(Integer)
    half_bath = Column(Integer)
    bedroom_abvgr = Column(Integer)
    sale_price = Column(Numeric(12, 2))       # baseline observed sale (ground truth)
    features = Column(JSON)                    # full model feature vector (glass-box matrix)
    lat = Column(Float)                         # geocoded at seed time, see app.geo
    lng = Column(Float)

    meta = relationship("BankPortfolioMeta", back_populates="prop", uselist=False,
                        cascade="all, delete-orphan")
    images = relationship("PropertyImage", back_populates="prop", order_by="PropertyImage.sort_order",
                          cascade="all, delete-orphan")


class BankPortfolioMeta(Base):
    __tablename__ = "bank_portfolio_meta"

    pid = Column(BigInteger, ForeignKey("properties.pid"), primary_key=True)
    current_loan_balance = Column(Numeric(12, 2), nullable=False)
    current_avm_value = Column(Numeric(12, 2), nullable=False)
    avm_variance_pct = Column(Float, nullable=False)  # (AVM - SalePrice) / SalePrice
    audit_status = Column(Enum(AuditStatus, values_callable=lambda e: [m.value for m in e]),
                          default=AuditStatus.PENDING_REVIEW, index=True)
    underwriter_notes = Column(Text, default="")
    # Which registered model's valuation is currently booked as current_avm_value. Defaults to
    # the champion at seed time; a triage decision can override it to a challenger or "manual".
    resolved_model_id = Column(String(64), ForeignKey("models.id"), nullable=True)

    prop = relationship("Property", back_populates="meta")
    resolved_model = relationship("RegisteredModel")

    @property
    def ltv(self) -> float:
        return float(self.current_loan_balance) / float(self.current_avm_value)


class PropertyImage(Base):
    __tablename__ = "property_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pid = Column(BigInteger, ForeignKey("properties.pid"), index=True, nullable=False)
    url = Column(String(512), nullable=False)
    label = Column(String(64))     # human-readable caption, e.g. "Kitchen", "Exterior Front"
    category = Column(String(32))  # structural category driving the deterministic mapping
    sort_order = Column(Integer, default=0, nullable=False)  # display order within the carousel

    prop = relationship("Property", back_populates="images")


class SystemLog(Base):
    """Unified operational + audit log, fed by loguru (backend) and loglevel (frontend).

    Doubles as the compliance audit trail (e.g. underwriter overrides) and as
    system telemetry (request latency, model inference stats, client errors).
    """
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    source = Column(String(16), index=True)     # 'backend' | 'frontend'
    level = Column(String(10), index=True)       # DEBUG / INFO / WARNING / ERROR
    logger_name = Column(String(64))              # e.g. 'api.audit', 'frontend.inspector'
    message = Column(Text, nullable=False)        # human-readable event description
    pid = Column(BigInteger, index=True, nullable=True)  # related property, if any
    context = Column(JSON)                         # structured payload (deltas, latency, etc.)
    actor = Column(String(64), index=True, nullable=True)  # authenticated username; NULL if none


class UserRole(str, enum.Enum):
    VIEWER = "Viewer"
    UNDERWRITER = "Underwriter"
    ADMIN = "Admin"


class User(Base):
    """PoC-grade user store: a handful of demo accounts (see scripts/seed_db.py),
    not a production identity system. Roles are re-checked from the DB on every
    request (see app.auth.get_current_user) rather than trusted from the session,
    so a role change takes effect on the user's very next request."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)  # bcrypt hash
    role = Column(Enum(UserRole, values_callable=lambda e: [m.value for m in e]),
                  default=UserRole.VIEWER, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RegisteredModel(Base):
    """Model risk inventory entry — one row per trained artifact under model/<id>/.

    Exactly one row should carry status=Champion at any time; that model's valuation is
    what gets booked onto BankPortfolioMeta.current_avm_value. All other non-retired rows
    are challengers: they score the full portfolio in shadow (see ModelValuation) but never
    get booked directly — promoting one to champion is a deliberate, logged, portfolio-wide act.
    """
    __tablename__ = "models"

    id = Column(String(64), primary_key=True)  # slug, e.g. "lgbm_v1", matches model/<id>/
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    architecture = Column(String(128), nullable=False)   # e.g. "LightGBM Gradient-Boosted Trees"
    description = Column(Text, default="")                 # model-card summary, plain language
    explainer = Column(String(32), nullable=False)         # "tree_shap" | "linear_coef"
    status = Column(Enum(ModelStatus, values_callable=lambda e: [m.value for m in e]),
                    default=ModelStatus.CHALLENGER, index=True)
    holdout_mape = Column(Float)
    holdout_r2 = Column(Float)
    trained_at = Column(DateTime(timezone=True))
    promoted_at = Column(DateTime(timezone=True), nullable=True)

    valuations = relationship("ModelValuation", back_populates="model",
                              cascade="all, delete-orphan")


class ScenarioType(str, enum.Enum):
    ORGANIC = "organic"                  # small seeded per-neighborhood drift ("standard cycle")
    BROAD_STRESS = "broad_stress"        # uniform shock applied across every neighborhood
    TARGETED_STRESS = "targeted_stress"  # shock isolated to one neighborhood (concentration risk)
    CUSTOM = "custom"                    # admin-specified per-neighborhood adjustments


class RevaluationRun(Base):
    """One periodic revaluation cycle: market movement since the previous cycle, injected as
    neighborhood-level index adjustments and applied to every asset's currently booked AVM
    value — the collateral-monitoring loop between full model-backed revaluations (a
    champion promotion re-anchors to raw model output; a cycle indexes on top of it). This is
    deliberately not a market/time-series simulator: it's discrete runs with an operator-set
    or auto-generated index vector per run, matching how HPI-indexed AVM updating works
    between full revaluations in practice.
    """
    __tablename__ = "revaluation_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    as_of_date = Column(DateTime(timezone=True), nullable=False)
    scenario_name = Column(String(128), nullable=False)
    scenario_type = Column(Enum(ScenarioType, values_callable=lambda e: [m.value for m in e]),
                           nullable=False)
    index_adjustments = Column(JSON, nullable=False)  # {neighborhood: pct_applied_this_run}
    notes = Column(Text, default="")
    model_id = Column(String(64), ForeignKey("models.id"), nullable=True)  # champion at run time
    created_by = Column(String(64), nullable=True)  # actor username
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    results = relationship("RevaluationResult", back_populates="run",
                           cascade="all, delete-orphan")


class RevaluationResult(Base):
    """Per-asset outcome of one revaluation run: prior vs. new booked value/LTV and whether the
    period-over-period movement itself is a triage signal (distinct from — and additive to —
    the existing AVM-vs-original-sale variance triage), so a stress cycle visibly refills the
    triage queue even for assets whose variance against the original sale price was fine."""
    __tablename__ = "revaluation_results"
    __table_args__ = (UniqueConstraint("run_id", "pid", name="uq_revaluation_result_run_pid"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("revaluation_runs.id"), index=True, nullable=False)
    pid = Column(BigInteger, ForeignKey("properties.pid"), index=True, nullable=False)
    prior_value = Column(Numeric(12, 2), nullable=False)
    new_value = Column(Numeric(12, 2), nullable=False)
    value_delta_pct = Column(Float, nullable=False)
    prior_ltv = Column(Float, nullable=False)
    new_ltv = Column(Float, nullable=False)
    ltv_delta = Column(Float, nullable=False)
    flagged = Column(Boolean, default=False, index=True)
    flag_reasons = Column(JSON)  # list[str], e.g. ["value_drop_gt_10pct", "ltv_crossed_80"]
    audit_status_after = Column(Enum(AuditStatus, values_callable=lambda e: [m.value for m in e]))

    run = relationship("RevaluationRun", back_populates="results")
    prop = relationship("Property")


class ModelValuation(Base):
    """Shadow-scoring ledger: one row per (property, model) — every registered model's
    valuation for every asset, computed at seed/registration time. This is the source of
    truth for champion/challenger comparison and the disagreement queue; it is never
    overwritten in place, only recomputed wholesale when a model is (re)registered."""
    __tablename__ = "model_valuations"
    __table_args__ = (UniqueConstraint("pid", "model_id", name="uq_model_valuation_pid_model"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    pid = Column(BigInteger, ForeignKey("properties.pid"), index=True, nullable=False)
    model_id = Column(String(64), ForeignKey("models.id"), index=True, nullable=False)
    estimated_value = Column(Numeric(12, 2), nullable=False)
    value_low = Column(Numeric(12, 2), nullable=False)
    value_high = Column(Numeric(12, 2), nullable=False)
    top_drivers = Column(JSON)
    top_detractors = Column(JSON)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    prop = relationship("Property")
    model = relationship("RegisteredModel", back_populates="valuations")
