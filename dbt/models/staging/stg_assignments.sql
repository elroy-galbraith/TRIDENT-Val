select
    id as assignment_id,
    pid,
    assignee_username,
    state as assignment_state,
    due_date,
    created_by,
    created_at,
    completed_at,
    -- Days-in-state: still counting up to now for open work, or the actual resolution
    -- time for Done ones — lets resolution-time reporting reuse this one column.
    case
        when state != 'Done' then {{ dbt.datediff('created_at', dbt.current_timestamp(), 'day') }}
        else {{ dbt.datediff('created_at', 'completed_at', 'day') }}
    end as days_open
from {{ source('trident_operational', 'assignments') }}
