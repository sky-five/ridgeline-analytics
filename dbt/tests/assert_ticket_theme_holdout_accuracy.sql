-- The ticket-theme classifier must agree with the hand labels on tickets it wasn't trained on (>= 90%).
select
    count(*) as holdout_tickets,
    avg(case when predicted_theme = labelled_theme then 1.0 else 0.0 end) as accuracy
from {{ ref('fct_ticket_themes') }}
where split = 'holdout'
having count(*) < 30 or avg(case when predicted_theme = labelled_theme then 1.0 else 0.0 end) < 0.9
