# Ridgeline Analytics: design spec

Date: 2026-10-07 · Owner: Shubham (Sky) Yadav · Status: draft for review

## 1. Purpose

A public portfolio project that proves, to data hiring managers (Roofr first), that Sky can build and run a modern analytics stack end to end, at production quality, and learns new tools fast.

**Success means:**
- A hiring manager can open one link and, within 2 minutes, see a finished internal analytics portal, try the AI analyst, and find the code, lineage and test results.
- The stack matches Roofr's job posts: Snowflake, dbt, a semantic layer, a code-based BI tool, and Claude/Cortex.
- It runs every night on its own, and its checks pass on every change.
- Nothing in it is real company data. Everything is synthetic, and the README says so.

**Non-goals:**
- No real Roofr or StorageVault data or code.
- No Dagster or Airflow. GitHub Actions does the scheduling.
- No custom web front end beyond Evidence and one small API.

## 2. The story

"Ridgeline" is a fictional SaaS for roofing contractors. It offers a free plan and paid plans (Essentials, Scale), pay-per-use measurement reports, proposals and e-signatures, job tracking, and add-ons (Instant Estimator, AI Receptionist, SMS). The portal is Ridgeline's internal analytics site, as its data team would run it.

## 3. Architecture

```
simulator/ ──► dlt pipelines ──► warehouse RAW ──► dbt ──► marts + metrics ──► Evidence site (static)
                                 (Snowflake | DuckDB)                     └──► AI analyst API ──► Claude
GitHub Actions: PR checks · nightly run · deploy
```

### 3.1 Simulator (`simulator/`)
- A deterministic Python package (fixed seed) that models these source systems:
  - **App DB:** accounts, users, subscriptions, plan changes, invoices, measurement orders
  - **Product events:** login, measurement_ordered, proposal_sent, proposal_signed, job_created, invoice_paid
  - **CRM** (HubSpot-like): contacts, deals, call logs, rep owner
  - **Support** (Zendesk-like): tickets with free-text subject and body, priority, status
  - **Ads:** daily spend by channel and campaign
  - **Contractor ops:** each contractor's homeowner leads, inspections, proposals, jobs, with stage timestamps
- **Time window:** simulated history from 2024-01-01 to "today". Each nightly run adds the new day, so freshness checks and the scorecard are real.
- **Interface:** a mock API client per system, with pagination and `updated_at` cursors, so dlt loads incrementally like a real SaaS API.
- **Planted patterns** (documented in the README):
  - Channel quality differs by channel.
  - Week-1 proposal is the strongest upgrade signal.
  - Crew size affects plan and churn.
  - Storm season (Apr–Aug).
  - Responding to a lead in under 5 minutes doubles the close rate.
  - Measurement redos drive tickets and churn.
  - About 8% of stage timestamps are missing.
  - Churn reasons are written in the ticket text.
- **Scale:** about 8,000 accounts and 2–4M events. Small enough for the free tiers.

### 3.2 Ingestion (`pipelines/`, dlt)
- One dlt source per system, with incremental loading on `updated_at`, merge write disposition for mutable tables, and append for events.
- Destinations: `snowflake` (database `RIDGELINE_RAW`) or `duckdb` (`warehouse/ridgeline.duckdb`). Chosen by environment variable.
- dlt schema contracts: new columns are allowed, but a type change fails the load.

### 3.3 Warehouse
- **Snowflake (primary while the trial lasts):**
  - Databases: `RIDGELINE_RAW` and `RIDGELINE_ANALYTICS` (schemas `staging`, `intermediate`, `marts`).
  - Roles: `LOADER`, `TRANSFORMER`, `REPORTER`.
  - Warehouse: XS with a 60-second auto-suspend and a resource monitor capped at 50 credits.
  - Setup SQL is in `infra/snowflake/`.
- **DuckDB (always on):** the same dbt project with target `duckdb`. It powers the public site and the AI analyst, and CI runs against it.
- **Portability:** cross-database SQL goes through dbt macros (`dbt.datediff`, `dbt.date_trunc`, and custom macros where needed). CI builds both targets whenever Snowflake credentials exist.

### 3.4 Transformation (`dbt/`)
- **Layers:**
  - `staging` (one model per source table, renamed and typed)
  - `intermediate` (business logic)
  - `marts` by domain: `finance`, `growth`, `sales`, `customer_success`, `contractor_outcomes`, `ops`
- **Key marts:**
  - `fct_mrr_daily` (new, expansion, contraction, churn, reactivation)
  - `dim_accounts`
  - `fct_account_funnel`
  - `fct_pqa_scores` (dbt Python model, scikit-learn, trained on 2024–25 cohorts and back-tested on 2026)
  - `fct_cohort_retention`
  - `fct_support_tickets` (with churn theme)
  - `fct_contractor_leads`
  - `fct_contractor_benchmarks`
  - `fct_measurement_quality`
  - `fct_marketing_channel_daily`
- **Snapshots:** `snap_subscriptions` (SCD2 of plan and price) feeds expansion and contraction.
- **Quality:**
  - Generic tests on all keys.
  - Accepted values and relationships tests.
  - dbt **unit tests** for the MRR movement and funnel logic.
  - **Model contracts** enforced on all marts.
  - Source freshness checks.
  - Singular tests that reconcile MRR to invoices.
