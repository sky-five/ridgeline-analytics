-- The seven metrics in long form: one row per day, site, line and metric.
{% set metrics = ['calls_offered', 'service_level', 'abandon_rate', 'avg_handle_minutes', 'claims_opened',
                  'claims_closed', 'open_backlog'] %}
{% for m in metrics %}
    select
        day,
        site,
        line,
        '{{ m }}' as metric,
        {{ m }}::double as value
    from {{ ref('fct_ops_day') }}
    {% if not loop.last %}union all{% endif %}
{% endfor %}
