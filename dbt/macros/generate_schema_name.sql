{# Use custom schema names as-is (e.g. "snapshots"), instead of dbt's default "<target>_snapshots". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
