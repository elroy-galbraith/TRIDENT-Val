"""Bad-parse flags on scraped listings — the Listings explorer's only write path.

Flags live in TRIDENT-Val's own app database (table `listing_flags`, created by the usual
Base.metadata.create_all at startup; works on SQLite and Postgres). Nothing here touches
BigQuery or GCS. Any logged-in non-Viewer may raise a flag; only an Admin resolves or deletes.
Every write is logged with the actor (same loguru `actor`/`context` convention as main.py).
"""
import csv
import datetime as dt
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import listings
from .auth import get_current_user, require_role
from .db import get_db
from .models import ListingFlag, User, UserRole

router = APIRouter(prefix="/api/v1/listings/flags", tags=["listing-flags"],
                   dependencies=[Depends(get_current_user)])

REASONS = ["wrong_value", "not_parsed", "wrong_unit", "wrong_currency", "wrong_category", "other"]
# Anything shown in the inspector's raw-vs-parsed table, plus the fill-rate fields.
FLAGGABLE_FIELDS = sorted({lab for lab, *_ in listings.COMPARE_FIELDS} |
                          {lab for lab, _, _ in listings.FILL_FIELDS})
CSV_COLUMNS = ["id", "status", "record_id", "site_listing_ref", "scrape_run_id", "field", "reason",
               "raw_value", "parsed_value", "expected_value", "note", "created_by", "created_at",
               "resolved_by", "resolved_at", "resolution_note"]


class FlagCreate(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)
    field: str = Field(min_length=1, max_length=64)
    reason: str
    note: str = Field("", max_length=2000)
    expected_value: Optional[str] = Field(None, max_length=256)


class FlagResolve(BaseModel):
    resolution_note: str = Field("", max_length=2000)


def _out(f: ListingFlag) -> dict:
    out = {}
    for c in CSV_COLUMNS:
        v = getattr(f, c)
        out[c] = v.isoformat() if isinstance(v, dt.datetime) else v
    return out


def _filtered(db: Session, status, field, reason, record_id, created_by):
    q = db.query(ListingFlag)
    for col, val in ((ListingFlag.status, status), (ListingFlag.field, field),
                     (ListingFlag.reason, reason), (ListingFlag.record_id, record_id),
                     (ListingFlag.created_by, created_by)):
        if val:
            q = q.filter(col == val)
    return q.order_by(ListingFlag.id.desc())


def _text(v) -> Optional[str]:
    return str(v) if listings._present(v) else None


def _snapshot(rec: dict, field: str) -> tuple[Optional[str], Optional[str]]:
    for c in listings._comparison(rec):
        if c["field"] == field:
            return _text(c["raw"]), _text(c["parsed"])
    for lab, sec, key in listings.FILL_FIELDS:
        if lab == field:
            return None, _text(listings._g(rec, sec, key))
    return None, None


@router.get("/meta")
def flag_meta():
    return {"reasons": REASONS, "fields": FLAGGABLE_FIELDS}


@router.get("/summary")
def flag_summary(db: Session = Depends(get_db)):
    """Counts for the quality overview."""
    rows = db.query(ListingFlag.status, ListingFlag.field, ListingFlag.record_id).all()
    open_rows = [r for r in rows if r[0] == "open"]
    by_field: dict[str, int] = {}
    for _, fld, _ in open_rows:
        by_field[fld] = by_field.get(fld, 0) + 1
    return {"open": len(open_rows), "resolved": len(rows) - len(open_rows), "total": len(rows),
            "open_listings": len({r[2] for r in open_rows}),
            "open_by_field": [{"field": k, "count": v}
                              for k, v in sorted(by_field.items(), key=lambda kv: -kv[1])]}


@router.get("/export.csv")
def export_flags(status: Optional[str] = "open", field: Optional[str] = None,
                 reason: Optional[str] = None, db: Session = Depends(get_db)):
    """CSV of flags (open by default; pass an empty status for all) for turning into parser fixes."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for f in _filtered(db, status, field, reason, None, None).all():
        w.writerow({k: ("" if v is None else v) for k, v in _out(f).items()})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="listing_flags.csv"'})


@router.get("")
def list_flags(status: Optional[str] = None, field: Optional[str] = None, reason: Optional[str] = None,
               record_id: Optional[str] = None, created_by: Optional[str] = None,
               limit: int = Query(500, ge=1, le=2000), db: Session = Depends(get_db)):
    q = _filtered(db, status, field, reason, record_id, created_by)
    return {"total": q.count(), "items": [_out(f) for f in q.limit(limit).all()]}


@router.post("", status_code=201)
def create_flag(body: FlagCreate, db: Session = Depends(get_db),
                user: User = Depends(require_role(UserRole.UNDERWRITER, UserRole.ADMIN))):
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {REASONS}")
    if body.field not in FLAGGABLE_FIELDS:
        raise HTTPException(422, f"Unknown field {body.field!r}")
    rec = next((r for r in listings._rows() if r["record"]["record_id"] == body.record_id), None)
    if rec is None:
        raise HTTPException(404, "Listing not found")
    raw, parsed = _snapshot(rec, body.field)
    f = ListingFlag(record_id=body.record_id, field=body.field, reason=body.reason,
                    note=body.note, expected_value=body.expected_value or None,
                    site_listing_ref=listings._g(rec, "provenance", "site_listing_ref"),
                    scrape_run_id=listings._g(rec, "provenance", "scrape_run_id"),
                    raw_value=raw, parsed_value=parsed, created_by=user.username)
    db.add(f)
    db.commit()
    db.refresh(f)
    logger.bind(actor=user.username, context={
        "flag_id": f.id, "record_id": f.record_id, "field": f.field, "reason": f.reason,
    }).info("Listing bad-parse flag #{id} raised on {rec} ({field}, {reason}).",
            id=f.id, rec=f.record_id[:12], field=f.field, reason=f.reason)
    return _out(f)


@router.patch("/{flag_id}/resolve")
def resolve_flag(flag_id: int, body: FlagResolve, db: Session = Depends(get_db),
                 user: User = Depends(require_role(UserRole.ADMIN))):
    f = db.get(ListingFlag, flag_id)
    if f is None:
        raise HTTPException(404, "Flag not found")
    if f.status == "resolved":
        raise HTTPException(409, "Flag is already resolved")
    f.status, f.resolved_by = "resolved", user.username
    f.resolved_at, f.resolution_note = dt.datetime.now(dt.timezone.utc), body.resolution_note
    db.commit()
    logger.bind(actor=user.username, context={"flag_id": f.id, "record_id": f.record_id}).info(
        "Listing flag #{id} resolved.", id=f.id)
    return _out(f)


@router.delete("/{flag_id}")
def delete_flag(flag_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_role(UserRole.ADMIN))):
    f = db.get(ListingFlag, flag_id)
    if f is None:
        raise HTTPException(404, "Flag not found")
    ctx = {"flag_id": f.id, "record_id": f.record_id, "field": f.field, "status": f.status}
    db.delete(f)
    db.commit()
    logger.bind(actor=user.username, context=ctx).info("Listing flag #{id} deleted.", id=ctx["flag_id"])
    return {"deleted": flag_id}
