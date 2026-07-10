-- Current open queue: every property still flagged or pending review, with its active
-- (non-Done) assignment if one has been made. Mirrors the manager rollup view the app
-- itself exposes, so this can be trended/reported on outside the live app.
select
    p.pid,
    p.neighborhood,
    p.bldg_type,
    p.audit_status,
    p.avm_variance_pct,
    p.ltv,
    a.assignment_id,
    a.assignee_username,
    a.assignment_state,
    a.due_date,
    a.days_open
from {{ ref('dim_properties') }} p
left join {{ ref('stg_assignments') }} a
    on a.pid = p.pid and a.assignment_state != 'Done'
where p.audit_status in ('Flagged: High Variance', 'Pending Review')
