select *,
       case
           when name in ('mrr', 'new_mrr', 'expansion_mrr', 'churned_mrr', 'net_new_mrr', 'ad_spend', 'cac',
                         'retained_mrr', 'cohort_start_mrr')
               then case when latest_value < 0 then '-' else '' end || '$' || format('{:,.0f}', abs(latest_value))
           when name in ('activation_rate', 'free_to_paid_60d', 'lead_close_rate', 'measurement_redo_rate', 'nrr_12m')
               then format('{:.1f}%', 100 * latest_value)
           else format('{:,.0f}', latest_value)
       end as latest_shown,
       strftime(cast(latest_month as date), '%b %Y') as latest_month_label,
       case when reconciled then '✅ agrees' else '❌ ' || mismatched_months || ' months differ' end as check_status
from reporting.metric_glossary
