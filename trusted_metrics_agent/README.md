# Trusted metrics

HR and payroll questions ("what was attrition in Field Operations last quarter?", "what do we spend on overtime?") get different answers depending on who pulls the numbers and how. This folder puts one governed definition behind each metric and a role check in front of all of them, then exposes only that, as a read-only MCP server: a person or an AI client can ask for a defined metric, gets the definition back with every number, and is told plainly when their role cannot see something.

> **All data is synthetic.** `hr_data.py` makes a roofing software company of about 300 people (2024-01 to 2026-09) from a fixed seed. Employees are ids only: no names, birth dates or other personal fields.

```bash
python -m trusted_metrics_agent                      # load the exports, dbt build, print every metric for 2026-09
pytest tests/trusted_metrics_agent -q                # 42 tests, about 16 seconds
claude mcp add hr-metrics -- .venv/bin/python -m trusted_metrics_agent.server --role people_manager
```

The warehouse goes to `warehouse/trusted_metrics.duckdb`; the main warehouse is not touched.

## The data

| Table | Rows | What it is |
|---|---|---|
| `raw_hr.employees` | 476 | Everyone employed at some point: department, location, level 1-5, full or part time, hire date |
| `raw_hr.salary_changes` | 1,292 | Annual base salary from a date on: the hire salary, then 3% each January |
| `raw_hr.terminations` | 141 | Leaving date and reason (92 voluntary, 49 involuntary) |
| `raw_payroll.pay_lines` | 14,986 | Pay per person and month: base (pro-rated for part months), overtime (field crews and support), March bonus |

Six departments over four locations; field crews are never remote. People keep their department, location and level for their whole stay, so a group's headcount moves only with hires and leavers. Headcount goes from 234 at the end of January 2024 to 335 at the end of September 2026.

## Models (dbt on DuckDB)

- `hr_employee_months`: one row per person and month end they were employed on, with tenure and the salary in effect (an `asof` join on the salary history).
- `hr_group_months`: month end x department x location x level, every group in every month (zeros where nobody was there), with headcount, hires, leavers, tenure, salaries, pay by type, and trailing 12-month leavers and average headcount. **This is the only table the metrics read.**

dbt tests: each group's headcount rolls forward (last month + hires - leavers); every cent in the payroll export lands in exactly one group and month; nobody is paid for a month before they joined or after they left; keys are unique.

## Governed metrics and roles

`metrics.yml` holds every definition. Each metric is `sum(numerator) / sum(denominator)` over `hr_group_months`, so it adds up correctly over any group, and each has an owner, a version and a sensitivity.

| Metric | Definition (short) | Sensitivity |
|---|---|---|
| `headcount` | People employed on the month's last day | internal |
| `hires`, `terminations`, `voluntary_terminations` | People whose hire or leaving date falls in the month | internal |
| `attrition_rate_12m` | Leavers in the last 12 months / average of the 12 month-end headcounts (from 2024-12) | internal |
| `avg_tenure_months` | Average whole months since hire, over the people employed | internal |
| `payroll_cost` | Gross pay at the month end: base + overtime + bonus | confidential |
| `overtime_share` | Overtime pay / (base + overtime pay) | confidential |
| `avg_base_salary` | Average annual base salary in effect on the month end | restricted |

| Role | Metrics | Breakdowns |
|---|---|---|
| `all_staff` | headcount, hires | none (company totals) |
| `people_manager` | the six workforce metrics, no pay | department, location, level |
| `finance` | headcount, payroll cost, overtime share | department, location |
| `hr_partner` | all nine | department, location, level |

Rules the service enforces (`metrics.py`):

- **Role fixed at start.** The store, and the MCP server, are opened with one role. No tool takes a role, so a client cannot ask for a different one.
- **Declines say why, with no values.** A metric or breakdown outside the role raises a decline naming the roles that can see it.
- **Small groups.** Confidential and restricted values are withheld for any group of fewer than 5 people. If that would hide exactly one group in a month, the next smallest is withheld too, so the hidden value cannot be worked out as the total minus the shown groups. (It does not try to stop every combination of queries; that is a bigger problem than this demo takes on.) At the finest breakdown in 2026-09, 50 of 77 groups are withheld for each pay metric.
- **Every result cites its definition**: `source` (`trusted_metrics_agent/metrics.yml#<metric>`), `version`, `definition` and the model.
- **No SQL from outside.** Column names come only from `metrics.yml` and are checked against the model when the store opens; filter values must be values that exist and are bound as parameters; the DuckDB connection is read-only.

## The MCP server

`server.py` serves three tools over stdio: `list_metrics` (what this role can query, its breakdowns, the months with data), `describe_metric` (one definition, and whether this role may query it) and `query_metric` (values for a month or a range, optionally grouped or filtered). Errors and declines come back as `{"error": ...}` or `{"declined": ...}`, so a client can tell "you asked wrongly" from "you may not see this".

## How it's tested

- Every metric, every month (33, or 22 for attrition), equals a pandas computation straight from the raw exports, with no dbt in between.
- Department, location and level groups add up to the company total.
- Each role sees exactly the metrics and breakdowns `metrics.yml` gives it; everything else is declined, and a decline never carries the value.
- Across every pay metric and every combination of breakdowns for January to September 2026, no group under 5 people shows a value, and no month has exactly one hidden group next to shown ones.
- Unknown metrics, bad months, months outside the data, an injected filter value and an unknown dimension are errors, not queries; the connection refuses writes; a catalog naming a missing column or metric is rejected.
- The stdio server starts with a role, lists the three tools (none with a `role` input), answers with a citation and declines by role.

## Next

The agent on top of this server, which answers plain-language questions only through these tools, and a 30-question eval for accuracy and grounding, is the next step (not built yet).
