# ED wait times and bed occupancy

Emergency-department (ED) wait times per hospital site and day, the hospital's bed occupancy beside them, and a
query that answers which sites' admitted patients were over the 8-hour target last week. Everything runs on
DuckDB; the models are a small dbt project.

```
python -m ed_wait_times            # load, dbt build, write results/
python -m ed_wait_times --check    # rebuild and fail if results/ is out of date (CI runs this)
python -m ed_wait_times --refresh  # download the public file again first; stops if it changed
```

## Which data is public and which is simulated

| data | source | rows |
|---|---|---|
| Ontario ICU beds and patients, province-wide, one row a day | public: [data.ontario.ca](https://data.ontario.ca/dataset/availability-of-adult-icu-beds-and-occupancy-for-covid-related-critical-illness-crci), Open Government Licence - Ontario | 1,665 days, 2020-05-01 to 2024-11-20 |
| ED visits for ten hospital sites, triage to leaving | simulated (`simulate.py`, seeded) | 475,391 visits, 64,014 admitted, 2026-01-05 to 2026-11-08 |
| inpatient beds per site at midnight, staffed and occupied | simulated | 3,080 site-days |

Ontario publishes time spent in the ED only as a monthly figure per hospital in an online viewer; there is no
open per-site, per-day file to download. So the ten sites are simulated, following the public definitions: time
in the ED runs from triage to leaving; it is reported as the 90th percentile; the target is 8 hours for admitted
patients and for high-urgency patients sent home (triage levels 1 to 3), and 4 hours for low-urgency patients
sent home (levels 4 and 5). The sites are called ED01 to ED10; none is a real hospital.

The ICU file is the public part. It is committed (`data/ontario_icu_beds.csv`, 85 KB) and pinned by its SHA-256,
so the build and the tests give the same numbers offline. It stopped updating on 2024-11-20, so it has no "last
week": it is used as real bed-occupancy data for the data tests to run on.

## What is planted in the simulated sites

Admitted patients wait in the ED for a ward bed, so their hours in the ED grow as the wards fill.

| planted | what it does |
|---|---|
| a full teaching site, ED03 | its wards run at 97.8% of staffed beds on average; its admitted patients breach 8 hours in 39 of 44 weeks |
| a bed closure, ED07 from 2026-10-26 | 24 of its 260 staffed beds close: weekly 90th percentile goes from a median 5.66 hours (1 breach in 42 weeks) to 10.74 hours (both weeks after) |
| a small site, ED10 | about 2 admissions a day: in 43 of 44 weeks it has fewer than 20 admitted patients, too few to report a 90th percentile |

## The models

| model | grain | what it is for |
|---|---|---|
| `stg_ed__visits` | visit | hours in the ED, patient group (admitted, high-urgency sent home, low-urgency sent home), its target and whether the visit met it |
| `stg_ed__bed_census` | site x day | occupied over staffed beds at midnight |
| `stg_public__ontario_icu_beds` | day | the public file as published, plus adult and paediatric occupancy |
| `fct_site_day_metric` | site x day x metric | every daily number in one long shape: visits, admitted visits, 90th percentile hours for admitted and for low-urgency patients, share admitted within 8 hours, staffed and occupied beds, occupancy |
| `site_week` | site x week x patient group | the 90th percentile over the week's patients against the target; `reportable` (20 patients or more) and `breached` |
| `icu_province_day` | day | the public file with two flags: more patients than beds, and an adult patient count more than 25% off the median of the week around it |

The weekly figure is the 90th percentile of the week's patients, not the average of the seven daily figures. For
ED03 the average of daily figures is lower in 37 of 44 weeks; a test checks the mart does not take that shortcut.

## Which sites breached the 8-hour target last week

`breaches.py` reads `site_week` only. For the last full week in the data (2026-11-02 to 2026-11-08), admitted
patients:

| site | admitted | 90th percentile, hours | bed occupancy | over 8 hours |
|---|---|---|---|---|
| ED07 | 117 | 11.51 | 100.0% | yes |
| ED03 | 298 | 10.43 | 99.3% | yes |
| ED06 | 172 | 8.34 | 94.9% | yes |
| ED01 | 301 | 7.87 | 94.3% | |
| ED04 | 191 | 6.75 | 93.3% | |
| ED02 | 219 | 6.24 | 92.0% | |
| ED05 | 133 | 5.97 | 92.1% | |
| ED08 | 56 | 5.43 | 87.0% | |
| ED09 | 30 | 4.82 | 86.5% | |
| ED10 | 12 | not reported | 83.2% | |

`breaches(con, week_start, group)` answers the same for any week and any of the three patient groups. A site under
20 patients is listed as not reported and goes last, never as passing.

## What the data tests find in the public file

The file is internally consistent: COVID and non-COVID patients add up to all patients, and patients plus
available beds add up to beds, for adults and children, on all 1,665 days, with no missing day. Adult ICU
occupancy has a median of 74.2%. A warn-level test lists 11 days that look wrong or unusual, kept as published
and listed in `results/summary.json`:

- 9 days in November 2022 with more paediatric ICU patients than paediatric ICU beds (up to 122 patients for 112 beds);
- 2023-09-09: 560 adult ICU patients, against about 1,750 on the days around it;
- 2023-10-20: 2,870 adult ICU patients for 2,421 beds (the file says -449 beds available), against about 1,770 around it.

The two single days look like reporting errors; the November 2022 days may be real. The test warns rather than
fails because the rows are the source's, not this project's.

## Tests

`tests/ed_wait_times/` (12 tests) builds the warehouse once and checks: the simulation is seeded and every arrival
falls inside its day; the weekly 90th percentile, patient counts and share within target match a pandas count from
the raw visits for all 440 site-weeks; daily visit counts in the long table match; the planted patterns; the
breach list for last week against pandas, for an earlier week and for another patient group; the breach rule on a
hand-made week (8.01 hours breaches, 8.00 does not, 19 patients is not reported); the public file matches its pin
and a changed byte is refused; the 11 odd days; and that `results/` is current. The dbt project has 24 data tests,
one of them warn-level (keys, accepted values, every site-day-metric present once, weeks add up to visits, stays between 0 and 48
hours, the public file's parts add up and has no missing day).

Next: an Evidence page of throughput by site, and a read-only MCP tool on `breaches()`.
