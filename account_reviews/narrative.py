"""A short written summary per account review, and a checker that every number in a summary is in the model.

`draft` writes the paragraph from the governed monthly series (the same table the review page charts). `check`
works on any text, hand-edited or drafted by a model: it finds every dollar amount, percentage, count and
month in it and fails unless each one equals a value computed from the review tables. Values are compared at
the precision the text shows them ($1,234 must be within 50 cents, 12% within half a point). A number only
matches facts on the topic of its sentence (MRR, leads, measurements, tickets, health), so a ticket count
can't pass by coinciding with a lead count. The checker tests values, not wording: "up" vs "down" is not read.
"""
import re
from dataclasses import dataclass, field

import pandas as pd

RECENT = 3  # months in the "recent" window compared with the window just before it

# a sentence is about a topic when it contains one of these words; it may then only quote that topic's facts
TOPIC_WORDS = {
    "mrr": ("mrr", "revenue"),
    "leads": ("lead",),
    "measurements": ("measurement", "redo"),
    "tickets": ("ticket",),
    "health": ("health",),
}
COUNTS = {"leads": ["leads", "closed_leads", "won_leads"],
          "measurements": ["measurement_orders", "redo_orders"],
          "tickets": ["tickets"]}
RATES = {"leads": ("won_leads", "closed_leads"), "measurements": ("redo_orders", "measurement_orders")}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December"]
MONTH_YEAR = re.compile(r"\b(" + "|".join(MONTH_NAMES) + r") (\d{4})\b")
WINDOW = re.compile(r"\b(\d+) months?\b")
NUMBER = re.compile(r"(?P<usd>\$)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<dec>\d+))?(?P<pct>%)?")


@dataclass
class Found:
    text: str  # as written, e.g. "$1,250" or "38%"
    kind: str  # usd, pct, count, month or window
    value: float
    sentence: str
    matched: bool


@dataclass
class CheckResult:
    numbers: list[Found] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(n.matched for n in self.numbers)

    @property
    def problems(self) -> list[str]:
        return [f"{n.text!r} ({n.kind}) matches nothing in the model: {n.sentence!r}"
                for n in self.numbers if not n.matched]