- **Cortex:** on Snowflake, `AI_CLASSIFY` labels the ticket text with a churn theme. On DuckDB, a seed of the same labels is used. It's produced once with Claude Batch and committed, so the public build never calls an LLM.
- **Exposures:** one per Evidence page, so lineage runs from source to dashboard.
- **Docs:** dbt docs are built in CI and hosted at `/docs`.

### 3.5 Semantic layer (MetricFlow)
- Semantic models on the core marts.
- About 15 governed metrics:
  - mrr, net_new_mrr, nrr, grr, logo_churn_rate
  - signups, activation_rate, free_to_paid_60d
  - cac, cac_payback_months
  - pqa_precision_top_decile
  - lead_close_rate, speed_to_lead_median_min, measurement_redo_rate
  - tickets_per_100_accounts
- Each has a time spine, owner and description.
- The Evidence pages and the AI analyst both use these definitions, so the site and the AI give the same numbers.

### 3.6 BI (`reports/`, Evidence)
- Seven pages:
  1. **Executive scorecard:** weekly KPIs vs target, WoW and YoY, sparklines, commentary block.
  2. **Acquisition funnel:** channel → signup → activation → paid. CAC, payback, cohort conversion curves.
  3. **Ready for sales:** score distribution, back-test lift, call list with reasons, rep follow-up rate.
  4. **Retention and expansion:** cohort heatmap, NRR/GRR, add-on adoption, churn themes, at-risk list.
  5. **Contractor outcomes:** lead-to-job funnel and speed to lead benchmarked across contractors (percentiles), measurement redo rate by region and roof type.
  6. **Data health:** last load time per source, freshness status, test pass/fail counts, row-count trend. Built from dbt `run_results.json` and `sources.json` loaded into DuckDB.
  7. **Ask the data:** an embedded chat panel that calls the AI analyst API.
- Consistent theme, a written "how to read this" note per page, and filters for date range, channel, region, plan and crew size.
- Built as a static site. Data is baked in at build time from DuckDB.

### 3.7 AI analyst (`analyst_api/`)
- FastAPI, one endpoint: `POST /ask {question}` → `{answer, metrics_used, query_spec, sql, rows}`.
- Claude (`claude-opus-5-5`, effort low, server-side refusal fallback) has two tools:
  - `list_metrics` (from the semantic manifest)
  - `query_metrics(metrics, group_by, where, order_by, limit)`, which MetricFlow compiles to SQL and runs read-only on DuckDB
- Claude never writes raw SQL. Answers cite the metric names and show the generated SQL.
- **Guardrails:**
  - Max 5 questions per IP per day.
  - Global daily cap of 200 questions.
  - `max-instances=1`, so in-memory counters hold.
  - Anthropic console spend limit of $10/month.
  - Read-only DB connection, row limit 1,000, 20-second timeout.
- **Local extra:** an MCP server config so the same tools work in Claude Desktop. It appears in the demo video.

### 3.8 CI/CD (`.github/workflows/`)
- **PR (`ci.yml`):**
  - ruff + sqlfluff lint
  - simulator unit tests (pytest)
  - dlt load to DuckDB
  - `dbt build` (slim CI: `state:modified+` with deferral to the main-branch manifest)
  - MetricFlow validate
  - Evidence build
  - API tests
- **Nightly (`nightly.yml`):**
  - simulate the new day, then dlt load, dbt build (DuckDB)
  - upload artifacts, rebuild the Evidence site and deploy to Vercel
  - redeploy the API image to Cloud Run when the DuckDB file changes
  - optional Snowflake job (`workflow_dispatch` plus nightly when secrets exist)
- **Failure behaviour:** if any step fails, the site keeps the last good build and the Data health page shows the failure.

## 4. Error handling
- dlt: retries with backoff. A schema-contract violation fails the run loudly.
- dbt: a test failure on `error` severity blocks the deploy. Warn-level tests (for example, the planted missing timestamps) show on the Data health page.
- API: 429 when over the cap, a friendly message on Claude refusal or timeout, and no stack traces returned.

## 5. Testing
- pytest for the simulator (determinism, the planted patterns appear) and the API (guardrails, tool validation, mocked Claude).
- dbt unit, generic and singular tests (section 3.4).
- A smoke test after deploy: fetch each Evidence page and one `/ask` call with a fixed question.

## 6. Repo layout

```
ridgeline-analytics/
  simulator/  pipelines/  dbt/  reports/  analyst_api/  infra/snowflake/
  .github/workflows/  docs/ (architecture diagram, specs)  README.md
```

## 7. Build phases
1. Simulator, dlt, dbt on DuckDB, tests, PR CI.
2. Snowflake setup, dual-target dbt, Cortex classification, snapshots.
3. MetricFlow metrics; Evidence pages 1, 2, 3 and 6; Vercel deploy; nightly job.
4. AI analyst API and page 7; pages 4 and 5; Cloud Run deploy.
5. README, architecture diagram, 3-minute video, final review.

## 8. Needs from Sky (auth only)
- Phase 2: Snowflake trial account.
- Phase 3: Vercel account (GitHub login).
- Phase 4: Google Cloud account for Cloud Run, plus an Anthropic API key with a $10/month cap.
- Before going public: an OK to push the repo to `github.com/sky-five`.

## 9. Risks
- **Snowflake trial ends:** the DuckDB target keeps everything live. Snowflake proof stays as screenshots, query history and CI logs.
- **MetricFlow in a small container:** if the image is too large or slow, fall back to compiling the metric SQL at build time for a fixed set of allowed metric and dimension combinations.
- **Free-tier limits:** the data size is chosen to stay under them. Check sizes in phase 1.
