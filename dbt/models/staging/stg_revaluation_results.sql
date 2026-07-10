select
    id as revaluation_result_id,
    run_id,
    pid,
    prior_value,
    new_value,
    value_delta_pct,
    prior_ltv,
    new_ltv,
    ltv_delta,
    flagged,
    audit_status_after
from {{ source('trident_operational', 'revaluation_results') }}