def windows(series: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The whole review window, the last RECENT months and the RECENT months before those."""
    s = series.sort_values("month").reset_index(drop=True)
    return {"all": s, "recent": s.tail(RECENT), "before": s.iloc[-2 * RECENT:-RECENT]}


def facts(header: pd.Series, series: pd.DataFrame) -> dict[tuple[str, str], list[float]]:
    """Every value a summary may quote, keyed by (topic, kind). Computed from the tables, not from the draft."""
    s = series.sort_values("month")
    f: dict[tuple[str, str], list[float]] = {}

    def add(topic, kind, *values):
        f.setdefault((topic, kind), []).extend(float(abs(v)) for v in values)

    mrr = s["mrr"].astype(float)
    add("mrr", "usd", *mrr, *s["net_new_mrr"], header["mrr"], mrr.iloc[-1] - mrr.iloc[0])
    if mrr.iloc[0]:
        add("mrr", "pct", 100 * (mrr.iloc[-1] - mrr.iloc[0]) / mrr.iloc[0])
    for topic, cols in COUNTS.items():
        for w in windows(s).values():
            add(topic, "count", *(int(w[c].sum()) for c in cols))
        add(topic, "count", *(v for c in cols for v in s[c]))
    for topic, (num, den) in RATES.items():
        for w in windows(s).values():
            if w[den].sum():
                add(topic, "pct", 100 * w[num].sum() / w[den].sum())
    add("health", "count", header["health_score"])
    return f


def check(text: str, header: pd.Series, series: pd.DataFrame) -> CheckResult:
    """Find every number in `text` and match it against `facts`. Months must fall inside the review window."""
    known = facts(header, series)
    months = {(m.month, m.year) for m in pd.to_datetime(series["month"])}
    lengths = {RECENT, len(series)}
    result = CheckResult()
    name = str(header.get("company_name", "") or "")
    body = text.replace(name, "The account") if name else text  # names may hold digits or full stops
    for sentence in re.split(r"(?<=[.!?])\s+", body.strip()):
        rest = sentence
        lower = rest.lower()
        topics = [t for t, words in TOPIC_WORDS.items() if any(w in lower for w in words)] or list(TOPIC_WORDS)

        for m in MONTH_YEAR.finditer(rest):
            ok = (MONTH_NAMES.index(m.group(1)) + 1, int(m.group(2))) in months
            result.numbers.append(Found(m.group(0), "month", int(m.group(2)), sentence, ok))
        rest = MONTH_YEAR.sub(" ", rest)
        for m in WINDOW.finditer(rest):
            ok = int(m.group(1)) in lengths
            result.numbers.append(Found(m.group(0), "window", int(m.group(1)), sentence, ok))
        rest = WINDOW.sub(" ", rest)
        for m in NUMBER.finditer(rest):
            value = float(m.group("int").replace(",", "") + ("." + m.group("dec") if m.group("dec") else ""))
            kind = "usd" if m.group("usd") else "pct" if m.group("pct") else "count"
            tol = 0.5 * 10 ** -len(m.group("dec") or "")
            ok = any(abs(v - value) <= tol + 1e-9 for t in topics for v in known.get((t, kind), []))
            result.numbers.append(Found(m.group(0), kind, value, sentence, ok))
    return result


def _month(d) -> str:
    d = pd.Timestamp(d)
    return f"{MONTH_NAMES[d.month - 1]} {d.year}"


def draft(header: pd.Series, series: pd.DataFrame) -> str:
    """A plain paragraph from the review's own numbers: MRR trend, biggest move, recent leads, measurements,
    tickets, health. Each sentence quotes one topic, so `check` can hold it to that topic's facts."""
    w = windows(series)
    s = w["all"]
    first, last = s["month"].iloc[0], s["month"].iloc[-1]
    start, end = float(s["mrr"].iloc[0]), float(s["mrr"].iloc[-1])
    name = header.get("company_name") or "The account"
    out = []
    if end == start:
        out.append(f"{name} ended {_month(last)} at ${end:,.0f} MRR, the same as at the end of {_month(first)}.")
    else:
        pct = f" ({abs(end - start) / start:.0%})" if start else ""
        out.append(f"{name} ended {_month(last)} at ${end:,.0f} MRR, {'up' if end > start else 'down'} "
                   f"${abs(end - start):,.0f}{pct} from ${start:,.0f} at the end of {_month(first)}.")
    moves = s[s["net_new_mrr"] != 0]
    if len(moves) > 1:
        big = moves.loc[moves["net_new_mrr"].abs().idxmax()]
        out.append(f"The largest monthly MRR change was a {'gain' if big['net_new_mrr'] > 0 else 'loss'} "
                   f"of ${abs(big['net_new_mrr']):,.0f} in {_month(big['month'])}.")
    rc, bc = int(w["recent"]["closed_leads"].sum()), int(w["before"]["closed_leads"].sum())
    if rc:
        rw = int(w["recent"]["won_leads"].sum())
        line = f"In the last {RECENT} months it closed {rc:,} homeowner leads and won {rw:,} ({rw / rc:.0%})"
        if bc:
            line += f", against {int(w['before']['won_leads'].sum()) / bc:.0%} in the {RECENT} months before"
        out.append(line + ".")
    orders, redos = int(s["measurement_orders"].sum()), int(s["redo_orders"].sum())
    if orders:
        out.append(f"It ordered {orders:,} measurement reports in {len(s)} months and asked for a redo on "
                   f"{redos:,} ({redos / orders:.0%}).")
    rt, bt = int(w["recent"]["tickets"].sum()), int(w["before"]["tickets"].sum())
    out.append(f"It opened {rt:,} support ticket{'' if rt == 1 else 's'} in the last {RECENT} months and "
               f"{bt:,} in the {RECENT} months before.")
    out.append(f"Health score: {int(header['health_score'])} ({str(header['risk_band']).replace('_', ' ')}).")
    return " ".join(out)


def checked_draft(header: pd.Series, series: pd.DataFrame) -> tuple[str, int]:
    """Draft and check; raise if any number fails, so a wrong summary never reaches the page."""
    text = draft(header, series)
    result = check(text, header, series)
    if not result.ok:
        raise ValueError(f"summary for {header.get('account_id')} failed the number check: {result.problems}")
    return text, len(result.numbers)


__all__ = ["CheckResult", "Found", "check", "checked_draft", "draft", "facts", "windows"]
