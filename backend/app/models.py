import enum

from sqlalchemy import (JSON, BigInteger, Column, DateTime, Enum, Float,
                        ForeignKey, Integer, Numeric, String, Text)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class AuditStatus(str, enum.Enum):
    APPROVED = "Approved"
    PENDING_REVIEW = "Pending Review"
    FLAGGED_HIGH_VARIANCE = "Flagged: High Variance"


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
    image = relationship("PropertyImage", back_populates="prop", uselist=False,
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

    prop = relationship("Property", back_populates="meta")

    @property
    def ltv(self) -> float:
        return float(self.current_loan_balance) / float(self.current_avm_value)


class PropertyImage(Base):
    __tablename__ = "property_images"

    pid = Column(BigInteger, ForeignKey("properties.pid"), primary_key=True)
    url = Column(String(512), nullable=False)
    category = Column(String(32))  # structural category driving the deterministic mapping

    prop = relationship("Property", back_populates="image")


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
