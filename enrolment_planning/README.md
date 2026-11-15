# Enrolment planning mart

Public postsecondary enrolment counts for Canada in a small dbt star schema on DuckDB, IRCC's monthly count of
new study permits beside them, and three simple rules for next year's international intake, back-tested month by
month against what was later published. All the data is public; nothing here is simulated.

```
python -m enrolment_planning            # load, dbt build, write results/
python -m enrolment_planning --check    # rebuild and fail if results/ is out of date (CI runs this)
python -m enrolment_planning --refresh  # download both sources again first; stops if anything changed
```

## The public data

| file | source | rows |
|---|---|---|
| `data/statcan_enrolments.csv` | Statistics Canada [table 37-10-0163](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3710016301), fall snapshot | 22,949: fall 2010 to fall 2024, 11 regions, ISCED level, institution type, program group, status of student |
| `data/statcan_totals.csv` | the same table's published totals per region, year and status | 660 |
| `data/ircc_study_permits_monthly.xlsx` | IRCC, [study permit holders, monthly](https://open.canada.ca/data/en/dataset/90115b00-f9b8-49e8-afa3-b4cff8facaee), as published | 7,560 cells: January 2015 to August 2026, by province or territory and study level |

Both are under the Open Government Licence - Canada. All three files are committed and pinned by SHA-256, so the
build and the tests give the same numbers offline.

StatCan's full table is 2.7 GB of CSV (every age group and gender), so `public.build_extract` keeps counts for all
ages and genders at the leaf categories only, with short codes that the dbt dims expand. `--refresh` rebuilds
the extract from the downloaded zip and compares it with the pinned one.

What the sources do that a planner has to know:

- Enrolments are program counts on one fall date (each institution picks a day between 30 September and
  1 December), not students over a year. Colleges with January and May intakes look smaller than they are.
- StatCan rounds every count at random to a multiple of 3, so leaves do not add up exactly to the totals;
  491 cells are not published (`..`). A dbt test checks that the leaves of every region, year and status land
  within 2 per cell of the published total, and a pytest checks the provinces against the national total.
- IRCC rounds to a multiple of 5 and shows 1 to 4 as `--` (932 of the 7,560 cells). The all-Canada row is more
  than the provinces added up because it also counts permits with no province stated.
- IRCC's months add up to 2% to 5% more than its own yearly totals, in every year: a person whose permit took
  effect in two months of a year counts in both months but once in the year. The rules below forecast the
  monthly series, so their 12-month totals are on the monthly basis.

## The star schema

| model | grain | what it is for |
|---|---|---|
| `fct_enrolment` | term x region x ISCED level x institution type x program group x status | the fact: fall-snapshot enrolments, with a flag where StatCan published no number |
| `dim_term` | fall year | academic year label (2024/2025) and the snapshot window |
| `dim_program` | program group | the 11 STEM and BHASE groups of CIP Canada 2021 (plus unclassified) |
| `dim_level` | ISCED level | upper secondary to doctoral, `is_tertiary` for ISCED 5 to 8 |
| `dim_status` | status of student | Canadian, international, not reported |
| `dim_region`, `dim_institution` | province or the territories; university or college | |
| `enrolment_region_year` | region x fall year | enrolments by status, the published totals next to them, international share |
| `fct_study_permits_month` | month x region x study level | new study permits, territories added up, suppressed cells counted |
| `study_permits_canada_month` | month x study level | IRCC's own all-Canada row, the series to forecast for the country |

In fall 2024 there were 533,382 international enrolments out of 2,345,775 (22.7%), down from the peak of
572,967 in fall 2023; in fall 2010 the share was 7.2%. Ontario had 286,539 of them (28.5% of its enrolments).
65% were in BHASE programs, 33% in STEM.

## Three intake rules, back-tested monthly

`forecast.py` forecasts the next 12 months of new post-secondary study permits from every month-end from 2017-12
to 2026-07, using only months up to that point, for Canada and the four provinces with the most permits
(Ontario, British Columbia, Quebec, Alberta):

- `same_month_last_year`: the same month a year earlier.
- `last_year_with_trend`: the same month a year earlier, times the last 12 months over the 12 before them.
- `three_year_mean`: the mean of the same month in the last three years.

Every forecast is scored against what IRCC later published: WAPE (absolute errors over actuals) and bias (errors
over actuals; above zero means too many). Single months are hard to hit because the August peak moves between
July, August and September, so the table scores each origin's 12-month total, which is what an intake plan
uses. Canada, by the year the 12-month window ends:

| period | same month last year | last year with trend | three-year mean |
|---|---|---|---|
| 2018-2019 steady growth (13 windows) | **11.6%**, bias -11.6% | 12.0%, +11.8% | 27.2%, -27.2% |
| 2020-2021 pandemic (24) | 22.7%, +1.2% | 32.3%, +5.6% | **18.0%**, -5.3% |
| 2022-2023 fast growth (24) | **24.3%**, -24.3% | 30.5%, +3.4% | 34.7%, -34.7% |
| 2024-2026 after the cap (32) | **35.2%**, +24.5% | 38.3%, +30.2% | 42.3%, +18.3% |

What the back-test says:

- No rule wins every period. Last year's months are best in steady and fast growth but always under while
  growing; the trend rule removes that bias on average and swings more; the three-year mean is the steadiest
  through the pandemic dip and the worst in growth.
- After the federal cap on study permit applications (announced 2024-01-22), every rule forecast too many for
  Canada, by 18% to 30% on the 12-month total. Across the five series and three rules, 14 of 15 were too high;
  the exception is Alberta's three-year mean (bias -5.6%). Rules built on past months cannot see a policy change;
  a plan in 2024 needed the cap as an explicit input, which is what the what-if on the dashboard page is for.
- The provinces tell the same story: the best rule after the cap misses by 17.6% (Quebec) to 44.4% (Ontario).

`results/summary.json` also holds, for each fall from 2016, international enrolments over the new post-secondary
permits of the 12 months to September (1.09 to 1.68 enrolments per new permit; 1.24 in fall 2024). That ratio is
the starting point for turning an intake what-if into a fall enrolment figure.

`results/backtest_scores.csv` has every series, rule, period and horizon (1 to 12 months, and the 12-month
total). `results/international_share.csv` has international and all enrolments per region (and Canada), fall and
program group; `results/permits_monthly.csv` the five monthly permit series. `--check` covers all four files.

## The dashboard page

The site's [Enrolment planning page](https://sky-five.github.io/ridgeline-analytics/enrolment-planning/) shows
the international share by region and program group (fall 2024, and every fall for Canada and the four largest
provinces), the back-test by period and rule for any of the five series, and a what-if.
`report.py` turns the committed results into seven `reporting.enrol_*` tables (no warehouse needed), so the page
does not move with the nightly build.

The what-if multiplies a year of new post-secondary permits (October to September) by enrolments per new permit.
That ratio is a stock over a flow: the fall count holds every year of study, the permits only the new arrivals, so
it rises when intake falls (1.31 in fall 2019, 1.68 in fall 2020 when intake dropped, 1.09 at the fall 2023 peak).
The page offers four published values (fall 2024, lowest, mean, highest) and shows the whole range. The last
complete window, October 2024 to September 2025, had 263,845 new permits, down from 430,105 a year earlier; at
1.24 that is 328,600 international enrolments in fall 2025 (-38.4%), at 1.68 it is 444,405 (-16.7%). StatCan has
not published fall 2025 yet. It is arithmetic on published ratios, not a forecast.

## Tests

`tests/enrolment_planning/` (25 tests) checks the committed files against their pins and refuses a changed one;
`build_extract` on hand-made rows in StatCan's layout (only leaves kept, Canada rows and age groups dropped, `..`
kept as empty); the IRCC parser (suppressed cells, every region, the months against the sheet's own yearly
totals); the fact against the raw extract and every fact row joining every dim; the territories added up; the
three rules on a hand-made series, and that no rule changes when months after the origin change; the back-test's
origins, horizons and scores on a short series; and the committed results and the numbers quoted here.
`test_report.py` checks the dashboard: the new results files equal what the marts give, regions add up to Canada
and program groups to all programs, months add up to the yearly permit counts, every October-to-September window
is recomputed, the page's own what-if SQL (run in DuckDB with the slider and dropdown filled in) gives intake
times ratio, and the page reads only exported tables and columns. The dbt
project has 27 data tests, including the rounding bounds above.
