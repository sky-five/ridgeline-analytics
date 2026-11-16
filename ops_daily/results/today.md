# Operations: what to look at on Tuesday 2026-06-30

Simulated claims operation, three sites (east, central, west) x two lines (home, auto). Each metric is compared with the same weekday over the previous six weeks; see the README for the rule and [the definitions](../dbt/seeds/metric_definitions.csv).

## Three things

1. **Central home: open claims 384**, usually 84 on a Tuesday. First check: New claims against closing capacity; borrow adjusters or approve overtime while it is still growing.
2. **West auto: abandon rate 10.9%**, usually 2.5% on a Tuesday. Also flagged: service level. First check: Staffed hours against plan, then handle time, as for service level; callers who hang up often call back, so expect more calls tomorrow.
3. **East home: abandon rate 15.0%**, usually 4.1% on a Tuesday. First check: Staffed hours against plan, then handle time, as for service level; callers who hang up often call back, so expect more calls tomorrow.

## Metric by metric

**Calls offered** (calls that reached the site's queue for the line that day, answered or not): 2,111 across the operation today against 2,116 on recent Tuesdays. No team was flagged on it in the last seven days, so nothing to do today.

**Service level** (share of offered calls answered within 60 seconds; a call that hangs up counts against it): 76.4% across the operation today against 83.4% on recent Tuesdays. Flagged: West auto on 6 of the last 7 days; East home on 1 of the last 7 days. So what: Staffed hours against plan for the day, then handle time: one of the two has usually moved.

**Abandon rate** (share of offered calls where the caller hung up before an agent answered): 5.6% across the operation today against 2.9% on recent Tuesdays. Flagged: East home on 7 of the last 7 days; West auto on 7 of the last 7 days. So what: Staffed hours against plan, then handle time, as for service level; callers who hang up often call back, so expect more calls tomorrow.

**Average handle time** (talk, hold and after-call work per answered call): 8.4 min across the operation today against 8.2 min on recent Tuesdays. Flagged: East home on 5 of the last 7 days. So what: A new step, script or system change on that line, or new staff still learning. A slow rise is easy to miss day to day.

**New claims** (claims opened at the site for the line that day): 187 across the operation today against 184 on recent Tuesdays. Flagged: Central auto on 1 of the last 7 days; West home on 1 of the last 7 days. So what: A weather event or a catastrophe code; tell the adjusters' team leads before the backlog builds.

**Claims closed** (claims closed at the site for the line that day): 131 across the operation today against 131 on recent Tuesdays. No team was flagged on it in the last seven days, so nothing to do today.

**Open claims** (claims opened on or before the day and still open at its end): 715 across the operation today against 400 on recent Tuesdays. Flagged: Central home on 7 of the last 7 days. So what: New claims against closing capacity; borrow adjusters or approve overtime while it is still growing.
