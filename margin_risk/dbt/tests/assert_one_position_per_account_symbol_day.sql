-- A positions file loaded twice must not count twice.
select as_of_date, account_id, symbol from {{ ref('fct_position_day') }}
group by as_of_date, account_id, symbol having count(*) > 1
