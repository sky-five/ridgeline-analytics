-- Daily calendar MetricFlow uses to fill and roll up time.
{{ config(materialized='table') }}

{{ dbt_utils.date_spine(
    datepart="day",
    start_date="cast('2024-01-01' as date)",
    end_date="cast('2028-01-01' as date)"
) }}
