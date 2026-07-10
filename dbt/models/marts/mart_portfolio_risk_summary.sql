select
    neighborhood,
    bldg_type,
    count(*) as property_count,
    avg(ltv) as avg_ltv,
    avg(avm_variance_pct) as avg_avm_variance_pct,
    sum(case when audit_status = 'Flagged: High Variance' then 1 else 0 end) as flagged_count,
    sum(case when audit_status = 'Pending Review' then 1 else 0 end) as pending_review_count,
    sum(case when audit_status = 'Approved' then 1 else 0 end) as approved_count,
    sum(current_loan_balance) as total_loan_balance,
    sum(current_avm_value) as total_avm_value
from {{ ref('dim_properties') }}
group by
    neighborhood,
    bldg_type
