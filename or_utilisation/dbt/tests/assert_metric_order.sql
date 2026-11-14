-- Plain block utilisation <= adjusted (smaller denominator) and <= with turnover (bigger numerator);
-- all rates between 0 and 1.
select block_week
from {{ ref('utilisation_weekly') }}
where not (0 <= block_utilisation and block_utilisation <= adjusted_block_utilisation
    and adjusted_block_utilisation <= 1 and block_utilisation <= block_utilisation_with_turnover
    and block_utilisation_with_turnover <= 1 and block_utilisation <= room_utilisation and room_utilisation <= 1)
