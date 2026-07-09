import enum

from sqlalchemy import (JSON, BigInteger, Column, Enum, Float, ForeignKey,
                        Integer, Numeric, String, Text)
from sqlalchemy.orm import relationship

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
