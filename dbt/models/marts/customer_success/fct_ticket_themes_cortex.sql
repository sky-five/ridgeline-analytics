-- The same classification done inside Snowflake with Cortex AI_CLASSIFY.
-- Off by default: Cortex functions are blocked on Snowflake trial accounts.
-- Turn on with --vars '{use_cortex: true}' on a paid Snowflake account.
{{ config(enabled=(var('use_cortex', false) and target.type == 'snowflake')) }}

select
    ticket_id,
    ai_classify(
        subject || '. ' || body,
        ['measurement_accuracy', 'billing_price', 'missing_feature', 'how_to', 'bug_outage', 'integration']
    ):labels[0]::varchar as churn_theme
from {{ ref('stg_support__tickets') }}
