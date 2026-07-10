select
    ru.run_id,
    ru.as_of_date,
    ru.scenario_name,
    ru.scenario_type,
    count(*) as properties_affected,
    sum(case when r.flagged then 1 else 0 end) as flagged_count,
    avg(r.value_delta_pct) as avg_value_delta_pct,
    avg(r.ltv_delta) as avg_ltv_delta,
    min(r.new_value - r.prior_value) as min_value_change,
    max(r.new_value - r.prior_value) as max_value_change
from {{ ref('stg_revaluation_results') }} r
left join {{ ref('stg_revaluation_runs') }} ru using (run_id)
group by
    ru.run_id,
    ru.as_of_date,
    ru.scenario_name,
    ru.scenario_type
