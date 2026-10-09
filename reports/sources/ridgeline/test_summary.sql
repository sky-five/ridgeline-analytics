select resource_type, status, count(*) as nodes from reporting.dbt_run_results group by 1, 2 order by 1, 2
