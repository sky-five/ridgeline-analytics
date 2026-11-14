select vehicle_id, segment, segment = 'ev' as is_electric, msrp from {{ ref('stg_vehicles__vehicles') }}
