select
    id as assignment_id,
    pid,
    assignee_username,
    state as assignment_state,
    due_date,
    created_by,
    created_at,
    completed_at,
    case
        when state != 'Done' then extract(day from (now() - created_at))
    end as days_open
from {{ source('trident_operational', 'assignments') }}
