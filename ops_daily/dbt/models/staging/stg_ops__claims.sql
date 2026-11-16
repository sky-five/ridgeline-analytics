select
    claim_id,
    site,
    line,
    opened_date::date as opened_date,
    closed_date::date as closed_date
from {{ source('raw_ops', 'claims') }}
