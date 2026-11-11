# Sales CRM data model (learning project, simulated data)

A learning project on simulated data. The standard objects of a B2B sales CRM (leads, accounts, contacts,
opportunities and opportunity history) come from the sales CRM pack in
[saas-world-sim](https://github.com/sky-five/saas-world-sim#domain-pack-sales-crm) v0.5.0. They are loaded as of a
date into DuckDB and modelled in a small dbt project. The pack is messy on purpose and keeps the answers in label
columns. Those labels are never loaded, so the fixes here are scored against data the models never saw. Nothing here
comes from a real CRM or real customers.

```bash
python -m crm_pipeline                     # load as of 2026-06-30, dbt build, score, write results/summary.json
python -m crm_pipeline --as-of 2026-03-31  # any other date (results file left alone)
```

The warehouse goes to `warehouse/crm.duckdb`. The main warehouse and the nightly build are not touched.

| Model | What it does |
|---|---|
| `stg_crm__*` | One view per CRM object, renamed and typed. Accounts get a `name_key`: lower case, `&` read as `and`, punctuation and a trailing LLC / Inc / Co dropped. |
| `int_account_dedupe` | Maps each account record to the earliest record of the same company. Rule 1 is the same website. Rule 2, for records with no website, is the same name key and billing state. Name alone is not enough, because different companies share names like "Golden Crest Roofing Co" in other states. |
| `int_opportunity_close_dates` | The close date the rep typed vs the day the deal really closed (from the stage change). A deal closed in one quarter but dated in an earlier one is flagged as backdated. Reporting uses the corrected date. |
| `int_opportunity_snapshots` | The open pipeline on the first day of each quarter, rebuilt from the history (each deal's latest change before that day). |
| `fct_opportunities`, `dim_accounts` | Deals on the deduplicated account, with corrected close date, days to close and close-date pushes. One row per company. |
| `stage_conversion` | Of the closed deals that reached each stage, the share that moved on and the share that were won. |
| `sales_velocity` | Open deals x win rate x average won deal / median days to win, per segment, from new-business deals closed in the last 365 days. |
| `pipeline_coverage` | Open pipeline by expected close quarter, against the average won per quarter over the last four complete quarters. The CRM holds no quota, so that average stands in for one. |
| `forecast_backtest` | On each quarter's first day, a forecast of the open deals due that quarter, weighted two ways. One uses the CRM's stage probability. The other uses the win rate per stage learned from earlier snapshots whose outcome was already known. Both are compared with what was really won. |

## Results as of 2026-06-30

| Check | Number |
|---|---|
| Duplicate accounts | 903 records, 61 labelled duplicates. The dedupe found 60 (35 by website, 25 by name and state) with 0 false matches, leaving 843 companies |
| Backdated close dates | the 9 labelled deals closed by this date were all caught, with 0 false flags. They move $84,700 of wins into the quarter they really closed in. A 10th labelled deal is still open on this date, so it has not been backdated yet |
| Totals | 1,006 deals and $6,007,400 won, the same as the pack, after dedupe |
| Stage conversion | win rate 47.9% from prospecting, 60.7% from demo, 83.0% from negotiation |
| Velocity (new business) | smb: 41.3% win rate, $6,298 average won, 47 days to win. enterprise: 37.5%, $68,967, 152.5 days |
| Coverage | $1,923,200 open for 2026 Q3, 3.16x the $608,125 average won per quarter |
| Forecast back-test | 9 quarters. In the 8 that have learned rates, the mean absolute error is 27.1% with CRM probabilities and 19.6% with learned stage rates. CRM probabilities came in below the real result in all 9 quarters, partly because deals created during a quarter are not in its opening pipeline |

The planted patterns from the pack show up in the marts. Partner referrals win more new-business deals than web forms.
Enterprise deals take more than twice as long to win as smb. Deals pushed twice or more win far less often.

## Object queries

`soql/` has four SOQL-style queries as a CRM's own query tool would take them: open pipeline by stage, won by
source last quarter, a parent-to-child subquery from accounts to their open deals, and deals pushed twice from the
field history. Each comes with a `.sql` version that runs on the staging models. The won-by-source query reads the
recorded close date, as the object query would, so it still counts backdated deals in the earlier quarter.

## Tests

`tests/crm_pipeline/` (14 tests, about 8 seconds). They build a fresh warehouse and check that the labels stay out
of it, that dedupe and backdating are scored against the labels, that totals match the pack, that stage win rates
rise, that the planted patterns are visible, and that the learned-rate forecast beats CRM probabilities. They also
run every `.sql` query and check that `results/summary.json` matches the code.
