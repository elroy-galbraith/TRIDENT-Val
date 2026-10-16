"""Read-only explorer over scraped property listings (cbjamaica crawl) for data validation.

Source of truth is the BigQuery table written by the listings scraper
(`ats-avm-jam.listings_raw.listing_observation_raw`, one row per listing observation).
For offline / SQLite-mode runs the same records can be read from local NDJSON
(`LISTINGS_NDJSON_PATH`, a file or a directory of *.ndjson files — e.g. the batches under
gs://ats-avm-jam-listings-raw/batches/cbjamaica/).

The whole table is a few hundred rows, so it is loaded once into memory (TTL cache) and every
endpoint is computed in Python. That keeps one code path for both sources and makes the
router trivially testable with a fixture file. Nothing here writes anywhere: the only BigQuery
call is a plain SELECT, and there are no POST/PATCH/DELETE routes.

Config (env):
  LISTINGS_NDJSON_PATH   if set, read local NDJSON instead of BigQuery
  LISTINGS_BQ_PROJECT    billing/job project (default ats-avm-jam — NOT the gcloud default)
  LISTINGS_BQ_TABLE      fully-qualified table (default ats-avm-jam.listings_raw.listing_observation_raw)
  LISTINGS_CACHE_TTL     seconds to keep loaded rows (default 300)
"""
import datetime as dt
import decimal
import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from .auth import get_current_user

router = APIRouter(prefix="/api/v1/listings", tags=["listings"],
                   dependencies=[Depends(get_current_user)])

DEFAULT_BQ_PROJECT = "ats-avm-jam"
DEFAULT_BQ_TABLE = "ats-avm-jam.listings_raw.listing_observation_raw"
_TABLE_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")

# Shown on every listings view; also returned by the API so the contract lives in one place.
COVERAGE_NOTE = (
    "Single-site crawl (cbjamaica.com) of the top of the market only: listings were collected "
    "price-descending and the site stops serving pages past ~50, so this is ~540 of ~7,600 "
    "listings. Prices are asking prices, not sale prices. Do not read these distributions as "
    "the whole Jamaican market."
)


# ---------- loading ----------

def _jsonable(v: Any) -> Any:
    """Normalise BigQuery client values into plain JSON types (matches NDJSON shape)."""
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, bytes):
        return v.hex()
    return v


def _load_ndjson(path: str) -> list[dict]:
    p = Path(path)
    files = sorted(p.glob("*.ndjson")) if p.is_dir() else [p]
    if not files or not all(f.exists() for f in files):
        raise FileNotFoundError(f"No NDJSON found at {path}")
    seen: dict[str, dict] = {}
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                seen[rec["record"]["record_id"]] = rec
    return list(seen.values())


def _load_bigquery() -> list[dict]:
    from google.cloud import bigquery  # imported lazily: offline mode must not need it

    table = os.environ.get("LISTINGS_BQ_TABLE", DEFAULT_BQ_TABLE)
    if not _TABLE_RE.match(table):
        raise ValueError(f"Invalid LISTINGS_BQ_TABLE: {table!r}")
    project = os.environ.get("LISTINGS_BQ_PROJECT", DEFAULT_BQ_PROJECT)
    client = bigquery.Client(project=project)
    rows = client.query(f"SELECT * FROM `{table}`").result()
    return [_jsonable(dict(r.items())) for r in rows]


_cache: dict = {"rows": None, "at": 0.0, "source": None}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.update(rows=None, at=0.0, source=None)


def _rows() -> list[dict]:
    ttl = float(os.environ.get("LISTINGS_CACHE_TTL", "300"))
    with _lock:
        if _cache["rows"] is not None and time.time() - _cache["at"] < ttl:
            return _cache["rows"]
        path = os.environ.get("LISTINGS_NDJSON_PATH")
        try:
            rows = _load_ndjson(path) if path else _load_bigquery()
        except Exception as e:  # surfaced to the UI as a 503 with the reason
            logger.error("Listings load failed: {e}", e=e)
            raise HTTPException(503, f"Listings source unavailable: {e}")
        _cache.update(rows=rows, at=time.time(),
                      source=f"ndjson:{path}" if path else "bigquery")
        logger.info("Loaded {n} listings from {s}", n=len(rows), s=_cache["source"])
        return rows


# ---------- helpers ----------

def _g(rec: dict, section: str, key: str) -> Any:
    return (rec.get(section) or {}).get(key)


def _present(v: Any) -> bool:
    return v is not None and v != "" and v != []


def _label(v: Any) -> str:
    return "(missing)" if not _present(v) else str(v)


def _counts(rows: list[dict], getter) -> list[dict]:
    c = Counter(_label(getter(r)) for r in rows)
    return [{"value": k, "count": n} for k, n in c.most_common()]


