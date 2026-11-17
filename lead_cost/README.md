# Cost per issued lead

A pipeline that turns three messy exports (ad platforms, call tracking, CRM) into one row per lead and a cost per
issued lead and per demo by client and campaign, with tests aimed at the failures that don't crash anything: a short
file, a missing day, a renamed campaign, a click id that stops matching. Bronze in Python, Silver and Gold in a
small dbt project on DuckDB. All data is simulated.

```bash
python -m lead_cost           # simulate, load Bronze, dbt build, plant the four faults, write results/
python -m lead_cost --check   # fail if results/ would change (run in CI)
```

## The exports

`simulate.py` runs a lead-generation operation for four home-service clients (roofing, HVAC, plumbing, solar) with
eleven campaigns on a search and a social platform, 2026-04-01 to 2026-06-30. A click can become a lead by web form
or by phone. Leads are worked in the CRM: new, then rejected or **issued** (sent to the client's rep with an
appointment); an issued lead becomes a **demo** when the rep runs the in-home presentation.

The exports arrive as 548 files, each with a declared row count:

| source | files | rows | what makes it messy |
|---|---|---|---|
| search spend | 91 | 1,620 | each file repeats the last three days with restated spend, in micros; "North Roofing - Roof Repair" |
| social spend | 92 | 460 | dollars as text, "NORTH_ROOFING_ROOF-REPAIR", sometimes a trailing space; the 2026-05-14 file arrives twice |
| search / social clicks | 182 | 57,872 | one row per click id, campaign named the platform's way |
| calls | 91 | 1,531 | caller as +1XXXXXXXXXX, tracking number as bare digits, click id when the caller came from the site |
| tracking numbers | 1 | 11 | "(416) 555-2000" to "North Roofing \| Roof Repair" |
| CRM leads | 91 | 6,207 | every record created or changed that day; phones typed four ways, emails in mixed case, 209 click ids stored as "gclid=..." |

A person who fills in the form and also phones gets two CRM records, and some submit the form twice. 7% of form
leads lose their click id on the way to the CRM. Some calls and forms come from people who never clicked an ad.

## Bronze, Silver, Gold

**Bronze** (`load.py`): every file lands as text in `bronze.<source>` with its batch id, file name and delivery
time, nothing dropped or fixed. `bronze.load_audit` has one row per file: the rows its manifest declared, the rows
counted in Bronze after the load, and a checksum (so the repeated social file shows up as two batches with one
checksum).

**Silver** (`dbt/models/silver/`): `slv_ad_spend` keeps the latest delivered row per platform, campaign and day
(1,079 restated or repeated rows dropped, 1,001 kept) and maps the three spellings of a campaign to one key;
`slv_ad_clicks`, `slv_calls` and `slv_tracking_numbers` clean click ids and reduce phones to ten digits;
`slv_crm_records` keeps the current version of each of the 3,107 CRM records.

**Gold** (`dbt/models/gold/`):

| model | grain | what it adds |
|---|---|---|
| `gold_leads` | person (client and phone) | one lead however many CRM records (2,826 leads from 3,107 records), its campaign and how it was found, issued and demo |
| `gold_campaign_cost` | campaign | spend, clicks, leads, issued leads, demos, cost per lead, per issued lead and per demo |
| `gold_client_cost` | client | the same per client, with the leads no campaign can claim counted beside it |

A lead's campaign comes from, in order: a click id on any of its CRM records (1,222 leads), the click id call
tracking saw on its call (675), the tracking number it called (122). 807 leads are reached by none of these.

Checked against the simulator's truth: no lead is attributed to the wrong campaign, every issued and demo outcome
matches, and 711 of the 807 unattributed leads are organic. The other 96 are paid leads (45 of them issued) that
came by form, lost their click id and never phoned; no join can recover them, so their cost is spread over the
leads that can be attributed.

## The numbers

$213,675.83 of spend, 891 issued leads and 439 demos attributed to a campaign: **$239.82 per issued lead**.

| client | spend | paid leads | issued | demos | per issued lead | per demo | unattributed leads |
|---|---|---|---|---|---|---|---|
| Lakeside HVAC | $51,041.90 | 582 | 256 | 133 | $199.38 | $383.77 | 220 |
| Metro Plumbing | $41,479.69 | 555 | 290 | 135 | $143.03 | $307.26 | 221 |
| North Roofing | $69,730.84 | 506 | 246 | 129 | $283.46 | $540.55 | 190 |
| Valley Solar | $51,423.40 | 376 | 99 | 42 | $519.43 | $1,224.37 | 176 |

Social clicks are cheap but rarely become issued leads: Valley Solar's social solar campaign costs $68.34 a lead
against $285.99 on search, but $339.99 per issued lead against $637.53, and the gap narrows further per demo
($1,133.31 against $1,224.05). Per campaign: [results/campaign_cost.csv](results/campaign_cost.csv). Leads from late
June have not all been worked yet, so the last weeks understate issued leads and demos.

## Silent failures

Seven dbt tests in `dbt/tests/` check what a build would not complain about: every file landed with its declared row
count; every campaign has spend every day; every spend row and click maps to a campaign; each week at least 98% of
the CRM's click ids match a click; Gold spend equals Silver spend; paid plus unattributed leads equal all leads, and
demos <= issued <= leads; a lead's campaign belongs to its client.

`faults.py` plants four failures one at a time. Each still loads and builds; `python -m lead_cost` builds each
into its own warehouse, runs the tests and records what failed and what the cost figure would have said
([results/faults.json](results/faults.json)):

| fault | caught by | cost per issued lead without the tests |
|---|---|---|
| the 2026-06-10 CRM file arrives with 60% of its rows | `assert_every_batch_fully_loaded` | $240.36 (+$0.54) |
| the social 2026-06-20 spend file never arrives | `assert_spend_every_day` | $239.28 (-$0.54) |
| a social campaign is renamed from 2026-06-15 | `assert_spend_maps_to_a_campaign` (and two more) | $238.65 (-$1.17) |
| from 2026-06-01 the form stores click ids in lower case | `assert_crm_click_ids_match` | $298.01 (+$58.19) |

Three of the four move the headline by about a dollar, which is why they need a test: nobody would see them on a
chart. The click-id change is the expensive one: 174 issued leads drop out of their campaigns and become
unattributed, and each client's cost per issued lead rises by between $43.82 and $131.50.

## Tests

`tests/lead_cost/` (17 tests): the simulation is seeded; the exports really are messy the way the docstring says
(four phone formats, restated search days, trailing spaces); every file landed in full and only the planted file
repeats; Silver spend equals the simulator's final spend on every campaign and day; Silver CRM keeps the last version
and cleans phones, emails and click ids; Gold against the truth (no wrong campaign, outcomes match); the unattributed
paid leads recomputed straight from the exports; cost per issued lead and per demo recomputed in pandas; each fault
changes only what it says; the lower-cased click id is caught by its own test and no other; the committed results are
current, and the figures quoted in this README match them.
