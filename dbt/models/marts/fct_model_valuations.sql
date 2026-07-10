select
    v.model_valuation_id,
    v.pid,
    v.model_id,
    mo.model_name,
    mo.model_status,
    v.estimated_value,
    v.value_low,
    v.value_high,
    v.computed_at
from {{ ref('stg_model_valuations') }} v
left join {{ ref('stg_models') }} mo using (model_id)
