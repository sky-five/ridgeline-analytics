select dealer_id, region from {{ ref('stg_vehicles__dealers') }}
