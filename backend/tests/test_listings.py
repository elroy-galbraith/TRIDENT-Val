"""Listings router tests, run against the NDJSON fallback with a 3-row fixture
(no BigQuery, no database): a mini app mounts only the listings router and overrides auth."""
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import listings
from app.auth import get_current_user

FIXTURE = Path(__file__).parent / "fixtures" / "listings_sample.ndjson"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", str(FIXTURE))
    listings.clear_cache()
    app = FastAPI()
    app.include_router(listings.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    yield TestClient(app)
    listings.clear_cache()


def test_requires_auth(monkeypatch):
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", str(FIXTURE))
    app = FastAPI()
    app.include_router(listings.router)

    def deny():
        raise HTTPException(401, "Not authenticated")
    app.dependency_overrides[get_current_user] = deny
    assert TestClient(app).get("/api/v1/listings/summary").status_code == 401


def test_summary(client):
    s = client.get("/api/v1/listings/summary").json()
    assert s["total"] == 3
    assert "cbjamaica" in s["coverage_note"]
    fill = {f["field"]: f for f in s["fill_rates"]}
    assert fill["price.amount"]["count"] == 2
    assert fill["attributes.bedrooms"]["count"] == 1
    assert fill["images (≥1)"]["count"] == 2
    assert {c["value"]: c["count"] for c in s["amount_parse_status"]} == {"ok": 2, "failed": 1}
    assert {c["value"]: c["count"] for c in s["currency"]} == {"USD": 2, "JMD": 1}
    runs = {r["scrape_run_id"]: r["count"] for r in s["rows_per_run"]}
    assert runs == {"run_A": 2, "run_B": 1}
    assert [d["fetched_date"] for d in s["rows_per_fetch_date"]] == ["2026-10-13", "2026-10-15"]
    # row 3: bedrooms_raw present, bedrooms parsed missing
    gaps = {g["pair"]: g["raw_present_parsed_missing"] for g in s["parse_gaps"]}
    assert gaps["bedrooms_raw → bedrooms"] == 1
    assert gaps["price.amount_raw → amount"] == 1
    cell = [m for m in s["property_by_listing_type"] if m["property_type"] == "Land"]
    assert cell == [{"property_type": "Land", "listing_type": "For Sale", "count": 1}]
    assert s["quality_flags"]["with_parse_errors"] == 1


def test_list_pagination_sort_and_filters(client):
    r = client.get("/api/v1/listings", params={"page_size": 2}).json()
    assert r["total"] == 3 and len(r["items"]) == 2
    assert r["items"][0]["amount"] == 250000000          # price_desc by default
    assert client.get("/api/v1/listings", params={"page": 2, "page_size": 2}).json()["items"][0]["amount"] is None
    ids = lambda **p: [i["site_listing_ref"] for i in client.get("/api/v1/listings", params=p).json()["items"]]  # noqa: E731
    assert ids(currency="JMD") == ["MLS-2"]
    assert ids(property_type="House", sort="price_asc") == ["MLS-1", "MLS-3"]
    assert ids(search="beach") == ["MLS-3"]
    assert ids(min_price=500000, max_price=2000000) == ["MLS-1"]
    assert ids(missing_field="attributes.bedrooms", sort="price_desc") == ["MLS-2", "MLS-3"]
    assert ids(amount_parse_status="failed") == ["MLS-3"]
    assert ids(scrape_run_id="run_B") == ["MLS-2"]
    assert client.get("/api/v1/listings", params={"sort": "nope"}).status_code == 422
    assert client.get("/api/v1/listings", params={"missing_field": "nope"}).status_code == 422


def test_filters_options(client):
    f = client.get("/api/v1/listings/filters").json()
    assert f["currency"] == ["JMD", "USD"]
    assert f["scrape_run_id"] == ["run_A", "run_B"]


def test_detail_parsed_vs_raw(client):
    d = client.get("/api/v1/listings/rec3").json()
    cmp_ = {c["field"]: c for c in d["comparison"]}
    assert cmp_["Bedrooms"]["raw"] == "3" and cmp_["Bedrooms"]["parsed"] is None
    assert cmp_["Bedrooms"]["status"] == "unparsed"
    assert cmp_["Price"]["status"] == "unparsed"
    assert cmp_["Bathrooms"]["status"] == "parsed"
    assert cmp_["Year built"]["status"] == "missing"
    assert d["provenance"]["parser_version"] == "0.1.0"
    assert d["provenance"]["http_status"] == 200
    assert [i["order_index"] for i in d["images"]] == [0, 1]
    assert d["quality"]["parse_errors"] == ["bedrooms"]
    assert d["record"]["price"]["amount_raw"] == "USD $ 1,000,000"


def test_detail_404(client):
    assert client.get("/api/v1/listings/nope").status_code == 404


def test_read_only(client):
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/listings/rec1").status_code == 405


def test_missing_source_is_503(monkeypatch):
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", "/does/not/exist.ndjson")
    listings.clear_cache()
    app = FastAPI()
    app.include_router(listings.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    assert TestClient(app).get("/api/v1/listings/summary").status_code == 503
    listings.clear_cache()
