-- password_hash is deliberately excluded — never surface it past this source, even in an
-- internal analytics schema.
select
    id as user_id,
    username,
    role
from {{ source('trident_operational', 'users') }}
