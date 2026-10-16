"""Phase 2 listings endpoints (/distributions, /geo) against a generated NDJSON file
(same mini-app pattern as test_listings.py, but with enough rows to exercise outlier fences)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import listings
from app.auth import get_current_user


def rec(i, amount=1_000_000, cur="USD", ptype="House", ltype="For Sale", lat=18.0, lon=-77.0,
        area=1000, unit="sqft", beds=3, parish="St Ann", precision="unverified"):
    return {
        "record": {"record_id": f"r{i}"},
        "provenance": {"scrape_run_id": "run_A", "site_listing_ref": f"MLS-{i}",
                       "fetched_at": f"2026-10-15T00:{i % 60:02d}:00Z"},
        "listing": {"title": f"Listing {i}", "listing_type_raw": ltype},
        "price": {"amount": amount, "amount_raw": str(amount), "currency": cur},
        "location": {"latitude": lat, "longitude": lon, "geo_source": "page", "geo_precision": precision,
                     "community": f"C{i}", "parish_raw": parish},
        "attributes": {"property_type_raw": ptype, "bedrooms": beds, "floor_area": area,
                       "floor_area_unit": unit},
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    rows = [rec(i, amount=1_000_000 + i * 50_000, area=1000 + i * 10) for i in range(10)]
    rows.append(rec(100, amount=850_000_000))                          # price outlier (USD)
    rows += [rec(200 + i, amount=20_000_000 + i * 1_000_000, cur="JMD", ptype="Land",
                 area=None, unit=None, beds=None) for i in range(3)]   # JMD facet n<8: not fenced
    rows.append(rec(300, area=2, unit="acres"))                        # incomparable unit
    # geo: swapped, far outside, and a 3-way shared centroid
    rows.append(rec(400, lat=-77.0, lon=18.0))
    rows.append(rec(401, lat=40.7, lon=-74.0))
    rows += [rec(410 + i, lat=18.1234, lon=-77.5, ptype="Resort", precision="parish_centroid") for i in range(3)]
    p = tmp_path / "x.ndjson"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", str(p))
    listings.clear_cache()
    app = FastAPI()
    app.include_router(listings.router)
    app.dependency_overrides[get_current_user] = lambda: object()
    yield TestClient(app)
    listings.clear_cache()


def test_distributions_facets_never_mix_currency(client):
    d = client.get("/api/v1/listings/distributions").json()
    price = {f["facet"]: f for f in d["facets"] if f["metric"] == "price"}
    assert set(price) == {"USD", "JMD"}
    assert price["JMD"]["n"] == 3 and price["JMD"]["fences"] is None
    assert sum(b["count"] for b in price["USD"]["bins"]) == price["USD"]["n"]
    assert price["USD"]["max"] == 850_000_000
    ppu = {f["facet"] for f in d["facets"] if f["metric"] == "price_per_area"}
    assert ppu == {"USD / sqft"}                      # acres row excluded, JMD land has no area
    assert d["price_per_area_skipped_incomparable_unit"] == 1


def test_price_outlier_flagged_with_record_id(client):
    d = client.get("/api/v1/listings/distributions").json()
    hits = [o for o in d["outliers"] if o["metric"] == "price"]
    assert [o["record_id"] for o in hits] == ["r100"]
    assert hits[0]["side"] == "high" and hits[0]["severity"] == "extreme"
    assert d["outliers"][0]["severity"] == "extreme"  # extremes sort first


def test_mix_and_bedrooms(client):
    d = client.get("/api/v1/listings/distributions").json()
    mix = {(m["property_type"], m["listing_type"]): m["count"] for m in d["property_by_listing_type"]}
    assert mix[("Land", "For Sale")] == 3 and mix[("Resort", "For Sale")] == 3
    assert {t["property_type"]: t["count"] for t in d["property_type_totals"]}["House"] == 14
    assert d["bedrooms_missing"] == 3
    assert {b["bedrooms"]: b["count"] for b in d["bedrooms"]} == {3: d["total"] - 3}


def test_distributions_respect_filters(client):
    d = client.get("/api/v1/listings/distributions", params={"property_type": "Land"}).json()
    assert d["total"] == 3
    assert {f["facet"] for f in d["facets"] if f["metric"] == "price"} == {"JMD"}
    assert client.get("/api/v1/listings/distributions", params={"missing_field": "nope"}).status_code == 422


def test_geo_problems_and_clusters(client):
    g = client.get("/api/v1/listings/geo").json()
    prob = {p["record_id"]: p["problem"] for p in g["outside_bbox"]}
    assert prob == {"r400": "lat_lon_swapped", "r401": "outside_jamaica"}
    cl = next(c for c in g["clusters"] if c["latitude"] == 18.1234)
    assert cl["count"] == 3 and cl["latitude"] == 18.1234 and cl["geo_precision"] == {"parish_centroid": 3}
    assert cl["record_ids"] == ["r410", "r411", "r412"]
    assert g["clusters"][0]["count"] == 15   # the (18.0, -77.0) default is the biggest shared point
    assert g["with_coordinates"] == g["total"]
    one = next(p for p in g["points"] if p["record_id"] == "r410")
    assert one["shared_count"] == 3


def test_geo_filters_and_min_cluster(client):
    g = client.get("/api/v1/listings/geo", params={"property_type": "Resort"}).json()
    assert g["total"] == 3 and len(g["clusters"]) == 1
    assert client.get("/api/v1/listings/geo", params={"property_type": "Resort", "min_cluster": 4}
                      ).json()["clusters"] == []


def test_grid_still_filters_via_shared_dependency(client):
    r = client.get("/api/v1/listings", params={"search": "listing 100"}).json()
    assert r["total"] == 1 and r["items"][0]["record_id"] == "r100"


def test_latest_only_dedupes_repeat_observations(client, tmp_path, monkeypatch):
    # the same listing (MLS-9) observed 4 times at one point is NOT a shared-centroid cluster
    rows = [rec(500 + i, amount=250_000_000, lat=18.2, lon=-78.2) for i in range(4)]
    for i, r in enumerate(rows):
        r["provenance"]["site_listing_ref"] = "MLS-9"
        r["provenance"]["fetched_at"] = f"2026-10-1{i}T00:00:00Z"
    p = tmp_path / "dup.ndjson"
    p.write_text(chr(10).join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", str(p))
    listings.clear_cache()
    g = client.get("/api/v1/listings/geo").json()
    assert g["total"] == 4 and g["clusters"] == []
    g = client.get("/api/v1/listings/geo", params={"latest_only": True}).json()
    assert g["total"] == 1 and g["duplicates_excluded"] == 3
    assert g["points"][0]["record_id"] == "r503"          # latest fetched_at wins
    d = client.get("/api/v1/listings/distributions", params={"latest_only": True}).json()
    assert d["total"] == 1 and d["duplicates_excluded"] == 3
