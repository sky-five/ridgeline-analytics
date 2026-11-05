---
title: A/B test
---

A learning project on **simulated** data: new trial accounts are split 50/50 between the current onboarding and a
guided setup checklist. Success is activation, the first proposal sent within 14 days of signup. The checklist's true
effect is planted in the simulation (30% to 34%), so every step of the analysis can be checked against the truth.
Code and tests: [experiments/](https://github.com/sky-five/ridgeline-analytics/tree/main/experiments).

```sql s
select * from ridgeline.experiment_summary
```

## 1. Plan the size first

<BigValue data={s} value=sample_size_per_arm title="Accounts needed per arm" fmt=num0/>
<BigValue data={s} value=days_needed title="Days needed at 85 per arm per day"/>
<BigValue data={s} value=power_at_planned_size title="Power of the planned 28 days" fmt=pct0/>

To detect a 4-point lift on a 30% base rate with a two-sided test at alpha 0.05 and 80% power, each arm needs
<Value data={s} column=sample_size_per_arm fmt=num0/> accounts. The test was planned for 28 days and analysed once,
at the end.

## 2. The readout

<BigValue data={s} value=rate_control title="Control activation" fmt=pct1/>
<BigValue data={s} value=rate_treatment title="Checklist activation" fmt=pct1/>
<BigValue data={s} value=diff title="Difference (points)" fmt=pct1/>
<BigValue data={s} value=p_value title="p-value" fmt=num3/>

The checklist arm activated <Value data={s} column=diff fmt=pct1/> points more, with a 95% interval from
<Value data={s} column=ci_low fmt=pct1/> to <Value data={s} column=ci_high fmt=pct1/>. The interval contains the
planted 4-point effect, but it also contains zero, so this run is **not significant** at 0.05. That is what 84% power
means: about one run in six misses a real effect of this size. The honest call is "probably positive, not proven",
not a win and not a failure.

Running the same design <Value data={s} column=replay_runs fmt=num0/> times shows the method works as designed: it
found the effect in <Value data={s} column=replay_significant fmt=pct1/> of runs, and the 95% interval covered the
true lift in <Value data={s} column=replay_ci_covers fmt=pct1/>.

```sql funnel
select step, rate_control, rate_treatment from ridgeline.experiment_funnel
```

<DataTable data={funnel}>
  <Column id=step title="Funnel step (within 14 days)"/>
  <Column id=rate_control title="Control" fmt=pct1/>
  <Column id=rate_treatment title="Checklist" fmt=pct1/>
</DataTable>

## 3. Check the split before trusting the lift

A sample-ratio-mismatch check compares the observed split with the planned 50/50. On this run the split is fine
(p = <Value data={s} column=srm_p fmt=num2/>). The simulation also has a tracking bug on purpose: the new onboarding
fails to log a fifth of the treatment accounts that never activate. The arms then come out
<Value data={s} column=n_control fmt=num0/> vs <Value data={s} column=bug_n_treatment fmt=num0/>, the check alarms
(p = <Value data={s} column=bug_srm_p fmt=num6/>), and the broken data would have claimed a
<Value data={s} column=bug_diff fmt=pct1/>-point lift, about twice the truth.

## 4. Why not stop early?

```sql looks
select day, diff, ci_low, ci_high, p_value from ridgeline.experiment_looks order by day
```

<LineChart data={looks} x=day y={['diff', 'ci_low', 'ci_high']} yFmt=pct1 title="Running difference and 95% interval, by day of the test" colorPalette={['#C2410C', '#9CA3AF', '#9CA3AF']}/>

The difference swings a lot in the first days. Checking every day and stopping at the first p-value below 0.05 turns a 5%
false-positive rate into a much bigger one. In <Value data={s} column=aa_tests fmt=num0/> simulated A/A tests (both
arms identical, so every "win" is false), testing once at day 28 gave <Value data={s} column=fp_fixed fmt=pct1/> false
positives; testing daily and stopping at the first significant day gave <Value data={s} column=fp_peeking fmt=pct1/>.
