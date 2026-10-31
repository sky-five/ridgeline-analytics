with paying as (select account_id, current_addons from main.dim_accounts where is_paying),
addons as (
    select unnest(string_split(current_addons, ',')) as addon
    from paying where current_addons <> ''
)
select addon, count(*) as accounts, count(*) / (select count(*) from paying) as share_of_paying
from addons
group by 1
order by 2 desc
