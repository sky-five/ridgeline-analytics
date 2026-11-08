# Customer health scoring (learning project, simulated data)

A learning project on simulated data. It asks one question: can the signals a customer-success team sees
(product usage, support tickets, re-measure requests, late invoices, crew size, plan, tenure) warn that a
subscriber will cancel in the next 60 days? It answers it two ways and compares them on accounts held out from
fitting. The data is the simulated roofing-software business from
[saas-world-sim](https://github.com/sky-five/saas-world-sim) v0.4.0. Nothing here comes from real customers.

```bash
python -m customer_health          # build snapshots, compare score and model, write results/summary.json
python -m customer_health --check  # fail if the committed results are out of date
```

## How it works

| File | What it does |
|---|---|
| `features.py` | One snapshot per live subscription on the first of each month, July 2024 to May 2026 (23 months). Each snapshot uses only rows timestamped before that day: logins, measurements, proposals and jobs in the last 30 days, the login trend vs the month before, tickets and measurement-accuracy tickets, re-measure requests, invoices paid more than 7 days late in the last 90 days, tenure, plan and crew size. Status columns are never read, because the app overwrites them later. The label is a cancel in the next 60 days. |
| `model.py` | **Health score**: start at 100 and take points off for each warning sign (`SCORE_RULES`, eight rules, set by hand and not fitted). **Churn model**: a scaled logistic regression on the same columns. Accounts are split 70/30 by a hash of the account id, so one account's months never sit on both sides. |

## Results

As of the simulated history up to 2026-06-30: 9,028 snapshots of 1,061 accounts, 280 of them held out. 13.3% of
snapshots cancel within 60 days.

| On held-out accounts | Health score | Logistic regression |
|---|---|---|
| ROC AUC | 0.594 | 0.599 |
| Churn rate in the riskiest 20% each month | 16.6% | 18.2% |
| Share of all churners in that 20% | 27.4% | 30.0% |

What this shows:

- Both work only a little better than chance. In this simulation a cancel is mostly a monthly coin flip. The
  only real drivers are crew size (one-person crews cancel most) and a recent re-measure request, so no model can
  do much better.
- The hand-written score is nearly as good as the fitted model. It is easier to explain to an account manager,
  so it is a fair first version. The model mostly confirms which rules matter.
- The model's largest weight is crew size. Usage counts (logins, measurements, proposals) carry almost no weight:
  in this data, busy accounts cancel about as often as quiet ones.
- Measurement-accuracy tickets barely matter: 13.5% of snapshots with one cancel within 60 days, against 13.2%
  without. The score takes 10 points off for them anyway. Once total tickets and re-measures are in the model,
  its weight for them even turns negative. A real team would check a rule like this against data before
  keeping it.

The tests check that snapshots never see rows from after their date, that only live subscriptions are
snapshotted, that the split keeps each account on one side, and that a fresh run matches the committed results.
