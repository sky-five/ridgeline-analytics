"""The one public file in this folder: Ontario's daily count of ICU beds and ICU patients, province-wide, from
2020-05-01 to 2024-11-20, published on data.ontario.ca under the Open Government Licence - Ontario.

The file is committed (data/ontario_icu_beds.csv, 85 KB) and pinned by its SHA-256, so the build and the tests run
offline and give the same numbers. `python -m ed_wait_times --refresh` downloads it again and stops if it changed.
The dataset stopped updating on 2024-11-20, so there is no "last week" in it: it is the province's ICU occupancy
history, used as a real check of what bed-occupancy data looks like, not as a live feed.
"""
import hashlib
import urllib.request
from pathlib import Path

import pandas as pd

URL = ("https://data.ontario.ca/dataset/1b5ff63f-48a1-4db6-965f-ab6acbab9f29/resource/"
       "c7f2590f-362a-498f-a06c-da127ec41a33/download/icu_beds.csv")
DATASET = ("https://data.ontario.ca/dataset/"
           "availability-of-adult-icu-beds-and-occupancy-for-covid-related-critical-illness-crci")
LICENCE = "Open Government Licence - Ontario"
PATH = Path(__file__).resolve().parent / "data" / "ontario_icu_beds.csv"
SHA256 = "ac0273990f51967e32881c332930e70bf7f82a252c58fb498efb31b3a241b5b4"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path = PATH) -> pd.DataFrame:
    """The committed file as published, after checking it is the pinned version."""
    data = path.read_bytes()
    if sha256(data) != SHA256:
        raise ValueError(f"{path} does not match the pinned SHA-256; run python -m ed_wait_times --refresh")
    return pd.read_csv(path, parse_dates=["date"])


def refresh(path: Path = PATH, url: str = URL) -> bool:
    """Download the file again. True if it is unchanged; raises if it changed (update SHA256 on purpose)."""
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    if sha256(data) != SHA256:
        raise ValueError(f"the published file changed (sha256 {sha256(data)}); review it, then update public.SHA256")
    path.write_bytes(data)
    return True
