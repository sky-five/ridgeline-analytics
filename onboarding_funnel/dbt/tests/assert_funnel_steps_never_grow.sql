-- Each step reaches no more people than the step before it.
select program
from {{ ref('funnel_by_program') }}
where not (started >= uploaded and uploaded >= submitted and submitted >= kyc_passed
    and kyc_passed >= funded and funded >= activated)
