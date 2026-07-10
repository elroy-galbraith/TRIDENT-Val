select
    id as model_id,
    name as model_name,
    version as model_version,
    architecture,
    explainer,
    status as model_status,
    holdout_mape,
    holdout_r2,
    trained_at,
    promoted_at
from {{ source('trident_operational', 'models') }}
