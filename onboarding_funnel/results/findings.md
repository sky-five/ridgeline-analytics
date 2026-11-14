# Onboarding funnel: findings

Simulated data. People who started from 2026-01-05 to 2026-05-25 (weeks with the full 30-day activation window by 2026-06-30). Activated = first transaction within 30 days of starting.

## The funnel

| program | started | KYC pass (of submitted) | activated | median days to first transaction | biggest drop-off | biggest KYC fail reason |
|---|---:|---:|---:|---:|---|---|
| gig_payouts | 5,000 | 94.6% | 73.5% | 2.0 | left_before_document_upload (26.9%) | document_unreadable |
| consumer_card | 8,031 | 91.0% | 45.1% | 2.9 | not_funded (36.2%) | document_unreadable |
| business_expense | 3,072 | 80.4% | 34.3% | 8.4 | left_before_document_upload (34.1%) | address_unverified |
| cross_border | 4,025 | 86.5% | 33.2% | 4.7 | not_funded (32.9%) | document_unreadable |

## What moved

- consumer_card kyc_pass_rate: 91.5% -> 87.9% from the week of 2026-05-11 (t = -5.4), read as **real**.
- cross_border activation_rate_per_id: 33.6% -> 28.8% from the week of 2026-04-06 (t = -3.1), read as **counting artefact**.

## Not a real drop: cross_border from 2026-04-06

Counted per application id, activation fell from 33.6% to 28.8% (-4.8 pp, 95% CI -7.6 to -2.0). Counted per person it went from 33.6% to 32.6% (-1.0 pp, 95% CI -4.0 to +2.0): about 80% of the drop is people counted twice. Application ids per person went above 1.02 that week and stayed there (up to 1.176).

## Can the counts be trusted

- 1,706 of 114,999 delivered events were redeliveries; each is counted once.
- 24,326 application ids belong to 24,000 people-in-a-program; the key (trimmed lower-case email + date of birth) splits 0 and merges 0 against the simulator's labels. Keyed on the raw email it would split 165.

## What to look at

- cross_border: find what opens a second application id from 2026-04-06, and report activation per person, not per application id.
- consumer_card: the KYC pass rate drop is real. selfie_mismatch grew the most, from 2.9% to 8.9% of people submitted, from 2026-05-11; look at what changed in that check that week.
- consumer_card and cross_border: the largest loss is people who pass KYC and never fund the account, not KYC itself.
