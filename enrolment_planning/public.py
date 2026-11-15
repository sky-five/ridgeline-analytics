"""The two public files this folder is built on, both under the Open Government Licence - Canada.

1. Statistics Canada table 37-10-0163, postsecondary enrolments by ISCED level, institution type, program group
   (STEM and BHASE) and status of student in Canada, fall snapshot, 2010/2011 to 2024/2025. The full table is a
   97 MB zip (2.7 GB of CSV with age and gender), so the repo keeps a compact extract: counts only, all ages, all
   genders, leaf categories only, one row per region, year, level, institution type, program and status
   (data/statcan_enrolments.csv), plus the published totals per region, year and status
   (data/statcan_totals.csv) so a test can check the leaves add back up. Codes are expanded by the dbt dims.
2. IRCC's monthly count of study permit holders by province or territory, study level and the month the permit
   became effective, January 2015 to August 2026 (data/ircc_study_permits_monthly.xlsx, kept as published).
   IRCC rounds every count to a multiple of 5 and shows "--" for 1 to 4.

All three files are committed and pinned by SHA-256, so the build and the tests run offline and give the same
numbers. `python -m enrolment_planning --refresh` downloads both sources again and stops if anything changed.
"""
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import duckdb
import pandas as pd

LICENCE = "Open Government Licence - Canada"
DATA = Path(__file__).resolve().parent / "data"

STATCAN_TABLE = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3710016301"
STATCAN_ZIP = "https://www150.statcan.gc.ca/n1/tbl/csv/37100163-eng.zip"
ENROLMENTS = DATA / "statcan_enrolments.csv"
TOTALS = DATA / "statcan_totals.csv"

IRCC_DATASET = "https://open.canada.ca/data/en/dataset/90115b00-f9b8-49e8-afa3-b4cff8facaee"
IRCC_URL = "https://www.ircc.canada.ca/opendata-donneesouvertes/data/EN_ODP-TR-Study-IS_PT_study_level_sign.xlsx"
PERMITS = DATA / "ircc_study_permits_monthly.xlsx"

SHA256 = {
    ENROLMENTS.name: "b7f465507889c8f7f1facf6c50a68d0c7285b374e7b8767764d405c4da58c4c0",
    TOTALS.name: "1d2151495d11b4dbc61fa2e16f699e07402a2e81cd474b75dec98bd0de8fb072",
    PERMITS.name: "b047f434bd34a508071330b199ba18b37dd13a6b6fc28115be5eabbce7997076",
}

# Short codes used in the extract. The dbt dims carry the full names.
LEVELS = {
    "Upper secondary education": "3", "Post-secondary non-tertiary education": "4",
    "Short-cycle tertiary education": "5", "Bachelor's or equivalent": "6", "Master's or equivalent": "7",
    "Doctoral or equivalent": "8", "Not in International Standard Classification of Education (ISCED)": "9",
}
INSTITUTIONS = {"University": "U", "College": "C"}
STATUSES = {"Canadian students": "CAN", "International students": "INT",
            "Not reported, status of student in Canada": "NR", "Total, status of student in Canada": "ALL"}
REGIONS = {
    "Canada": "CA", "Newfoundland and Labrador": "NL", "Prince Edward Island": "PE", "Nova Scotia": "NS",
    "New Brunswick": "NB", "Quebec": "QC", "Ontario": "ON", "Manitoba": "MB", "Saskatchewan": "SK",
    "Alberta": "AB", "British Columbia": "BC", "Territories": "TR",
}
# IRCC names the three territories one by one; StatCan groups them.
IRCC_TERRITORIES = {"Yukon": "TR", "Northwest Territories": "TR", "Nunavut": "TR"}
IRCC_LEVELS = {"Secondary or less": "secondary_or_less", "Post Secondary": "post_secondary",
               "Other Studies": "other", "Education level not stated": "not_stated"}
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _checked(path: Path) -> Path:
    if sha256(path.read_bytes()) != SHA256[path.name]:
        raise ValueError(f"{path} does not match the pinned SHA-256; run python -m enrolment_planning --refresh")
    return path


def enrolments() -> pd.DataFrame:
    """The extract as committed: fall_year (2010 = 2010/2011), region, isced, institution, program, status,
    enrolments (empty where StatCan shows '..')."""
    return pd.read_csv(_checked(ENROLMENTS), dtype={"isced": str, "program": str}, keep_default_na=False,
                       na_values=[""])


def totals() -> pd.DataFrame:
    """Published totals per fall_year, region and status (all levels, institutions and programs)."""
    return pd.read_csv(_checked(TOTALS), keep_default_na=False, na_values=[""])


def _count(v) -> tuple[float | None, bool]:
    """An IRCC cell as (count, suppressed). '--' is 1 to 4, shown as no number."""
    if isinstance(v, str):
        v = v.strip()
        if v == "--":
            return None, True
        return float(v.replace(",", "")), False
    return float(v), False


