{#- The minute sums and the metrics in or_utilisation/metric_spec.yml, for any grouping of fct_blocks. -#}
{% macro utilisation_columns() %}
    count(*) as blocks,
    count(distinct block_date) as days,
    sum(allocated_minutes) as allocated_minutes,
    sum(released_minutes) as released_minutes,
    sum(credited_released_minutes) as credited_released_minutes,
    sum(owner_in_block_minutes) as owner_in_block_minutes,
    sum(owner_turnover_minutes) as owner_turnover_minutes,
    sum(reused_in_block_minutes) as reused_in_block_minutes,
    sum(completed_cases) as completed_cases,
    sum(cancelled_cases) as cancelled_cases,
    sum(owner_in_block_minutes) / sum(allocated_minutes) as block_utilisation,
    sum(owner_in_block_minutes) / nullif(sum(allocated_minutes) - sum(credited_released_minutes), 0)
        as adjusted_block_utilisation,
    (sum(owner_in_block_minutes) + sum(owner_turnover_minutes)) / sum(allocated_minutes)
        as block_utilisation_with_turnover,
    (sum(owner_in_block_minutes) + sum(reused_in_block_minutes)) / sum(allocated_minutes) as room_utilisation,
    sum(credited_released_minutes) / sum(allocated_minutes) as released_time_rate,
    sum(reused_in_block_minutes) / nullif(sum(released_minutes), 0) as released_time_reuse_rate,
    sum(cancelled_cases) / nullif(sum(completed_cases) + sum(cancelled_cases), 0) as same_day_cancellation_rate
{% endmacro %}
