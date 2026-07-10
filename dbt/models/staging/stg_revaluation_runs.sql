select
    id as run_id,
    as_of_date,
    scenario_name,
    scenario_type,
    model_id,
    created_by,
    created_at
from {{ source('trident_operational', 'revaluation_runs') }}
