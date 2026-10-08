{# Timestamps arrive from dlt as timestamptz. Convert to naive UTC so DuckDB's local session
   timezone can never shift them. #}
{% macro to_utc(col) %}{{ return(adapter.dispatch('to_utc')(col)) }}{% endmacro %}

{% macro default__to_utc(col) %}cast({{ col }} as {{ dbt.type_timestamp() }}){% endmacro %}

{% macro duckdb__to_utc(col) %}timezone('UTC', {{ col }}){% endmacro %}

{% macro snowflake__to_utc(col) %}convert_timezone('UTC', {{ col }})::timestamp_ntz{% endmacro %}


{# Read a number from a JSON text column. #}
{% macro json_number(col, key) %}{{ return(adapter.dispatch('json_number')(col, key)) }}{% endmacro %}

{% macro default__json_number(col, key) %}
    cast(json_extract_string({{ col }}, '$.{{ key }}') as {{ dbt.type_float() }})
{% endmacro %}

{% macro snowflake__json_number(col, key) %}
    cast(parse_json({{ col }}):{{ key }} as {{ dbt.type_float() }})
{% endmacro %}


{# The as-of date as a date literal, from the as_of_date var. #}
{% macro as_of_date() %}cast('{{ var("as_of_date") }}' as date){% endmacro %}

{# End of the as-of day, as a timestamp. #}
{% macro as_of_end() %}
    {{ dbt.dateadd('second', 86399, "cast('" ~ var("as_of_date") ~ "' as " ~ dbt.type_timestamp() ~ ")") }}
{% endmacro %}
