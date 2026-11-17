{# The same campaign is spelled differently by every tool: "North Roofing - Roof Repair",
   "NORTH_ROOFING_ROOF-REPAIR ", "North Roofing | Roof Repair". All become north_roofing_roof_repair. #}
{% macro campaign_key(col) -%}
    trim(regexp_replace(lower({{ col }}), '[^a-z0-9]+', '_', 'g'), '_')
{%- endmacro %}

{# Phones typed four ways, plus +1 numbers from call tracking: keep the last ten digits. #}
{% macro phone10(col) -%}
    nullif(right(regexp_replace({{ col }}, '[^0-9]', '', 'g'), 10), '')
{%- endmacro %}

{# The CRM's hidden field sometimes keeps the whole query parameter: gclid=ABC -> ABC. #}
{% macro click_id(col) -%}
    nullif(regexp_replace(trim({{ col }}), '^(gclid|fbclid)=', ''), '')
{%- endmacro %}
