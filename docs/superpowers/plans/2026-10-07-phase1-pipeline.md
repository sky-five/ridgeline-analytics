# Ridgeline Phase 1: Simulator → dlt → dbt (DuckDB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic simulator of Ridgeline's six source systems, loaded incrementally by dlt into DuckDB, transformed by a tested dbt project into domain marts, with PR CI.

**Architecture:**
- `simulator/` builds a full deterministic history up to a horizon date, then serves an "as of" view through a paginated mock API with `updated_at` cursors.
- `pipelines/` holds one dlt source per system, writing to `raw_*` datasets.
- `dbt/` holds staging → intermediate → marts, with contracts, unit tests, freshness and singular tests.

**Tech Stack:** Python 3.12 (uv venv), numpy, pandas, dlt 1.31 (duckdb + snowflake extras), dbt-core 1.12, dbt-duckdb 1.11, dbt-utils, scikit-learn 1.9, pytest, ruff, sqlfluff 4.4 (dbt templater), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-07-ridgeline-analytics-design.md` (sections 3.1–3.4, 3.8 PR CI, 4, 5)

## Global Constraints

- All data is synthetic. Never use real company names, data or code. The fictional company is "Ridgeline".
- Python 3.12. Dependencies are pinned in `requirements.txt` to the versions installed on 2026-10-07: dlt==1.31.0, dbt-core==1.12.5, dbt-duckdb==1.11.0, dbt-snowflake==1.12.1, dbt-metricflow==0.15.0, duckdb==1.5.6, pandas==3.0.6, numpy==2.5.3, scikit-learn==1.9.1, pytest==9.1.1, ruff==0.16.10, sqlfluff==4.4.0, sqlfluff-templater-dbt==4.4.0.
- Determinism: `SEED = 20260101`. History starts `2024-01-01`. The horizon is `2027-12-31`. The same seed and as-of date must give byte-identical output.
- All timestamps are UTC and timezone-naive in the warehouse. Column suffix `_at` means timestamp and `_date` means date.
- Scale: about 8,000 accounts by 2026-10-07 and 2–4M events. A full simulate + load + build must finish in under 10 minutes on a laptop.
- dbt SQL must stay portable to Snowflake (Phase 2). Use `dbt.datediff`, `dbt.dateadd`, `dbt.date_trunc`, `dbt.safe_cast`, `dbt.type_*` and `dbt_utils.date_spine`. No DuckDB-only syntax in models: no `filter (where …)`, `::` casts, `group by all`, `date_diff`, `interval 60 day` or `last_day`.
- Prices (USD/month): essentials 249, scale 349. Add-ons: instant_estimator 149, ai_receptionist 99, sms 49. Measurement report: 19 on free, 13 on paid.
- Channels: google_ads, organic, facebook, referral, supplier_partner, trade_show.
- Regions: Southeast, Southwest, Midwest, Northeast, West, Canada. Crew sizes: 1, 2-5, 6-15, 16+.
- Planted patterns (spec 3.1):
  - Channel quality differs.
  - Week-1 proposal is the strongest upgrade signal.
  - Crew size affects plan and churn.
  - Storm season is Apr–Aug.
  - Lead contact under 5 min ≈ 2× close rate.
  - Measurement redos drive tickets and churn.
  - About 8% of contractor-lead stage timestamps are missing.
  - Churn reasons are written in the ticket text.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Re-running history.** The same as-of date run twice, or as-of D and then D+1, must not rewrite rows dated ≤ D. Otherwise nightly merges churn every row. Pinned by `test_history_stable_across_as_of` (Task 5) and `test_incremental_load_idempotent` (Task 7).
2. **Mutable records change state.** A subscription canceled or a ticket solved on D+1 must come back on the D+1 load with a new `updated_at`, and dlt must merge it, not duplicate it. Pinned by `test_next_day_updates_merge` (Task 7).
3. **Month-boundary MRR.** Subscriptions starting on the 29th–31st, and changes on the last day of a month, must land in the right month's movement. Pinned by the dbt unit test `mrr_movements_month_boundary` (Task 9).
4. **Empty pages.** An as-of date with zero new rows for a table must load cleanly, not fail. Pinned by `test_empty_increment` (Task 7).
5. **Missing timestamps.** About 8% of leads have null stage times. Speed-to-lead and benchmarks must exclude them, not count them as zero or crash. Pinned by the dbt unit test `contractor_leads_missing_contact` (Task 12).

---

## File Structure

```
ridgeline-analytics/
  pyproject.toml            # ruff + pytest config, package discovery
  requirements.txt
  .gitignore  .sqlfluff  .sqlfluffignore
  simulator/
    __init__.py
    config.py               # constants above (seed, dates, prices, channels…)
    rng.py                  # keyed RNG
    accounts.py             # account arrivals + latent traits
    lifecycle.py            # per-account: events, subscriptions, changes, invoices, measurement orders
    side_systems.py         # support tickets, CRM, ads spend, contractor leads
    text.py                 # ticket subject/body templates by theme
    world.py                # full history (cached) + as-of view
    api.py                  # MockApi: paginated, incremental
  pipelines/
    __init__.py
    sources.py              # dlt sources/resources
    run.py                  # CLI: python -m pipelines.run --as-of YYYY-MM-DD --destination duckdb
  dbt/
    dbt_project.yml  profiles.yml  packages.yml
    seeds/targets_monthly.csv
    models/staging/<system>/_sources.yml, stg_*.sql, _stg_models.yml
    models/intermediate/int_*.sql
    models/marts/{finance,growth,sales,customer_success,contractor_outcomes,ops}/*.sql + _models.yml
    tests/assert_mrr_reconciles_to_invoices.sql
  scripts/run_all.py        # simulate → load → dbt build, for local + CI
  tests/simulator/*.py  tests/pipelines/*.py
  .github/workflows/ci.yml
  warehouse/                # gitignored DuckDB file
```

---

### Task 1: Scaffold, config and keyed RNG

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `simulator/__init__.py`, `simulator/config.py`, `simulator/rng.py`
- Test: `tests/simulator/test_rng.py`

**Interfaces:**
- Produces:
  - `simulator.config` constants: `SEED: int`, `START_DATE: date`, `HORIZON_DATE: date`, `CHANNELS: dict[str, ChannelSpec]`, `REGIONS: dict[str, float]` (share), `CREW_SIZES: dict[str, CrewSpec]`, `PLAN_PRICES: dict[str, int]`, `ADDON_PRICES: dict[str, int]`, `REPORT_PRICE: dict[str, int]` (`{"free": 19, "paid": 13}`)
  - `ChannelSpec(share: float, conv_logit: float, monthly_cost_usd: float | None, cpc_usd: float | None)`
  - `CrewSpec(share: float, conv_logit: float, churn_mult: float, scale_plan_p: float)`
  - `simulator.rng.keyed_rng(*keys: str | int, seed: int = SEED) -> np.random.Generator`. It derives the stream from `np.random.SeedSequence([seed, *stable_hash(keys)])`, where `stable_hash` uses `hashlib.blake2b`, never Python `hash()`.

- [ ] **Step 1: Write failing tests**

```python
from simulator.rng import keyed_rng

def test_same_keys_same_stream():
    assert keyed_rng("acct", 7).random() == keyed_rng("acct", 7).random()

def test_different_keys_differ():
    assert keyed_rng("acct", 7).random() != keyed_rng("acct", 8).random()

def test_stable_across_processes():
    # pinned value: fails if someone swaps blake2b for hash()
    assert round(keyed_rng("acct", 1).random(), 12) == round(keyed_rng("acct", 1).random(), 12)
    import subprocess, sys
    out = subprocess.check_output([sys.executable, "-c",
        "from simulator.rng import keyed_rng; print(repr(keyed_rng('acct', 1).random()))"])
    assert float(out) == keyed_rng("acct", 1).random()
```

- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/simulator/test_rng.py -v`. Expected: FAIL (module not found).
- [ ] **Step 3:** Implement `config.py` with the values below, and `rng.py`.
  - Channels `(share, conv_logit, monthly_cost_usd, cpc_usd)`:
    - google_ads (0.30, 0.0, None, 4.2)
    - organic (0.20, 0.2, None, None)
    - facebook (0.18, -0.5, None, 1.6)
    - referral (0.12, 1.0, None, None)
    - supplier_partner (0.12, 0.6, 9000, None)
    - trade_show (0.08, 0.3, 14000, None)
  - Crew sizes `(share, conv_logit, churn_mult, scale_plan_p)`:
    - "1" (0.35, -0.4, 1.3, 0.05)
    - "2-5" (0.40, 0.0, 1.0, 0.20)
    - "6-15" (0.18, 0.4, 0.8, 0.70)
    - "16+" (0.07, 0.6, 0.6, 0.90)
  - Region shares: Southeast .28, Southwest .22, Midwest .18, Northeast .14, West .10, Canada .08.
  - `pyproject.toml`: ruff (line-length 110, target py312) and pytest `testpaths=["tests"]`, `pythonpath=["."]`.
  - `.gitignore`: `.venv/ warehouse/ .cache/ dbt/target/ dbt/dbt_packages/ dbt/logs/ __pycache__/ .dlt/secrets.toml`.
- [ ] **Step 4:** Run the tests. Expected: 3 passed.
- [ ] **Step 5:** Commit `feat(simulator): config and keyed rng`.

---

### Task 2: Account arrivals

**Files:**
- Create: `simulator/accounts.py`
- Test: `tests/simulator/test_accounts.py`

**Interfaces:**
- Consumes: `keyed_rng`, config.
- Produces: `build_accounts(seed: int = SEED) -> pd.DataFrame` with one row per account from START_DATE to HORIZON_DATE.
  - Columns: `account_id` (str `"ACC-000001"`, ordered by signup), `company_name` (str), `signup_at` (datetime64), `channel`, `campaign_id` (str or None; `"{channel}-{yyyymm}"` for google_ads/facebook), `region`, `crew_size`, `intent` (float latent, N(0,1)).
  - `intent` is internal. The API layer drops it (Task 6).

- [ ] **Step 1: Write failing tests**

```python
import pandas as pd
from simulator.accounts import build_accounts

def test_accounts_volume_and_season():
    a = build_accounts()
    to_date = a[a.signup_at < "2026-10-08"]
    assert 7000 <= len(to_date) <= 9000
    m = to_date.signup_at.dt.month
    per_day_storm = (m.between(4, 8)).sum() / 5
    per_day_other = (~m.between(4, 8)).sum() / 7
    assert per_day_storm > 1.3 * per_day_other

def test_ids_unique_and_sorted():
    a = build_accounts()
    assert a.account_id.is_unique and a.signup_at.is_monotonic_increasing

def test_channel_shares_close_to_config():
    a = build_accounts()
    assert abs((a.channel == "google_ads").mean() - 0.30) < 0.02
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - Daily arrivals are Poisson with `λ(d) = 5.0 × growth(d) × season(d)`.
    - `growth` is linear from 1.0 at START_DATE to 2.2 at HORIZON_DATE.
    - `season` is 1.6 for Apr–Aug, else 1.0.
  - Signup hour is uniform 07:00–20:00. Use `keyed_rng("arrivals")` for counts and `keyed_rng("account", i)` for each account's traits.
  - `company_name` = `f"{adjective} {noun} Roofing"` from fixed 40-word lists, seeded per account.
- [ ] **Step 4:** Run. Expected: 3 passed.
- [ ] **Step 5:** Commit `feat(simulator): account arrivals`.

---

### Task 3: Account lifecycle (product, billing, measurements)

**Files:**
- Create: `simulator/lifecycle.py`
- Test: `tests/simulator/test_lifecycle.py`

**Interfaces:**
- Consumes: one row of `build_accounts()` (as a namedtuple) and `keyed_rng("life", account_id)`.
- Produces: `simulate_account(acct) -> AccountHistory`, a dataclass of lists of dicts:
  - `events`: `event_id, account_id, event_type, occurred_at, properties` (dict; `{"value_usd": float}` on proposal_sent and proposal_signed)
  - `subscription`: one dict or None: `subscription_id, account_id, plan, started_at, canceled_at, cancel_reason`
  - `subscription_changes`: `change_id, subscription_id, account_id, changed_at, change_type ∈ {new, upgrade, downgrade, addon_added, addon_removed, cancel, reactivate}, plan_after, addons_after (comma-sorted str), mrr_before, mrr_after`
  - `invoices`: `invoice_id, account_id, subscription_id, period_start_date, issued_at, amount_usd, paid_at, line_type ∈ {subscription, measurement}`
  - `measurement_orders`: `order_id, account_id, ordered_at, delivered_at, tier ∈ {24h, 6h, 2h}, price_usd, roof_type ∈ {gable, hip, complex, flat}, redo_requested_at (or None), redo_reason (or None)`
- Ids are deterministic: `f"{prefix}-{account_id[4:]}-{n:05d}"`.

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
from simulator.accounts import build_accounts
from simulator.lifecycle import simulate_account

def _sample(n=1500):
    a = build_accounts()
    a = a[a.signup_at < "2026-06-01"].sample(n, random_state=1)
    return [simulate_account(r) for r in a.itertuples(index=False)]

def test_week1_proposal_lifts_conversion():
    hs = _sample()
    def paid60(h):
        s = h.subscription
        return s is not None and (s["started_at"] - h.signup_at).days < 60
    wk1 = [paid60(h) for h in hs if h.proposal_wk1]
    rest = [paid60(h) for h in hs if not h.proposal_wk1]
    assert np.mean(wk1) > 5 * np.mean(rest)
    assert 0.10 <= np.mean([paid60(h) for h in hs]) <= 0.20

def test_mrr_chain_is_consistent():
    for h in _sample(300):
        prev = 0
        for c in sorted(h.subscription_changes, key=lambda c: c["changed_at"]):
            assert c["mrr_before"] == prev
            prev = c["mrr_after"]

def test_invoices_match_mrr_each_month():
    # every subscription invoice amount equals mrr in force on period_start_date
    ...  # assert for each invoice: amount == mrr_after of last change <= period_start

def test_redos_raise_churn():
    hs = [h for h in _sample(2500) if h.subscription]
    redo = [h.subscription["canceled_at"] is not None for h in hs if any(o["redo_requested_at"] for o in h.measurement_orders)]
    clean = [h.subscription["canceled_at"] is not None for h in hs if not any(o["redo_requested_at"] for o in h.measurement_orders)]
    assert np.mean(redo) > 1.3 * np.mean(clean)
```

  (`AccountHistory` also exposes `signup_at` and `proposal_wk1: bool` for tests and Task 4.)

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `simulate_account`.
  - **First 14 days:**
    - `engaged ~ Bernoulli(sigmoid(-0.3 + intent + 0.5*ch.conv_logit))`
    - measurements: Poisson 2.2 if engaged, else 0.4
    - `proposal_wk1 ~ engaged and Bernoulli(sigmoid(-0.4 + 0.8*intent + 0.3*crew.conv_logit))`
    - proposals = Poisson(1.5)+1 if wk1, else Poisson(0.5) if engaged, else 0
    - signed = Binomial(proposals, 0.25)
    - logins: Poisson 6 if engaged, else 1.5
  - **Conversion:** `logit = -3.1 + 0.9*intent + ch.conv_logit + crew.conv_logit + 1.6*proposal_wk1 + 0.25*min(meas,6) + 0.5*(signed>0)`.
    - Paid lag = gamma(2, 12 if wk1 else 25) + 3 days.
    - Plan = scale with probability `crew.scale_plan_p`, else essentials.
  - **Monthly loop from start until cancel or HORIZON:**
    - `p_churn = 0.045 × crew.churn_mult × (1.8 if a redo happened in the prior 60 days else 1)`
    - 1.5% upgrade (essentials→scale)
    - 0.8% downgrade
    - addon_added 3%/mo up to 2 add-ons; addon_removed 1%/mo
    - Canceled accounts reactivate with 6%/mo for 6 months.
    - `cancel_reason` is the theme of the account's most recent ticket if one exists in the 90 days before cancel (Task 4 sets this via a callback), else `"price"` or `"no_longer_needed"`.
  - **Invoices:**
    - One subscription invoice on each month anniversary while active, amount = MRR in force. `paid_at = issued_at + U(0,5)` days, and 3% stay unpaid for 30 days.
    - One measurement invoice per order.
  - **Weekly activity after day 14:**
    - Paid: login 5, measurement 2.5, proposal 2, job_created 1.2, invoice_paid 0.8.
    - Free: active ~ exp(40d), then login 1, measurement 0.4, proposal 0.15.
  - **Measurement orders:**
    - Redo probability is 4% base: ×2.5 for complex roofs and ×1.8 in Canada.
    - Tier on paid accounts: 2h 30%, 6h 40%, 24h 30%. Free accounts are 24h only.
- [ ] **Step 4:** Run. Expected: 4 passed.
- [ ] **Step 5:** Commit `feat(simulator): account lifecycle`.

---

### Task 4: Side systems (support, CRM, ads, contractor leads)

**Files:**
- Create: `simulator/side_systems.py`, `simulator/text.py`
- Modify: `simulator/lifecycle.py` (the churn reason uses the ticket theme)
- Test: `tests/simulator/test_side_systems.py`

**Interfaces:**
- Consumes: `AccountHistory` (Task 3).
- Produces:
  - `simulate_support(h: AccountHistory) -> list[dict]`, tickets with: `ticket_id, account_id, created_at, first_reply_at, solved_at, priority ∈ {low, normal, high, urgent}, channel ∈ {email, chat, phone}, subject, body, true_theme`
    - `true_theme ∈ {measurement_accuracy, billing_price, missing_feature, how_to, bug_outage, integration}`
    - `true_theme` stays internal; the API drops it, and Phase 2 evaluation uses it.
  - `simulate_crm(h) -> tuple[list[dict], list[dict]]`:
    - deals: `deal_id, account_id, owner_rep, created_at, stage ∈ {open, won, lost}, closed_at, amount_usd`
    - calls: `call_id, account_id, rep, called_at, outcome ∈ {connected, voicemail, no_answer, demo_booked}, duration_s`
  - `simulate_leads(h) -> list[dict]`, the contractor's homeowner leads: `lead_id, account_id, source ∈ {instant_estimator, google_lsa, referral, door_knocking, facebook, home_show}, created_at, first_contact_at, inspection_at, proposal_sent_at, closed_at, outcome ∈ {won, lost_price, lost_competitor, lost_no_decision, unqualified, no_response}, proposal_value_usd`
  - `simulate_ad_spend(seed) -> list[dict]`: `spend_date, channel, campaign_id, spend_usd, impressions, clicks`
  - `text.render_ticket(theme: str, rng) -> tuple[str, str]` (subject, body)
- Reps are `["Avery", "Jordan", "Riley", "Casey", "Morgan", "Quinn"]`.

- [ ] **Step 1: Write failing tests**

```python
def test_fast_contact_doubles_close_rate(): ...
    # leads with (first_contact_at - created_at) < 5 min: won/closed >= 1.8x those 5min-24h
def test_missing_stage_timestamps_about_8pct(): ...
    # share of leads with first_contact_at null but outcome not in (no_response): 0.06..0.10
def test_redo_accounts_file_measurement_tickets(): ...
    # accounts with a redo have measurement_accuracy ticket within 7 days >= 70%
def test_churn_reason_matches_recent_ticket_theme(): ...
    # canceled subs with a ticket in prior 90d: cancel_reason == that ticket's true_theme
def test_ad_spend_only_paid_channels(): ...
    # set(channels with spend) == {google_ads, facebook, supplier_partner, trade_show}
def test_ticket_text_mentions_theme_keywords(): ...
    # measurement_accuracy bodies contain one of ("pitch", "measurement", "imagery", "squares")
```

  The implementer writes these bodies from the comments, using `_sample()` from Task 3's tests, moved to `tests/simulator/conftest.py` as a fixture.

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
  - **Leads (paid contractors only):** 15/month × crew multiplier {1: 0.5, 2-5: 1, 6-15: 2, 16+: 4}, with storm season ×1.8.
    - Contact delay is lognormal around the source median (minutes): instant_estimator 6, google_lsa 25, referral 60, door_knocking 1, facebook 90, home_show 600, σ = 1.1.
    - Win logit includes `+0.7 × (delay < 5 min)`.
    - Null 8% of first_contact_at and 8% of inspection_at independently.
  - **Support:**
    - Base rate is 0.3 tickets/account-month while active.
    - Every redo spawns a measurement_accuracy ticket with p = 0.8 within 0–7 days.
    - Theme mix otherwise: how_to .35, billing_price .2, missing_feature .2, bug_outage .15, integration .1.
    - `text.py` holds 4 subject and 6 body templates per theme, with slot filling (address, pitch values, invoice numbers).
  - **CRM:**
    - Reps call 35% of free accounts 2–30 days after signup. High activity raises demo_booked.
    - A deal opens on demo_booked. It is won if the account converts within 45 days, else lost.
  - **Ads:**
    - google_ads/facebook spend per day = attributed signups that day × cpc × clicks-per-signup (25 and 60) × U(0.85, 1.15).
    - supplier_partner and trade_show: monthly cost spread evenly over the month's days.
- [ ] **Step 4:** Run. Expected: 6 passed.
- [ ] **Step 5:** Commit `feat(simulator): support, crm, ads, contractor leads`.

---

### Task 5: World (full history cache + as-of view)

**Files:**
- Create: `simulator/world.py`
- Test: `tests/simulator/test_world.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `TABLES: dict[str, TableSpec]` for 11 tables: `accounts, events, subscriptions, subscription_changes, invoices, measurement_orders, support_tickets, crm_deals, crm_calls, ad_spend, contractor_leads`.
  - `TableSpec(system: str, primary_key: str, mutable: bool, time_cols: list[str], internal_cols: list[str])`
    - system ∈ {app_db, product_events, crm, support, ads, contractor_ops}
  - `build_full_history(seed: int = SEED) -> dict[str, pd.DataFrame]`, cached as parquet in `.cache/full-{seed}-{HORIZON_DATE}/`. The cache key includes a `SIM_VERSION` int in config; bump it when simulator logic changes.
  - `world_as_of(as_of: date, seed: int = SEED) -> dict[str, pd.DataFrame]`. Rules:
    - Keep rows whose creation time is ≤ as_of 23:59:59.
    - In those rows, null any `time_cols` value after as_of. Recompute `status` fields (subscription: active/canceled; ticket: open/solved; deal: stage open if closed_at nulled; lead: outcome `"open"` if closed_at nulled; invoice: `"open"` if paid_at nulled).
    - Set `updated_at` = max of the non-null `time_cols`.
    - Drop `internal_cols` (`intent`, `true_theme`).

- [ ] **Step 1: Write failing tests**

```python
from datetime import date
from simulator.world import world_as_of

def test_history_stable_across_as_of():
    d0, d1 = world_as_of(date(2026, 9, 1)), world_as_of(date(2026, 9, 2))
    for name, df0 in d0.items():
        df1 = d1[name]
        # rows untouched since D0 must be identical in both views
        old = df1[df1.updated_at <= "2026-09-01 23:59:59"]
        merged = old.merge(df0, how="left", indicator=True)
        assert (merged._merge == "both").all(), name

def test_mutable_rows_change_state():
    d0, d1 = world_as_of(date(2026, 9, 1)), world_as_of(date(2026, 9, 30))
    s0 = d0["subscriptions"].set_index("subscription_id")
    s1 = d1["subscriptions"].set_index("subscription_id")
    flipped = (s0.status == "active") & (s1.loc[s0.index].status == "canceled")
    assert flipped.sum() > 0
    assert (s1.loc[flipped[flipped].index].updated_at > "2026-09-01 23:59:59").all()

def test_no_future_timestamps():
    w = world_as_of(date(2026, 3, 15))
    for df in w.values():
        for c in df.select_dtypes("datetime").columns:
            assert (df[c].dropna() <= "2026-03-15 23:59:59").all()

def test_internal_columns_dropped():
    w = world_as_of(date(2026, 3, 15))
    assert "intent" not in w["accounts"] and "true_theme" not in w["support_tickets"]
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Each table carries an internal `_created_at` column used for the as-of filter, dropped before return.
- [ ] **Step 4:** Run. Expected: 4 passed. Also run `time python -c "from simulator.world import build_full_history; build_full_history()"` cold. Expected: under 4 minutes.
- [ ] **Step 5:** Commit `feat(simulator): world history and as-of view`.

---

### Task 6: Mock API

**Files:**
- Create: `simulator/api.py`
- Test: `tests/simulator/test_api.py`

**Interfaces:**
- Consumes: `world_as_of`, `TABLES`.
- Produces: `MockApi(as_of: date, seed: int = SEED)` with method `fetch(table: str, updated_since: datetime | None = None, page_size: int = 5000) -> Iterator[list[dict]]`.
  - Rows are ordered by `(updated_at, primary_key)`, with strict `updated_at > updated_since`.
  - Timestamps are ISO-8601 strings with no timezone. NaN becomes None. `properties` is a dict.
  - An unknown table raises `KeyError`.

- [ ] **Step 1: Write failing tests**

```python
def test_pages_cover_all_rows_once(): ...      # sum(len(p)) == len(world table), ids unique
def test_updated_since_filters_strictly(): ...  # every row updated_at > cursor
def test_empty_page_stream_when_nothing_new(): ...  # cursor = max(updated_at) -> list(fetch) == []
def test_json_safe(): ...                       # json.dumps(page) works; no NaN
```

- [ ] **Step 2–4:** Run (FAIL), implement, run (4 passed).
- [ ] **Step 5:** Commit `feat(simulator): paginated incremental mock api`.

---

### Task 7: dlt sources and load CLI

**Files:**
- Create: `pipelines/__init__.py`, `pipelines/sources.py`, `pipelines/run.py`
- Test: `tests/pipelines/test_load.py`

**Interfaces:**
- Consumes: `MockApi`, `TABLES`.
- Produces:
  - `ridgeline_source(system: str, api: MockApi) -> DltSource`. One resource per table of that system, with:
    - `primary_key = spec.primary_key`
    - `write_disposition = "merge"` if `spec.mutable`, else `"append"`
    - `dlt.sources.incremental("updated_at", initial_value="1970-01-01T00:00:00")`
    - `schema_contract = {"tables": "evolve", "columns": "evolve", "data_type": "freeze"}`
  - `load(as_of: date, destination: str = "duckdb", duckdb_path: str = "warehouse/ridgeline.duckdb", pipelines_dir: str | None = None) -> dict[str, int]` (rows loaded per table). It runs 6 pipelines named `ridgeline_{system}` into datasets `raw_{system}`.
  - CLI: `python -m pipelines.run --as-of 2026-10-07 [--destination duckdb|snowflake]`. Snowflake credentials come from dlt secrets/env in Phase 2.

- [ ] **Step 1: Write failing tests** (use `tmp_path` for the DuckDB file and `pipelines_dir`)

```python
def test_first_load_counts_match_world(tmp_path): ...
    # rows in raw_app_db.accounts == len(world_as_of(D)["accounts"])
def test_incremental_load_idempotent(tmp_path): ...
    # load(D) twice -> counts unchanged
def test_next_day_updates_merge(tmp_path): ...
    # load(D) then load(D+29): subscriptions count == world(D+29) count (no dup ids),
    # and a sub canceled in between has status 'canceled'
def test_empty_increment(tmp_path): ...
    # load(D) then load(D) again returns 0 rows for every table, no exception
```

  Keep the tests fast: use D = 2024-03-31 and D+29 = 2024-04-29 (early history, small).

- [ ] **Step 2–4:** Run (FAIL), implement, run (4 passed).
- [ ] **Step 5:** Commit `feat(pipelines): dlt incremental sources`.

---

### Task 8: dbt project, sources, staging, lint

**Files:**
- Create:
  - `dbt/dbt_project.yml` (name `ridgeline`; staging = view, intermediate = table, marts = table; var `as_of_date` default `'2026-10-07'`)
  - `dbt/profiles.yml` (target `duckdb`: path `../warehouse/ridgeline.duckdb`, threads 4)
  - `dbt/packages.yml` (dbt-labs/dbt_utils, pinned to the latest 1.x on install)
  - `dbt/models/staging/<system>/_sources.yml`
  - `dbt/models/staging/<system>/stg_<system>__<table>.sql` (11 files)
  - `dbt/models/staging/_stg_models.yml`
  - `.sqlfluff`, `.sqlfluffignore`
- Test: `dbt build --select staging` plus `dbt source freshness`.

**Interfaces:**
- Consumes: the `raw_*` datasets from Task 7.
- Produces: staging models named `stg_<system>__<table>`, e.g. `stg_app_db__subscriptions`.
  - Columns: the source columns cast with `dbt.type_*`, ids as strings, and timestamps cast to timestamp.
  - `properties` is parsed in `stg_product_events__events` into `value_usd`.
  - dlt `_dlt_*` columns are dropped.
- Sources declare `loaded_at_field: updated_at` and `freshness: {warn_after: {count: 36, period: hour}, error_after: {count: 72, period: hour}}`. Freshness is measured against the as-of clock, so `ad_spend` uses `spend_date`.

- [ ] **Step 1:** Write `_stg_models.yml` with `unique` + `not_null` on every primary key, `accepted_values` on every enum listed in Tasks 3–4, and `relationships` from each `account_id` to `stg_app_db__accounts`. These are the failing tests.
- [ ] **Step 2:** Run `python scripts/run_all.py --as-of 2026-10-07 --skip-dbt` (load only), then `cd dbt && dbt deps && dbt build --select staging`. Expected: FAIL (models missing).
- [ ] **Step 3:** Implement the 11 staging models, and `.sqlfluff` (templater dbt, dialect duckdb, max line 110, capitalisation lower).
- [ ] **Step 4:** Run `dbt build --select staging` (expected: all pass) and `sqlfluff lint dbt/models` (expected: 0 violations).
- [ ] **Step 5:** Commit `feat(dbt): sources, staging, lint`.

(`scripts/run_all.py` is created here with flags `--as-of`, `--skip-load`, `--skip-dbt`, `--destination`. It calls `pipelines.run.load`, then `dbt deps` + `dbt build --vars '{as_of_date: …}'` via `subprocess` with `cwd=dbt`.)

---

### Task 9: Finance marts (MRR) with unit and reconciliation tests

**Files:**
- Create:
  - `dbt/models/intermediate/int_mrr_movements.sql`
  - `dbt/models/marts/finance/fct_mrr_movements.sql`
  - `dbt/models/marts/finance/fct_mrr_daily.sql`
  - `dbt/models/marts/finance/dim_accounts.sql`
  - `dbt/models/marts/finance/_finance_models.yml`
  - `dbt/tests/assert_mrr_reconciles_to_invoices.sql`
  - `dbt/seeds/targets_monthly.csv`

**Interfaces:**
- Produces:
  - `fct_mrr_movements`: grain change_id.
    - Columns: `change_id, account_id, changed_at, movement_date, movement_month, movement_type ∈ {new, expansion, contraction, churn, reactivation}, mrr_delta`.
    - Mapping: new = first non-zero from 0. Reactivation = from 0 after a cancel. Churn = to 0. Expansion = up while > 0 (upgrade, addon_added). Contraction = down while > 0.
  - `fct_mrr_daily`: grain date_day, from START to the `as_of_date` var. Columns: `date_day, mrr, paying_accounts, new_mrr, expansion_mrr, contraction_mrr, churned_mrr, reactivation_mrr, net_new_mrr`.
  - `dim_accounts`: grain account_id. Columns: `account_id, company_name, signup_at, signup_month, channel, campaign_id, region, crew_size, first_paid_at, current_plan, current_addons, current_mrr, is_paying, churned_at, cancel_reason`.
  - `targets_monthly.csv`: `month, metric, target` for metrics `mrr, signups, free_to_paid_60d, nrr` from 2025-01 to 2026-12. Targets = actual trend × 1.05, computed once with a one-off query and committed.

- [ ] **Step 1:** Write the failing tests in `_finance_models.yml`:
  - `contract: {enforced: true}` with full column types on all 3 models.
  - PK tests.
  - Unit test `mrr_movements_types`: given rows for 0→249, 249→349, 349→299, 299→0, 0→249, expect new, expansion, contraction, churn, reactivation.
  - Unit test `mrr_movements_month_boundary`: changes at `2025-01-31 23:59:00` and `2025-02-01 00:00:00` get `movement_month` 2025-01-01 and 2025-02-01.
  - Singular test: for each month, `sum(mrr on day 1 of month)` vs `sum(subscription invoice amount_usd with period_start_date in that month)`. Fail rows where `abs(diff) > 1.0 × paying_accounts` (anniversary billing timing tolerance).
- [ ] **Step 2:** Run `dbt build --select +fct_mrr_daily +dim_accounts`. Expected: FAIL.
- [ ] **Step 3:** Implement. `fct_mrr_daily` uses `dbt_utils.date_spine` and a running sum of `mrr_delta`.
- [ ] **Step 4:** Run. Expected: all pass. Then sanity query: `select mrr from fct_mrr_daily order by date_day desc limit 1`. Expect it between $200k and $400k.
- [ ] **Step 5:** Commit `feat(dbt): finance marts with unit and reconciliation tests`.

---

### Task 10: Growth marts

**Files:**
- Create:
  - `dbt/models/intermediate/int_account_first14d.sql`
  - `dbt/models/intermediate/int_account_milestones.sql`
  - `dbt/models/marts/growth/fct_account_funnel.sql`
  - `dbt/models/marts/growth/fct_marketing_channel_daily.sql`
  - `dbt/models/marts/growth/fct_cohort_retention.sql`
  - `dbt/models/marts/growth/_growth_models.yml`

**Interfaces:**
- Produces:
  - `fct_account_funnel` (account_id):
    - Columns: `signup_at, signup_month, channel, region, crew_size, logins_14d, measurements_14d, proposals_14d, signed_14d, active_days_14d, proposal_wk1, first_measurement_at, first_proposal_at, first_signed_at, first_paid_at, is_activated` (proposal within 14d), `measured_60d, proposed_60d, signed_60d, is_paid_60d` (paid < 60 days after signup), `is_mature` (signup ≤ as_of − 60d).
  - `fct_marketing_channel_daily` (date_day, channel): `spend_usd, signups, paid_60d_from_cohort, cac_usd` (spend ÷ paid conversions over trailing 90 days by signup date).
  - `fct_cohort_retention` (cohort_month, months_since_start): `cohort_accounts, retained_accounts, cohort_start_mrr, retained_mrr, logo_retention, nrr, grr`. Cohort = first_paid month.

- [ ] **Step 1:** Write failing tests in YAML:
  - contracts and PK tests
  - unit test `funnel_paid_60d_boundary`: paid at signup + 59d 23h → true; signup + 60d → false
  - `dbt_utils.expression_is_true`: `logo_retention between 0 and 1`, `grr <= 1`
- [ ] **Step 2–4:** Run (FAIL), implement, run (pass). Sanity check: activated accounts convert ≥ 5× non-activated.
- [ ] **Step 5:** Commit `feat(dbt): growth marts`.

---

### Task 11: Sales marts (PQA score + rep follow-up)

**Files:**
- Create:
  - `dbt/models/marts/sales/fct_pqa_scores.py`
  - `dbt/models/marts/sales/fct_rep_followups.sql`
  - `dbt/models/marts/sales/_sales_models.yml`

**Interfaces:**
- Consumes: `fct_account_funnel`, `stg_crm__calls`.
- Produces:
  - `fct_pqa_scores` (account_id): `score_model, score_points, decile, top_reasons, split ∈ {train, test, not_labelled}, is_paid_60d, call_list_eligible`.
    - Same method as the old Roofline demo: logistic regression on log1p counts + channel/crew dummies.
    - Train = mature accounts with signup < 2026-01-01. Test = mature accounts with signup ≥ 2026-01-01.
    - Points: proposal_wk1 40, measurements 5 each (max 25), signed 15, referral/supplier 10, crew 6+ 10, capped at 100.
    - Eligible = not paid and 14–45 days since signup, relative to the `as_of_date` var (read with `dbt.config.get` for vars).
  - `fct_rep_followups` (account_id, eligible accounts in decile 10 only): `became_eligible_at` (signup + 14d), `first_call_at, called_within_3d, rep, converted_60d`.
- Contracts are not supported on Python models. Use PK and `accepted_values` tests instead.

- [ ] **Step 1:** Failing tests: PK tests; `accepted_values` on split; a singular test `assert_pqa_top_decile_lift.sql` that fails if test-split top-decile conversion < 2.5× the test-split average.
- [ ] **Step 2–4:** Run (FAIL), implement, run (pass).
- [ ] **Step 5:** Commit `feat(dbt): pqa score and rep follow-ups`.

---

### Task 12: Customer success, contractor outcomes and ops marts

**Files:**
- Create:
  - `dbt/models/marts/customer_success/fct_support_tickets.sql`
  - `dbt/models/marts/customer_success/fct_account_health.sql`
  - `dbt/models/marts/contractor_outcomes/fct_contractor_leads.sql`
  - `dbt/models/marts/contractor_outcomes/fct_contractor_benchmarks.sql`
  - `dbt/models/marts/ops/fct_measurement_quality.sql`
  - one `_models.yml` per folder

**Interfaces:**
- Produces:
  - `fct_support_tickets` (ticket_id): `account_id, created_at, first_reply_minutes, resolution_hours, priority, channel, subject, body, status, is_paying_at_creation`. The `churn_theme` column is added in Phase 2 by Cortex or a seed.
  - `fct_account_health` (account_id, paying accounts):
    - Columns: `logins_30d, proposals_30d, tickets_90d, redo_90d, mrr, health_score` (0–100 rule-based), `risk_band ∈ {healthy, watch, at_risk}`.
    - Rule: start at 100. −30 if logins_30d < 4, −20 if proposals_30d = 0, −20 if redo_90d > 0, −10 per ticket over 2 in 90 days. Floor 0. at_risk < 40, watch < 70.
  - `fct_contractor_leads` (lead_id):
    - Columns: `account_id, source, created_at, created_month, first_contact_at, inspection_at, proposal_sent_at, closed_at, outcome, outcome_group ∈ {won, lost, unqualified, no_response, open}, proposal_value_usd`.
    - `speed_to_lead_min` is null when first_contact_at is null.
    - `speed_bucket ∈ {missing, lt_5m, 5_60m, 1_24h, gt_1d}`.
    - Also `missing_contact_ts, missing_inspection_ts`.
  - `fct_contractor_benchmarks` (account_id, month): `crew_size, region, leads, closed, won, close_rate, median_speed_min, close_rate_pctile, speed_pctile` (percentile rank within crew_size peers that month; null when leads < 5).
  - `fct_measurement_quality` (order_id): `account_id, ordered_at, region, roof_type, tier, turnaround_hours, is_redo, redo_reason`.

- [ ] **Step 1:** Write failing tests:
  - contracts and PK tests, plus accepted_values on every enum
  - unit test `contractor_leads_missing_contact`: a lead with null first_contact_at gets speed_to_lead_min null and speed_bucket `missing`, and a won lead with null contact still counts as won
  - unit test `health_score_rules`: three crafted accounts expect 100, 50 and 0
  - expression test: close_rate between 0 and 1
- [ ] **Step 2–4:** Run (FAIL), implement, run (pass). Sanity check: lt_5m close rate ≥ 1.8× the 5_60m close rate.
- [ ] **Step 5:** Commit `feat(dbt): cs, contractor outcomes, ops marts`.

---

### Task 13: End-to-end runner and PR CI

**Files:**
- Modify: `scripts/run_all.py` (from Task 8) to add a `--fresh` flag that deletes `warehouse/ridgeline.duckdb` and the dlt state first.
- Create: `.github/workflows/ci.yml`, `tests/test_end_to_end.py` (marked `@pytest.mark.e2e`, skipped unless `RUN_E2E=1`)

**Interfaces:**
- Produces a CI job `ci` on `pull_request` and `push` to main, running on ubuntu-latest with Python 3.12 via `astral-sh/setup-uv`:
  1. `uv pip install -r requirements.txt`
  2. `ruff check .`
  3. `pytest -m "not e2e"`
  4. `python scripts/run_all.py --fresh --as-of 2026-10-07`
  5. `cd dbt && dbt source freshness --vars '{as_of_date: "2026-10-07"}'`
  6. `sqlfluff lint dbt/models`
  7. Upload `dbt/target/{manifest.json,run_results.json,sources.json}` as the artifact `dbt-artifacts`.
- The simulator cache `.cache/` is cached with `actions/cache`, keyed on a hash of `simulator/**` and the SIM_VERSION.

- [ ] **Step 1:** Write `test_end_to_end.py`. It runs `run_all.py --fresh --as-of 2024-06-30` in a temp dir copy, then asserts `dbt/target/run_results.json` has no `error` or `fail` statuses.
- [ ] **Step 2:** Run `RUN_E2E=1 pytest tests/test_end_to_end.py -v`. Expected: PASS. Before Tasks 8–12 it would fail.
- [ ] **Step 3:** Write `ci.yml`. Validate it with `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`.
- [ ] **Step 4:** Run the full local equivalent: `python scripts/run_all.py --fresh --as-of 2026-10-07`. Expected: dbt `Done. PASS=… ERROR=0`, total runtime under 10 minutes. Record the runtime in the commit message.
- [ ] **Step 5:** Commit `ci: end-to-end runner and PR workflow`.

---

### Task 14: Phase 1 README

**Files:**
- Create: `README.md`

- [ ] **Step 1:** Write the README with these sections:
  - What Ridgeline is: synthetic, with a one-line disclaimer.
  - Architecture (the ASCII diagram from the spec).
  - How to run (uv venv, `python scripts/run_all.py --fresh`).
  - Repo map.
  - Data model: a table of marts with grain and purpose.
  - Testing approach: unit, contract, singular and freshness tests, with counts from `run_results.json`.
  - Planted patterns.
  - Roadmap: Phases 2–5.
  - Built-with-Claude-Code note.
- [ ] **Step 2:** Verify every command in the README by running it, and every count against `run_results.json`.
- [ ] **Step 3:** Commit `docs: phase 1 readme`.
