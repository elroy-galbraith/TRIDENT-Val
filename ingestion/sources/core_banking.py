"""dlt source: core-banking-style CSV drop (SFTP-shaped) — loan/account fields, with the ugly
realities of a real feed: renamed columns, zero-padded string PIDs, dates in DD/MM/YYYY, and a
handful of deliberately malformed rows for the quarantine demo. Files are dropped by
scripts/generate_ingestion_sources.py into ingestion/dropzone/core_banking/.
"""
import csv
from pathlib import Path

import dlt

from ..mapping import validate_core_banking

DROPZONE = Path(__file__).resolve().parents[1] / "dropzone" / "core_banking"


def _read_rows() -> list[dict]:
    if not DROPZONE.exists():  # fresh checkout, generator hasn't run yet — sync 0 rows, don't crash
        return []
    rows = []
    for path in sorted(DROPZONE.glob("*.csv")):
        with open(path, newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows


@dlt.source(name="core_banking")
def core_banking_source():
    clean_rows, rejected_rows = [], []
    for row in _read_rows():
        mapped, reason = validate_core_banking(row)
        if mapped is not None:
            clean_rows.append(mapped)
        else:
            reason_code, reason_detail = reason
            rejected_rows.append({
                "raw_record": row, "reason_code": reason_code, "reason_detail": reason_detail,
            })

    @dlt.resource(name="core_banking_clean", write_disposition="merge", primary_key="pid")
    def clean(last_updated=dlt.sources.incremental("last_updated", initial_value="")):
        yield clean_rows

    @dlt.resource(name="core_banking_rejected", write_disposition="append",
                 columns={"raw_record": {"data_type": "json"}})
    def rejected():
        yield rejected_rows

    return clean, rejected