def permits(path: Path = PERMITS) -> pd.DataFrame:
    """IRCC's wide sheet as one row per region, study level and month: month (first day), region, study_level,
    permits (None where suppressed), suppressed. The territories are kept apart (region_name) and coded TR.
    The all-Canada rows come through as region CA; they are more than the provinces added up, because IRCC also
    counts permits with no province stated (shown only as a total, so not kept) and rounds every cell."""
    raw = pd.read_excel(_checked(path), header=None)
    year_row, month_row = raw.iloc[2].ffill(), raw.iloc[4]
    month_cols = [c for c in raw.columns[2:] if month_row[c] in MONTHS]
    months = [pd.Timestamp(int(year_row[c]), MONTHS[month_row[c]], 1).date() for c in month_cols]
    rows, pending = [], []
    for i in range(5, len(raw)):
        first, second = raw.iat[i, 0], raw.iat[i, 1]
        # Province blocks put the level in column 1; the all-Canada block at the bottom puts it in column 0.
        level = second if isinstance(second, str) else first
        if isinstance(level, str) and level in IRCC_LEVELS:
            pending.append((i, IRCC_LEVELS[level]))
            continue
        if isinstance(first, str) and (first.endswith(" Total") or first == "Total - All Canada") and pending:
            name = "Canada" if first == "Total - All Canada" else first.removesuffix(" Total")
            code = REGIONS.get(name) or IRCC_TERRITORIES[name]
            for j, study_level in pending:
                for month, c in zip(months, month_cols, strict=True):
                    n, sup = _count(raw.iat[j, c])
                    rows.append({"month": month, "region": code, "region_name": name, "study_level": study_level,
                                 "permits": n, "suppressed": sup})
        pending = []
    df = pd.DataFrame(rows)
    df["permits"] = df["permits"].astype("Int64")
    return df


def build_extract(csv_in_zip: bytes | Path) -> tuple[str, str]:
    """The two compact CSVs from StatCan's full table (the 37100163.csv inside the zip)."""
    con = duckdb.connect()
    src = str(csv_in_zip)
    con.execute(f"""create table t as select * from read_csv('{src}', header=true, all_varchar=true)
        where "Selected statistics" = 'Number' and "Age group" = 'Total, age group' and "Gender" = 'Total, gender'""")
    for name, mapping in [("regions", REGIONS), ("levels", LEVELS), ("insts", INSTITUTIONS),
                          ("statuses", STATUSES)]:
        con.register(name, pd.DataFrame(list(mapping.items()), columns=["name", "code"]))
    base = """
        select cast(left(t."REF_DATE", 4) as integer) as fall_year, r.code as region, {cols},
               try_cast(t."VALUE" as integer) as enrolments
        from t join regions r on r.name = t."GEO" join statuses s on s.name = t."Status of student in Canada"
        {joins} where {where} order by all"""
    program = """t."Classification of Instructional Programs, STEM and BHASE groupings" """
    leaves = base.format(
        cols=f"""l.code as isced, i.code as institution,
                 coalesce(nullif(regexp_extract({program}, '\\[(.+)\\]', 1), ''), 'u') as program, s.code as status""",
        joins="""join levels l on l.name = t."International Standard Classification of Education (ISCED)"
                 join insts i on i.name = t."Institution type" """,
        where=f"""r.code <> 'CA' and s.code <> 'ALL' and {program} not like 'Total%'
                  and regexp_extract({program}, '\\[(.+)\\]', 1) not in ('a', 'b')""")
    tots = base.format(
        cols="s.code as status", joins="",
        where=f"""t."International Standard Classification of Education (ISCED)" like 'Total%'
                  and t."Institution type" like 'Total%' and {program} = 'Total, instructional program'""")
    out = []
    for sql in (leaves, tots):
        out.append(con.sql(sql).df().to_csv(index=False, lineterminator="\n"))
    return out[0], out[1]


def refresh() -> list[str]:
    """Download both sources again. Returns the files checked; raises if any changed (update SHA256 on purpose)."""
    with urllib.request.urlopen(IRCC_URL, timeout=120) as r:
        xlsx = r.read()
    with urllib.request.urlopen(STATCAN_ZIP, timeout=600) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    tmp = DATA / "_37100163.csv"
    try:
        tmp.write_bytes(z.read("37100163.csv"))
        fresh = dict(zip((ENROLMENTS.name, TOTALS.name), build_extract(tmp), strict=True))
    finally:
        tmp.unlink(missing_ok=True)
    changed = [n for n, text in fresh.items() if sha256(text.encode()) != SHA256[n]]
    if sha256(xlsx) != SHA256[PERMITS.name]:
        changed.append(PERMITS.name)
    if changed:
        raise ValueError(f"published data changed: {', '.join(changed)}; review it, then update public.SHA256")
    return sorted(SHA256)
