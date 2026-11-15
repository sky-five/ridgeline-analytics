select site_id, site_type, region
from {{ source('raw_ed', 'sites') }}
