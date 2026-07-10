select
    id as model_valuation_id,
    pid,
    model_id,
    estimated_value,
    value_low,
    value_high,
    computed_at
from {{ source('trident_operational', 'model_valuations') }}
