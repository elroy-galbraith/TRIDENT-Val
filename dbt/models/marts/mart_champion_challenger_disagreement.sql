-- Materiality threshold (10%) mirrors the app's default divergence threshold at
-- GET /api/v1/models/disagreements (backend/app/main.py) so this mart and the live
-- triage queue agree on what counts as a "disagreement".
with champion as (
    select
        pid,
        model_id as champion_model_id,
        estimated_value as champion_value
    from {{ ref('fct_model_valuations') }}
    where model_status = 'Champion'
),

challenger as (
    select
        pid,
        model_id as challenger_model_id,
        model_name as challenger_model_name,
        estimated_value as challenger_value
    from {{ ref('fct_model_valuations') }}
    where model_status = 'Challenger'
)

select
    c.pid,
    c.champion_model_id,
    c.champion_value,
    ch.challenger_model_id,
    ch.challenger_model_name,
    ch.challenger_value,
    ch.challenger_value - c.champion_value as value_delta,
    (ch.challenger_value - c.champion_value) / nullif(c.champion_value, 0) as value_delta_pct,
    coalesce(
        abs((ch.challenger_value - c.champion_value) / nullif(c.champion_value, 0)) >= 0.10,
        false
    ) as material_disagreement
from champion c
inner join challenger ch using (pid)
