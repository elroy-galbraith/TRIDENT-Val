"""dlt orchestration: runs one fake source system's dlt pipeline into a local DuckDB staging
file, then merges the clean rows into TRIDENT-Val's canonical SQLAlchemy tables (with
provenance) and copies rejected rows into `IngestionQuarantine` — bad records are quarantined,
never silently dropped.

dlt lands into a *separate* staging schema, never straight into `properties`/
`bank_portfolio_meta` — a plain-Python merge step (below) then upserts provenance for every
row and, for `core_banking` only, refreshes `BankPortfolioMeta.current_loan_balance`. It never
touches `current_avm_value`/`avm_variance_pct`/`audit_status`: those stay owned by the AVM
scoring/triage logic in scripts/seed_db.py and app/main.py, so a sync can never silently
perturb the numbers the rest of the app's demo (Dashboard, Inspector, Model Compare) depends
on. `valuation_vendor`/`valuations_team` land as provenance only in this pass.

Row-level business validation happens per-source (see ingestion/mapping.py) before this
module ever sees the data; schema drift (a source adding a column) is handled by dlt's own
default "evolve" schema contract — deliberately not tightened, since the point of the demo
beat is that a new column shouldn't break anything. This module just diffs the clean table's
columns before/after `pipeline.run()` to report what changed.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import dlt
from sqlalchemy.orm import Session

# Self-sufficient regardless of the caller's sys.path (main.py already has this on PYTHONPATH
# in the running app; scripts/generate_ingestion_sources.py and ad hoc test runs may not) —
# same explicit-insert convention scripts/seed_db.py uses for the same reason.
_BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.models import (BankPortfolioMeta, IngestionQuarantine, IngestionRun,  # noqa: E402
                        IngestionRunStatus, Property, PropertySourceRecord, SourceSystem)

from .sources.core_banking import core_banking_source
from .sources.valuation_vendor import valuation_vendor_source
from .sources.valuations_team import valuations_team_source

STAGING_DIR = Path(__file__).resolve().parent / ".dlt_staging"
_NON_DATA_COLUMNS = {"_dlt_load_id", "_dlt_id"}

_SOURCE_SPECS = {
    SourceSystem.CORE_BANKING: {
        "factory": core_banking_source,
        "clean_table": "core_banking_clean",
        "rejected_table": "core_banking_rejected",
        "natural_key": "acct_pid",
    },
    SourceSystem.VALUATION_VENDOR: {
        "factory": valuation_vendor_source,
        "clean_table": "valuation_vendor_clean",
        "rejected_table": "valuation_vendor_rejected",
        "natural_key": "pid",
    },
    SourceSystem.VALUATIONS_TEAM: {
        "factory": valuations_team_source,
        "clean_table": "valuations_team_clean",
        "rejected_table": "valuations_team_rejected",
        "natural_key": "pid",
    },
}


def _make_pipeline(source_system: SourceSystem) -> dlt.Pipeline:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    destination = dlt.destinations.duckdb(credentials=str(STAGING_DIR / f"{source_system.value}.duckdb"))
    return dlt.pipeline(pipeline_name=f"ingest_{source_system.value}", destination=destination,
                        dataset_name="raw_ingestion", pipelines_dir=str(STAGING_DIR / "_pipelines"))


def _table_columns(pipeline: dlt.Pipeline, table_name: str) -> set:
    if not pipeline.schema_names:  # first-ever run for this pipeline_name — nothing loaded yet
        return set()
    schema = pipeline.default_schema
    if table_name not in schema.tables:
        return set()
    return set(schema.get_table_columns(table_name).keys()) - _NON_DATA_COLUMNS


def _fetch_rows(pipeline: dlt.Pipeline, table_name: str) -> list[dict]:
    if table_name not in pipeline.default_schema.tables:
        return []
    with pipeline.sql_client() as client:
        with client.execute_query(f"SELECT * FROM {table_name}") as cur:
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def _clean_payload(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _NON_DATA_COLUMNS}


def _merge_core_banking(db: Session, run: IngestionRun, rows: list[dict]) -> int:
    loaded = 0
    for row in rows:
        pid = row["pid"]
        prop = db.get(Property, pid)
        if prop is None:
            continue  # a source can reference a PID outside this PoC's seeded book — skip cleanly
        meta = db.get(BankPortfolioMeta, pid)
        if meta is not None:
            meta.current_loan_balance = row["loan_bal"]

        rec = db.query(PropertySourceRecord).filter_by(
            pid=pid, source_system=SourceSystem.CORE_BANKING).one_or_none()
        if rec is None:
            rec = PropertySourceRecord(pid=pid, source_system=SourceSystem.CORE_BANKING)
            db.add(rec)
        rec.source_record_id = row.get("acct_pid")
        rec.ingestion_run_id = run.id
        rec.raw_payload = _clean_payload(row)
        rec.mapped_fields = ["current_loan_balance"]
        loaded += 1
    return loaded


def _merge_provenance_only(db: Session, run: IngestionRun, source_system: SourceSystem,
                          rows: list[dict], natural_key: str) -> int:
    """valuation_vendor / valuations_team land as provenance only in this pass — no write to
    Property/BankPortfolioMeta, which stay owned by the AVM/triage logic (see module docstring)."""
    loaded = 0
    for row in rows:
        pid = row["pid"]
        prop = db.get(Property, pid)
        if prop is None:
            continue
        rec = db.query(PropertySourceRecord).filter_by(pid=pid, source_system=source_system).one_or_none()
        if rec is None:
            rec = PropertySourceRecord(pid=pid, source_system=source_system)
            db.add(rec)
        rec.source_record_id = str(row.get(natural_key))
        rec.ingestion_run_id = run.id
        rec.raw_payload = _clean_payload(row)
        rec.mapped_fields = []
        loaded += 1
    return loaded


def run_sync(db: Session, source_system: SourceSystem, actor: Optional[str]) -> IngestionRun:
    """Runs one source's dlt pipeline, merges clean rows into canonical tables + provenance,
    and copies rejected rows into IngestionQuarantine. Synchronous, matching the rest of the
    app's heavy-but-synchronous operations (report generation, revaluation cycles)."""
    spec = _SOURCE_SPECS[source_system]
    run = IngestionRun(source_system=source_system, status=IngestionRunStatus.RUNNING, triggered_by=actor)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        pipeline = _make_pipeline(source_system)
        before_cols = _table_columns(pipeline, spec["clean_table"])
        is_first_sync_ever = not before_cols
        load_info = pipeline.run(spec["factory"]())
        after_cols = _table_columns(pipeline, spec["clean_table"])
        # Only report a diff once this table has synced before — on the very first sync ever,
        # every column is "new" relative to nothing, which isn't the schema-drift signal the
        # UI cares about (a source adding a column to an already-established feed).
        new_cols = [] if is_first_sync_ever else sorted(after_cols - before_cols)

        clean_rows = _fetch_rows(pipeline, spec["clean_table"])
        rejected_rows = _fetch_rows(pipeline, spec["rejected_table"])

        if source_system == SourceSystem.CORE_BANKING:
            loaded = _merge_core_banking(db, run, clean_rows)
        else:
            loaded = _merge_provenance_only(db, run, source_system, clean_rows, spec["natural_key"])

        quarantined = 0
        for row in rejected_rows:
            raw_record = row.get("raw_record")
            if isinstance(raw_record, str):
                try:
                    raw_record = json.loads(raw_record)
                except (json.JSONDecodeError, TypeError):
                    pass
            db.add(IngestionQuarantine(
                source_system=source_system, ingestion_run_id=run.id,
                raw_record=raw_record, reason_code=row.get("reason_code"),
                reason_detail=row.get("reason_detail"),
            ))
            quarantined += 1

        run.status = IngestionRunStatus.SUCCEEDED
        run.completed_at = datetime.now(timezone.utc)
        run.records_seen = len(clean_rows) + len(rejected_rows)
        run.records_loaded = loaded
        run.records_quarantined = quarantined
        run.schema_columns_added = new_cols or None
        run.dlt_load_id = load_info.loads_ids[0] if load_info.loads_ids else None
        db.commit()
        return run
    except Exception as e:
        db.rollback()
        run = db.get(IngestionRun, run.id)
        run.status = IngestionRunStatus.FAILED
        run.completed_at = datetime.now(timezone.utc)
        run.error = str(e)
        db.commit()
        raise
