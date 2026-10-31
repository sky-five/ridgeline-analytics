-- last complete month; contractors with too few closed leads are left out of the peer comparison
select b.month, b.crew_size, b.region, b.leads, b.closed, b.won, b.close_rate, b.median_speed_min,
       b.close_rate_pctile, b.speed_pctile
from main.fct_contractor_benchmarks b
where b.month = (select max(month) - interval 1 month from main.fct_contractor_benchmarks)
  and b.closed >= 5
