"""The public feed both loaders read: USGS earthquakes of magnitude 2.5+ in the past 30 days (public domain).

The feed is regenerated every minute: new events arrive, events are revised (magnitude, location, status
automatic -> reviewed), a few are deleted, and events older than 30 days drop off the end. Snapshots are
stored gzipped under snapshots/, named by the UTC minute they were fetched.
"""
import gzip
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_month.csv"
SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"
WINDOW_DAYS = 30
STAMP = "%Y-%m-%dT%H%MZ"

# Column order and DuckDB types of the feed's CSV.
COLUMNS = {
    "time": "TIMESTAMP", "latitude": "DOUBLE", "longitude": "DOUBLE", "depth": "DOUBLE", "mag": "DOUBLE",
    "magType": "VARCHAR", "nst": "INTEGER", "gap": "DOUBLE", "dmin": "DOUBLE", "rms": "DOUBLE",
    "net": "VARCHAR", "id": "VARCHAR", "updated": "TIMESTAMP", "place": "VARCHAR", "type": "VARCHAR",
    "horizontalError": "DOUBLE", "depthError": "DOUBLE", "magError": "DOUBLE", "magNst": "INTEGER",
    "status": "VARCHAR", "locationSource": "VARCHAR", "magSource": "VARCHAR",
}
KEY = "id"


def fetched_at(path: Path) -> datetime:
    return datetime.strptime(path.name.split(".")[0], STAMP).replace(tzinfo=UTC)


def snapshots(folder: Path = SNAPSHOTS) -> list[Path]:
    return sorted(folder.glob("*.csv.gz"))


def read_sql(path: Path) -> str:
    """A DuckDB expression that reads one snapshot with fixed types."""
    cols = ", ".join(f"'{c}': '{t}'" for c, t in COLUMNS.items())
    return f"read_csv('{path.as_posix()}', header = true, columns = {{{cols}}}, timestampformat = '%Y-%m-%dT%H:%M:%S.%gZ')"


def fetch(folder: Path = SNAPSHOTS, retries: int = 4) -> Path:
    """Download the feed now and store it as a new snapshot."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(FEED_URL, timeout=60) as r:
                body = r.read()
            break
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt * 5)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now(UTC).strftime(STAMP)}.csv.gz"
    path.write_bytes(gzip.compress(body, mtime=0))
    return path