def _date_of(ts: Any) -> Optional[str]:
    return str(ts)[:10] if ts else None


# (label, section, key) — fill rate is reported for each
FILL_FIELDS = [
    ("price.amount", "price", "amount"),
    ("price.currency", "price", "currency"),
    ("listing.title", "listing", "title"),
    ("listing.description", "listing", "description"),
    ("listing.listing_type_raw", "listing", "listing_type_raw"),
    ("listing.listing_status_raw", "listing", "listing_status_raw"),
    ("listing.listed_at", "listing", "listed_at"),
    ("location.community", "location", "community"),
    ("location.parish_raw", "location", "parish_raw"),
    ("location.latitude", "location", "latitude"),
    ("location.longitude", "location", "longitude"),
    ("attributes.property_type_raw", "attributes", "property_type_raw"),
    ("attributes.bedrooms", "attributes", "bedrooms"),
    ("attributes.bathrooms", "attributes", "bathrooms"),
    ("attributes.floor_area", "attributes", "floor_area"),
    ("attributes.lot_size", "attributes", "lot_size"),
    ("attributes.year_built_raw", "attributes", "year_built_raw"),
    ("attributes.condition_raw", "attributes", "condition_raw"),
    ("attributes.features_raw", "attributes", "features_raw"),
    ("identifiers.mls_id_raw", "identifiers", "mls_id_raw"),
    ("agent.agency_name_raw", "agent", "agency_name_raw"),
    ("agent.agent_name_raw", "agent", "agent_name_raw"),
]

# raw string / parsed value pairs shown side by side. parsed=None means "no parsed field exists".
COMPARE_FIELDS = [
    ("Price", ("price", "amount_raw"), ("price", "amount"), ("price", "currency")),
    ("Currency", ("price", "currency_raw"), ("price", "currency"), ("price", "currency_source")),
    ("Price qualifier", ("price", "price_qualifier_raw"), None, None),
    ("Property type", ("attributes", "property_type_raw"), None, None),
    ("Bedrooms", ("attributes", "bedrooms_raw"), ("attributes", "bedrooms"), None),
    ("Bathrooms", ("attributes", "bathrooms_raw"), ("attributes", "bathrooms"), None),
    ("Floor area", ("attributes", "floor_area_raw"), ("attributes", "floor_area"),
     ("attributes", "floor_area_unit")),
    ("Lot size", ("attributes", "lot_size_raw"), ("attributes", "lot_size"),
     ("attributes", "lot_size_unit")),
    ("Year built", ("attributes", "year_built_raw"), None, None),
    ("Condition", ("attributes", "condition_raw"), None, None),
    ("Parish", ("location", "parish_raw"), None, None),
    ("Address", ("location", "address_raw"), ("location", "community"), None),
]

# raw present but parsed missing = parser gap worth looking at
PARSE_GAP_PAIRS = [
    ("price.amount_raw → amount", ("price", "amount_raw"), ("price", "amount")),
    ("price.currency_raw → currency", ("price", "currency_raw"), ("price", "currency")),
    ("bedrooms_raw → bedrooms", ("attributes", "bedrooms_raw"), ("attributes", "bedrooms")),
    ("bathrooms_raw → bathrooms", ("attributes", "bathrooms_raw"), ("attributes", "bathrooms")),
    ("floor_area_raw → floor_area", ("attributes", "floor_area_raw"), ("attributes", "floor_area")),
    ("lot_size_raw → lot_size", ("attributes", "lot_size_raw"), ("attributes", "lot_size")),
]


