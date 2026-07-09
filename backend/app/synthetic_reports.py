"""Synthetic valuation-report PDF generation for the Docling extraction-accuracy demo (see
README's Document Intake section, and app.extraction). Reuses the same Jinja2 + WeasyPrint
plumbing as app.reports, but for a genuinely different purpose: instead of rendering the
underwriter's own decision record, this renders a synthetic surveyor/appraisal-style document
*from* an Ames property record, so the ground truth is known and extraction accuracy is
measurable — see SyntheticDocument.ground_truth.

Every generated document carries an unmissable in-PDF banner stating it is synthetic,
generated from a public dataset, and not a real appraisal, survey, or valuation — see
templates/synthetic_valuation_report.html. Nothing here is passed off as authentic; the whole
point of the exercise is to measure extraction accuracy against a known answer key, not to
produce something that looks like a real document from a real institution.
"""
import logging as stdlib_logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from weasyprint import HTML

from .models import Property, SyntheticReportStyle

stdlib_logging.getLogger("weasyprint").setLevel(stdlib_logging.ERROR)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic_reports"
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True, lstrip_blocks=True,
)

SURVEYORS = ["A. Reid", "K. Brown", "T. Facey", "M. Grant", "P. Anderson"]

# Ground-truth fields the extraction pipeline is scored against (app.extraction) — every one
# of these appears verbatim in the rendered document, so a perfect extractor should recover
# every field on a clean, undegraded document.
GROUND_TRUTH_FIELDS = [
    "pid", "neighborhood", "bldg_type", "house_style", "year_built", "ms_zoning",
    "overall_qual", "overall_cond", "gr_liv_area", "total_bsmt_sf",
    "full_bath", "half_bath", "bedroom_abvgr", "sale_price",
]


def ground_truth_for(prop: Property) -> dict:
    out = {}
    for f in GROUND_TRUTH_FIELDS:
        v = getattr(prop, f)
        out[f] = float(v) if isinstance(v, Decimal) else v
    return out


def synthetic_report_context(prop: Property, style: SyntheticReportStyle) -> dict:
    rng = random.Random(f"synthetic-report:{prop.pid}")  # deterministic per-property flavor text
    inspection_date = (datetime(2026, 1, 1) + timedelta(days=rng.randint(0, 180))).strftime("%Y-%m-%d")
    ctx = ground_truth_for(prop)
    ctx.update({
        "style": style.value,
        "surveyor_name": SURVEYORS[rng.randint(0, len(SURVEYORS) - 1)],
        "inspection_date": inspection_date,
        "notes": "" if style == SyntheticReportStyle.MODERN else
                 "Standard drive-by review conducted for this synthetic record; no material findings.",
        "generated_at": datetime.now(timezone.utc),
    })
    return ctx


def render_synthetic_report_pdf(db: Session, pid: int,
                               style: SyntheticReportStyle = SyntheticReportStyle.LEGACY_URAR
                               ) -> Optional[tuple[bytes, dict]]:
    """Returns (pdf_bytes, ground_truth) or None if the pid isn't on file."""
    prop = db.query(Property).filter(Property.pid == pid).one_or_none()
    if not prop:
        return None
    ctx = synthetic_report_context(prop, style)
    html = _env.get_template("synthetic_valuation_report.html").render(**ctx)
    pdf_bytes = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf()
    return pdf_bytes, ground_truth_for(prop)
