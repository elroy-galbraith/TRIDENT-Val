"""Per-source row validation and canonical-field mapping for the dlt ingestion pipeline
(see ingestion/pipeline.py).

Row-level business validation (a negative loan balance, an unparseable PID) is deliberately
custom Python here, not a dlt schema contract — dlt's contracts govern *shape* (a source
adding a column, which should never break anything; see ingestion/pipeline.py's schema-drift
handling), not *business rules* (a negative loan balance is still a perfectly well-typed
float). Every validator returns either a clean canonical-shaped row, or `None` plus a
(reason_code, reason_detail) pair the caller routes into `IngestionQuarantine` — bad records
are never silently dropped.
"""
from datetime import datetime
from typing import Optional


def parse_zero_padded_pid(raw) -> Optional[int]:
    """core_banking's PIDs arrive as zero-padded strings (e.g. '000526301100')."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or not s.lstrip("0").isdigit() and s != "0" * len(s):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def validate_core_banking(row: dict) -> tuple[Optional[dict], Optional[tuple]]:
    pid = parse_zero_padded_pid(row.get("acct_pid"))
    if pid is None:
        return None, ("pid_unparseable", f"acct_pid {row.get('acct_pid')!r} is not a valid zero-padded PID")
    try:
        loan_bal = float(row["loan_bal"])
    except (KeyError, TypeError, ValueError):
        return None, ("loan_balance_unparseable", f"loan_bal {row.get('loan_bal')!r} is not numeric")
    if loan_bal < 0:
        return None, ("negative_loan_balance", f"loan_bal {loan_bal} is negative")
    try:
        orig_dt = datetime.strptime(row["orig_dt"], "%d/%m/%Y").date().isoformat()
    except (KeyError, TypeError, ValueError):
        return None, ("orig_date_unparseable", f"orig_dt {row.get('orig_dt')!r} is not DD/MM/YYYY")
    return {
        "pid": pid,
        "acct_pid": row.get("acct_pid"),
        "loan_bal": loan_bal,
        "orig_dt": orig_dt,
        "last_updated": row.get("last_updated") or orig_dt,
        "disbursement_channel": row.get("disbursement_channel"),  # present only after schema drift
    }, None


def validate_valuation_vendor(row: dict) -> tuple[Optional[dict], Optional[tuple]]:
    try:
        pid = int(row["pid"])
    except (KeyError, TypeError, ValueError):
        return None, ("pid_unparseable", f"pid {row.get('pid')!r} is not a valid PID")
    try:
        appraised_value = float(row["appraised_value"])
    except (KeyError, TypeError, ValueError):
        return None, ("appraised_value_unparseable",
                      f"appraised_value {row.get('appraised_value')!r} is not numeric")
    return {**row, "pid": pid, "appraised_value": appraised_value}, None


def validate_valuations_team(row: dict) -> tuple[Optional[dict], Optional[tuple]]:
    raw_pid = row.get("pid")
    if raw_pid in (None, "", "nan"):
        return None, ("pid_missing", "pid is blank")
    try:
        pid = int(float(raw_pid))
    except (TypeError, ValueError):
        return None, ("pid_unparseable", f"pid {raw_pid!r} is not a valid PID")
    try:
        valuation_figure = float(row["valuation_figure"])
    except (KeyError, TypeError, ValueError):
        return None, ("valuation_figure_unparseable",
                      f"valuation_figure {row.get('valuation_figure')!r} is not numeric")
    return {
        "pid": pid,
        "valuation_figure": valuation_figure,
        "notes": row.get("notes") or "",
        "reviewed_by": row.get("reviewed_by") or "",
        "last_updated": row.get("last_updated") or datetime.utcnow().date().isoformat(),
    }, None