def _percentile(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def _summarize(rows: list[dict]) -> dict:
    n = len(rows)

    def fill(sec, key):
        k = sum(1 for r in rows if _present(_g(r, sec, key)))
        return {"count": k, "rate": round(k / n, 4) if n else 0.0}

    fill_rates = [{"field": lab, **fill(s, k)} for lab, s, k in FILL_FIELDS]
    k = sum(1 for r in rows if r.get("images"))
    fill_rates.append({"field": "images (≥1)", "count": k, "rate": round(k / n, 4) if n else 0.0})

    gaps = []
    for lab, (rs, rk), (ps, pk) in PARSE_GAP_PAIRS:
        g = sum(1 for r in rows if _present(_g(r, rs, rk)) and not _present(_g(r, ps, pk)))
        gaps.append({"pair": lab, "raw_present_parsed_missing": g})

    matrix: dict[tuple, int] = defaultdict(int)
    for r in rows:
        matrix[(_label(_g(r, "attributes", "property_type_raw")),
                _label(_g(r, "listing", "listing_type_raw")))] += 1
    matrix_rows = [{"property_type": a, "listing_type": b, "count": c}
                   for (a, b), c in sorted(matrix.items(), key=lambda kv: -kv[1])]

    runs: dict[str, dict] = {}
    for r in rows:
        rid = _label(_g(r, "provenance", "scrape_run_id"))
        f = _g(r, "provenance", "fetched_at")
        e = runs.setdefault(rid, {"scrape_run_id": rid, "count": 0, "first_fetched_at": f, "last_fetched_at": f})
        e["count"] += 1
        if f:
            if not e["first_fetched_at"] or str(f) < str(e["first_fetched_at"]):
                e["first_fetched_at"] = f
            if not e["last_fetched_at"] or str(f) > str(e["last_fetched_at"]):
                e["last_fetched_at"] = f
    dates = Counter(_label(r.get("fetched_date") or _date_of(_g(r, "provenance", "fetched_at")))
                    for r in rows)

    by_cur: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        a = _g(r, "price", "amount")
        if isinstance(a, (int, float)):
            by_cur[_label(_g(r, "price", "currency"))].append(float(a))
    price_by_currency = []
    for cur, vals in sorted(by_cur.items()):
        vals.sort()
        price_by_currency.append({"currency": cur, "count": len(vals), "min": vals[0],
                                  "p50": _percentile(vals, 0.5), "max": vals[-1]})

    q = lambda sec, key: sum(1 for r in rows if _present(_g(r, sec, key)))  # noqa: E731
    return {
        "total": n,
        "coverage_note": COVERAGE_NOTE,
        "source": _cache["source"],
        "fill_rates": fill_rates,
        "parse_gaps": gaps,
        "amount_parse_status": _counts(rows, lambda r: _g(r, "price", "amount_parse_status")),
        "currency": _counts(rows, lambda r: _g(r, "price", "currency")),
        "currency_source": _counts(rows, lambda r: _g(r, "price", "currency_source")),
        "geo_source": _counts(rows, lambda r: _g(r, "location", "geo_source")),
        "geo_precision": _counts(rows, lambda r: _g(r, "location", "geo_precision")),
        "parish": _counts(rows, lambda r: _g(r, "location", "parish_raw")),
        "property_type": _counts(rows, lambda r: _g(r, "attributes", "property_type_raw")),
        "listing_type": _counts(rows, lambda r: _g(r, "listing", "listing_type_raw")),
        "property_by_listing_type": matrix_rows,
        "http_status": _counts(rows, lambda r: _g(r, "provenance", "http_status")),
        "parser_version": _counts(rows, lambda r: _g(r, "provenance", "parser_version")),
        "robots_allowed": _counts(rows, lambda r: _g(r, "provenance", "robots_allowed")
                                  if _g(r, "provenance", "robots_allowed") is not None else "(missing)"),
        "rows_per_run": sorted(runs.values(), key=lambda e: str(e["first_fetched_at"])),
        "rows_per_fetch_date": [{"fetched_date": d, "count": c} for d, c in sorted(dates.items())],
        "price_by_currency": price_by_currency,
        "quality_flags": {
            "with_parse_errors": sum(1 for r in rows if (r.get("quality") or {}).get("parse_errors")),
            "with_missing_required": sum(1 for r in rows if (r.get("quality") or {}).get("missing_required")),
            "marked_duplicate": q("quality", "duplicate_of"),
        },
    }


def _list_item(r: dict) -> dict:
    imgs = r.get("images") or []
    primary = next((i for i in imgs if i.get("is_primary")), imgs[0] if imgs else None)
    return {
        "record_id": r["record"]["record_id"],
        "site_listing_ref": _g(r, "provenance", "site_listing_ref"),
        "title": _g(r, "listing", "title"),
        "listing_type_raw": _g(r, "listing", "listing_type_raw"),
        "property_type_raw": _g(r, "attributes", "property_type_raw"),
        "amount": _g(r, "price", "amount"),
        "amount_raw": _g(r, "price", "amount_raw"),
        "currency": _g(r, "price", "currency"),
        "amount_parse_status": _g(r, "price", "amount_parse_status"),
        "community": _g(r, "location", "community"),
        "parish_raw": _g(r, "location", "parish_raw"),
        "latitude": _g(r, "location", "latitude"),
        "longitude": _g(r, "location", "longitude"),
        "geo_precision": _g(r, "location", "geo_precision"),
        "bedrooms": _g(r, "attributes", "bedrooms"),
        "bathrooms": _g(r, "attributes", "bathrooms"),
        "floor_area": _g(r, "attributes", "floor_area"),
        "floor_area_unit": _g(r, "attributes", "floor_area_unit"),
        "lot_size": _g(r, "attributes", "lot_size"),
        "image_count": len(imgs),
        "primary_image_url": primary.get("source_url") if primary else None,
        "scrape_run_id": _g(r, "provenance", "scrape_run_id"),
        "fetched_at": _g(r, "provenance", "fetched_at"),
        "has_parse_errors": bool((r.get("quality") or {}).get("parse_errors")),
    }


def _comparison(r: dict) -> list[dict]:
    out = []
    for label, (rs, rk), parsed, extra in COMPARE_FIELDS:
        raw = _g(r, rs, rk)
        val = _g(r, *parsed) if parsed else None
        ex = _g(r, *extra) if extra else None
        if parsed is None:
            status = "raw_only" if _present(raw) else "missing"
        elif _present(raw) and _present(val):
            status = "parsed"
        elif _present(raw):
            status = "unparsed"        # parser gap
        elif _present(val):
            status = "derived"         # parsed value with no raw source text
        else:
            status = "missing"
        out.append({"field": label, "raw": raw, "parsed": val, "extra": ex, "status": status})
    return out


SORTS = {
    "price_desc": (lambda i: i["amount"], True),
    "price_asc": (lambda i: i["amount"], False),
    "area_desc": (lambda i: i["floor_area"], True),
    "fetched_desc": (lambda i: i["fetched_at"], True),
}


# ---------- endpoints ----------

@router.get("/summary")
def listings_summary():
    """Data-quality overview: fill rates, parse status, category counts, per-run / per-date rows."""
    return _summarize(_rows())


@router.get("/filters")
def listings_filters():
    rows = _rows()

    def opts(getter):
        return sorted({str(v) for r in rows if _present(v := getter(r))})

    return {
        "coverage_note": COVERAGE_NOTE,
        "parish": opts(lambda r: _g(r, "location", "parish_raw")),
        "property_type": opts(lambda r: _g(r, "attributes", "property_type_raw")),
        "listing_type": opts(lambda r: _g(r, "listing", "listing_type_raw")),
        "currency": opts(lambda r: _g(r, "price", "currency")),
        "amount_parse_status": opts(lambda r: _g(r, "price", "amount_parse_status")),
        "geo_precision": opts(lambda r: _g(r, "location", "geo_precision")),
        "scrape_run_id": opts(lambda r: _g(r, "provenance", "scrape_run_id")),
        "missing_field": [f for f, _, _ in FILL_FIELDS],
        "sort": list(SORTS),
    }


@router.get("")
def list_listings(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=200),
    search: Optional[str] = None,
    parish: Optional[str] = None,
    property_type: Optional[str] = None,
    listing_type: Optional[str] = None,
    currency: Optional[str] = None,
    amount_parse_status: Optional[str] = None,
    geo_precision: Optional[str] = None,
    scrape_run_id: Optional[str] = None,
    missing_field: Optional[str] = Query(None, description="Only rows where this field (e.g. attributes.bedrooms) is empty"),
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort: str = "price_desc",
):
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {list(SORTS)}")
    missing = None
    if missing_field:
        missing = next(((s, k) for f, s, k in FILL_FIELDS if f == missing_field), None)
        if missing is None:
            raise HTTPException(422, f"Unknown missing_field {missing_field!r}")

    def eq(r, sec, key, want):
        return want is None or str(_g(r, sec, key)) == want

    needle = search.lower() if search else None
    items = []
    for r in _rows():
        if not (eq(r, "location", "parish_raw", parish)
                and eq(r, "attributes", "property_type_raw", property_type)
                and eq(r, "listing", "listing_type_raw", listing_type)
                and eq(r, "price", "currency", currency)
                and eq(r, "price", "amount_parse_status", amount_parse_status)
                and eq(r, "location", "geo_precision", geo_precision)
                and eq(r, "provenance", "scrape_run_id", scrape_run_id)):
            continue
        if missing and _present(_g(r, *missing)):
            continue
        amt = _g(r, "price", "amount")
        if min_price is not None and (amt is None or amt < min_price):
            continue
        if max_price is not None and (amt is None or amt > max_price):
            continue
        item = _list_item(r)
        if needle and needle not in " ".join(str(item[k] or "") for k in
                                             ("title", "community", "site_listing_ref", "record_id")).lower():
            continue
        items.append(item)

    key, desc = SORTS[sort]
    have = [i for i in items if key(i) is not None]
    lack = [i for i in items if key(i) is None]
    have.sort(key=key, reverse=desc)
    items = have + lack  # rows lacking the sort key always go last
    total = len(items)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size,
            "coverage_note": COVERAGE_NOTE, "items": items[start:start + page_size]}


@router.get("/{record_id}")
def get_listing(record_id: str):
    for r in _rows():
        if r["record"]["record_id"] == record_id:
            imgs = sorted(r.get("images") or [], key=lambda i: i.get("order_index") or 0)
            return {
                "coverage_note": COVERAGE_NOTE,
                "record": r,
                "summary": _list_item(r),
                "comparison": _comparison(r),
                "provenance": r.get("provenance") or {},
                "images": imgs,
                "quality": r.get("quality") or {},
            }
    raise HTTPException(404, "Listing not found")
