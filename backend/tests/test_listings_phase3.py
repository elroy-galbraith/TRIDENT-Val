"""Phase 3: scrape-run comparison and bad-parse flags.

Mini app mounting only the listings + flags routers against a generated two-run NDJSON file and an
in-memory SQLite DB; get_current_user is overridden so roles can be switched per test."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import listing_flags, listings
from app.auth import get_current_user
from app.db import Base, get_db
from app.models import UserRole


def rec(rid, ref, run, fetched, amount=1_000_000, status="Active", beds=3, area=1000, parser="0.1.0"):
    return {
        "record": {"record_id": rid},
        "provenance": {"scrape_run_id": run, "site_listing_ref": ref, "canonical_url": f"https://x/{ref}",
                       "fetched_at": fetched, "parser_version": parser},
        "listing": {"title": f"T {ref}", "listing_status_raw": status, "listing_type_raw": "For Sale"},
        "price": {"amount": amount, "amount_raw": f"USD {amount}", "currency": "USD"},
        "attributes": {"bedrooms": beds, "bedrooms_raw": str(beds) if beds is not None else "3",
                       "floor_area": area, "floor_area_raw": f"{area} sq ft", "floor_area_unit": "sqft"},
        "location": {"parish_raw": "St Ann"},
    }


ROWS_TWO_RUNS = [
    # run A
    rec("a1", "M1", "run_A", "2026-10-13T10:00:00Z"),
    rec("a2", "M2", "run_A", "2026-10-13T10:01:00Z"),
    rec("a3", "M3", "run_A", "2026-10-13T10:02:00Z", amount=500_000),
    rec("a4", "M4", "run_A", "2026-10-13T10:03:00Z"),
    # run B: M1 unchanged, M2 price+status change, M3 bedrooms parsed → None (parser regression), M5 new
    rec("b1", "M1", "run_B", "2026-10-15T10:00:00Z"),
    rec("b2", "M2", "run_B", "2026-10-15T10:01:00Z", amount=900_000, status="Under Offer"),
    rec("b3", "M3", "run_B", "2026-10-15T10:02:00Z", amount=500_000, beds=None, parser="0.2.0"),
    rec("b5", "M5", "run_B", "2026-10-15T10:04:00Z"),
]


def write(tmp_path, monkeypatch, rows):
    p = tmp_path / "x.ndjson"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setenv("LISTINGS_NDJSON_PATH", str(p))
    listings.clear_cache()


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    state = {"user": SimpleNamespace(username="alice", role=UserRole.UNDERWRITER)}

    def build(rows):
        write(tmp_path, monkeypatch, rows)
        app = FastAPI()
        app.include_router(listing_flags.router)
        app.include_router(listings.router)

        def db():
            s = Session()
            try:
                yield s
            finally:
                s.close()
        app.dependency_overrides[get_db] = db
        app.dependency_overrides[get_current_user] = lambda: state["user"]
        return TestClient(app)

    def as_role(role, name):
        state["user"] = SimpleNamespace(username=name, role=role)

    yield build, as_role
    listings.clear_cache()


# ---------- run comparison ----------

def test_run_overview_two_runs(make_client):
    build, _ = make_client
    o = build(ROWS_TWO_RUNS).get("/api/v1/listings/runs").json()
    assert [r["scrape_run_id"] for r in o["runs"]] == ["run_A", "run_B"]
    assert o["distinct_listings"] == 5 and o["observations"] == 8
    assert o["listings_in_multiple_runs"] == 3 and o["comparable"] is True
    assert o["best_pair"] == {"run_a": "run_A", "run_b": "run_B", "shared": 3}
    assert {h["runs"]: h["listings"] for h in o["listings_by_run_count"]} == {1: 2, 2: 3}


def test_run_diff(make_client):
    build, _ = make_client
    d = build(ROWS_TWO_RUNS).get("/api/v1/listings/runs/diff", params={"run_a": "run_A", "run_b": "run_B"}).json()
    assert d["counts"]["only_a"] == 1 and d["only_a"][0]["site_listing_ref"] == "M4"
    assert d["counts"]["only_b"] == 1 and d["only_b"][0]["site_listing_ref"] == "M5"
    assert d["counts"]["both"] == 3 and d["counts"]["both_unchanged"] == 1 and d["counts"]["both_changed"] == 2
    ch = {c["key"]: c for c in d["changed"]}
    assert {(c["field"], c["before"], c["after"]) for c in ch["M2"]["changes"]} == {
        ("Price", 1_000_000, 900_000), ("Status", "Active", "Under Offer")}
    assert [c["field"] for c in ch["M3"]["changes"]] == ["Bedrooms"]
    assert ch["M3"]["parser_version_changed"] is True and ch["M2"]["parser_version_changed"] is False
    assert d["counts"]["parser_version_differs"] == 1
    assert {f["field"]: f["count"] for f in d["field_change_counts"]} == {"Price": 1, "Status": 1, "Bedrooms": 1}


def test_run_diff_direction_is_symmetric(make_client):
    build, _ = make_client
    d = build(ROWS_TWO_RUNS).get("/api/v1/listings/runs/diff", params={"run_a": "run_B", "run_b": "run_A"}).json()
    assert d["only_a"][0]["site_listing_ref"] == "M5" and d["only_b"][0]["site_listing_ref"] == "M4"
    price = next(c for c in d["changed"] if c["key"] == "M2")["changes"][0]
    assert (price["before"], price["after"]) == (900_000, 1_000_000)


def test_run_diff_keeps_latest_within_run_and_falls_back_to_canonical_url():
    rows = [rec("a1", "M1", "A", "2026-10-13T10:00:00Z", amount=1),
            rec("a1b", "M1", "A", "2026-10-13T11:00:00Z", amount=2),   # re-fetched inside the same run
            rec("b1", "M1", "B", "2026-10-15T10:00:00Z", amount=2)]
    for r in rows:
        r["provenance"]["site_listing_ref"] = None                    # force canonical_url keying
        r["provenance"]["canonical_url"] = "https://x/same"
    d = listings.diff_runs(rows, "A", "B")
    assert d["counts"]["both"] == 1 and d["counts"]["both_unchanged"] == 1


def test_run_diff_errors(make_client):
    build, _ = make_client
    c = build(ROWS_TWO_RUNS)
    assert c.get("/api/v1/listings/runs/diff", params={"run_a": "run_A", "run_b": "nope"}).status_code == 404
    assert c.get("/api/v1/listings/runs/diff", params={"run_a": "run_A", "run_b": "run_A"}).status_code == 422


def test_runs_with_no_overlap_are_reported_not_comparable(make_client):
    build, _ = make_client
    rows = [rec("a1", "M1", "run_A", "2026-10-13T10:00:00Z"), rec("b1", "M2", "run_B", "2026-10-15T10:00:00Z")]
    c = build(rows)
    o = c.get("/api/v1/listings/runs").json()
    assert o["comparable"] is False and o["best_pair"] is None and o["listings_in_multiple_runs"] == 0
    d = c.get("/api/v1/listings/runs/diff", params={"run_a": "run_A", "run_b": "run_B"}).json()
    assert d["counts"]["both"] == 0 and d["counts"]["only_a"] == 1 and d["counts"]["only_b"] == 1


def test_single_run_table(make_client):
    build, _ = make_client
    o = build([rec("a1", "M1", "run_A", "2026-10-13T10:00:00Z")]).get("/api/v1/listings/runs").json()
    assert len(o["runs"]) == 1 and o["pair_overlap"] == [] and o["comparable"] is False


def test_inspector_lists_other_observations(make_client):
    build, _ = make_client
    r = build(ROWS_TWO_RUNS).get("/api/v1/listings/b2").json()
    assert [o["record_id"] for o in r["other_observations"]] == ["a2"]


# ---------- flags ----------

def flag_body(**kw):
    return {"record_id": "b3", "field": "Bedrooms", "reason": "not_parsed", "note": "says 3", "expected_value": "3", **kw}


def test_flag_lifecycle_and_roles(make_client):
    build, as_role = make_client
    c = build(ROWS_TWO_RUNS)
    f = c.post("/api/v1/listings/flags", json=flag_body())
    assert f.status_code == 201
    f = f.json()
    assert f["created_by"] == "alice" and f["status"] == "open" and f["created_at"]
    assert f["raw_value"] == "3" and f["parsed_value"] is None      # snapshot of the unparsed bedrooms
    assert f["site_listing_ref"] == "M3" and f["scrape_run_id"] == "run_B"

    assert c.get("/api/v1/listings/flags", params={"record_id": "b3"}).json()["total"] == 1
    assert c.get("/api/v1/listings/flags", params={"status": "resolved"}).json()["total"] == 0
    s = c.get("/api/v1/listings/flags/summary").json()
    assert (s["open"], s["resolved"], s["open_listings"]) == (1, 0, 1)

    # Underwriter may not resolve or delete
    assert c.patch(f"/api/v1/listings/flags/{f['id']}/resolve", json={}).status_code == 403
    assert c.delete(f"/api/v1/listings/flags/{f['id']}").status_code == 403

    as_role(UserRole.ADMIN, "root")
    r = c.patch(f"/api/v1/listings/flags/{f['id']}/resolve", json={"resolution_note": "parser fixed"}).json()
    assert r["status"] == "resolved" and r["resolved_by"] == "root" and r["resolved_at"]
    assert c.patch(f"/api/v1/listings/flags/{f['id']}/resolve", json={}).status_code == 409
    assert c.get("/api/v1/listings/flags/summary").json()["open"] == 0
    assert c.delete(f"/api/v1/listings/flags/{f['id']}").status_code == 200
    assert c.delete(f"/api/v1/listings/flags/{f['id']}").status_code == 404


def test_viewer_cannot_create_but_can_read(make_client):
    build, as_role = make_client
    c = build(ROWS_TWO_RUNS)
    as_role(UserRole.VIEWER, "vic")
    assert c.post("/api/v1/listings/flags", json=flag_body()).status_code == 403
    assert c.get("/api/v1/listings/flags").status_code == 200
    assert c.get("/api/v1/listings/flags/export.csv").status_code == 200


def test_flag_validation(make_client):
    build, _ = make_client
    c = build(ROWS_TWO_RUNS)
    assert c.post("/api/v1/listings/flags", json=flag_body(record_id="nope")).status_code == 404
    assert c.post("/api/v1/listings/flags", json=flag_body(field="Nonsense")).status_code == 422
    assert c.post("/api/v1/listings/flags", json=flag_body(reason="meh")).status_code == 422
    assert c.get("/api/v1/listings/flags/meta").json()["reasons"]


def test_flag_filters_and_csv_export(make_client):
    build, as_role = make_client
    c = build(ROWS_TWO_RUNS)
    c.post("/api/v1/listings/flags", json=flag_body())
    c.post("/api/v1/listings/flags", json=flag_body(record_id="b2", field="Price", reason="wrong_value",
                                                    note='has "quotes", and a comma', expected_value=None))
    assert c.get("/api/v1/listings/flags", params={"field": "Price"}).json()["total"] == 1
    assert c.get("/api/v1/listings/flags", params={"reason": "not_parsed"}).json()["total"] == 1
    as_role(UserRole.ADMIN, "root")
    c.patch("/api/v1/listings/flags/1/resolve", json={})
    open_csv = c.get("/api/v1/listings/flags/export.csv")
    assert open_csv.headers["content-type"].startswith("text/csv")
    import csv, io
    rows = list(csv.DictReader(io.StringIO(open_csv.text)))
    assert [r["field"] for r in rows] == ["Price"] and rows[0]["note"] == 'has "quotes", and a comma'
    all_rows = list(csv.DictReader(io.StringIO(c.get("/api/v1/listings/flags/export.csv", params={"status": ""}).text)))
    assert len(all_rows) == 2


def test_flags_route_not_shadowed_by_record_id(make_client):
    build, _ = make_client
    c = build(ROWS_TWO_RUNS)
    assert "items" in c.get("/api/v1/listings/flags").json()
