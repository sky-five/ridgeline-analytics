select
    call_date::date as day,
    site,
    line,
    offered::int as offered,
    answered::int as answered,
    abandoned::int as abandoned,
    answered_within_60s::int as answered_within_60s,
    handle_seconds::bigint as handle_seconds,
    staffed_hours::decimal(8, 1) as staffed_hours
from {{ source('raw_ops', 'calls') }}
