"""dlt source: valuation-vendor mock API — a paginated JSON feed served by the standalone
vendor_api/ FastAPI service (not an in-process shortcut; see vendor_api/main.py), the shape a
real valuation-vendor/MLS-type integration would take.
"""
import os

import dlt
import httpx

from ..mapping import validate_valuation_vendor

VENDOR_API_BASE_URL = os.environ.get("VENDOR_API_BASE_URL", "http://localhost:8001")


def _fetch_all_records() -> list[dict]:
    records = []
    page = 1
    with httpx.Client(timeout=15) as client:
        while True:
            resp = client.get(f"{VENDOR_API_BASE_URL}/records", params={"page": page, "page_size": 200})
            resp.raise_for_status()
            body = resp.json()
            records.extend(body["records"])
            if not body["has_more"]:
                break
            page += 1
    return records


@dlt.source(name="valuation_vendor")
def valuation_vendor_source():
    clean_rows, rejected_rows = [], []
    for row in _fetch_all_records():
        mapped, reason = validate_valuation_vendor(row)
        if mapped is not None:
            clean_rows.append(mapped)
        else:
            reason_code, reason_detail = reason
            rejected_rows.append({
                "raw_record": row, "reason_code": reason_code, "reason_detail": reason_detail,
            })

    @dlt.resource(name="valuation_vendor_clean", write_disposition="merge", primary_key="pid")
    def clean(last_updated=dlt.sources.incremental("last_updated", initial_value="")):
        yield clean_rows

    @dlt.resource(name="valuation_vendor_rejected", write_disposition="append",
                 columns={"raw_record": {"data_type": "json"}})
    def rejected():
        yield rejected_rows

    return clean, rejected
