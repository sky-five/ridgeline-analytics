"""A seeded, simulated lead-generation operation for four home-service clients, 2026-04-01 to 2026-06-30.

Each client runs campaigns on two ad platforms (search and social). A click can turn into a lead by web form or by
phone call; the call-tracking tool gives each campaign its own tracking number and records the click id when the
caller came from the website. Leads are worked in the CRM: new, then rejected or issued (sent to the client's
sales rep with an appointment), and an issued lead becomes a demo when the rep runs the in-home presentation.

The exports arrive as files, the way the three systems deliver them, each with a declared row count in its
manifest (`deliveries`):

- `search_spend`: one file a day with the last three days, because the platform restates recent spend; spend in
  micros, campaign named "North Roofing - Roof Repair";
- `social_spend`: one file a day for that day only, spend in dollars, campaign named "NORTH_ROOFING_ROOF-REPAIR"
  (sometimes with a trailing space); the 2026-05-14 file is delivered twice;
- `search_clicks`, `social_clicks`: one file a day, one row per click id;
- `calls`: one file a day from call tracking, caller number as +1XXXXXXXXXX, click id when known;
- `tracking_numbers`: one file, tracking number "(XXX) XXX-XXXX" to platform and campaign label;
- `crm_leads`: one file a day with every CRM record created or changed that day (the latest row wins).

Messy on purpose: phone numbers typed four ways, emails in mixed case, click ids sometimes stored as
"gclid=..." in the CRM, campaign names spelled differently by every tool. A person who fills in the form and
also calls gets two CRM records (and a few submit the form twice); 7% of form leads lose their click id. Some
calls and forms come from people who never clicked an ad (organic): they cost nothing and belong to no campaign.

`truth` keeps, per person, the campaign they really came from and whether they were issued and had a demo, so
tests can check what the pipeline gets right and what it can't know.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

SEED = 521
FIRST_DAY, AS_OF = date(2026, 4, 1), date(2026, 6, 30)
CLIENTS = {  # client key -> (label, area code)
    "north_roofing": ("North Roofing", "416"),
    "lakeside_hvac": ("Lakeside HVAC", "905"),
    "metro_plumbing": ("Metro Plumbing", "647"),
    "valley_solar": ("Valley Solar", "519"),
}
# (client, platform, theme, clicks a weekday, cost per click, lead rate per click, issue rate, demo rate)
CAMPAIGNS = [
    ("north_roofing", "search", "Roof Repair", 34, 9.40, 0.085, 0.55, 0.62),
    ("north_roofing", "search", "Roof Replacement", 22, 14.80, 0.070, 0.62, 0.70),
    ("north_roofing", "social", "Roof Repair", 90, 1.70, 0.022, 0.35, 0.48),
    ("lakeside_hvac", "search", "AC Tune Up", 40, 6.10, 0.090, 0.50, 0.55),
    ("lakeside_hvac", "search", "Furnace Replacement", 18, 11.20, 0.075, 0.60, 0.66),
    ("lakeside_hvac", "social", "AC Tune Up", 110, 1.20, 0.020, 0.30, 0.45),
    ("metro_plumbing", "search", "Emergency Plumber", 48, 7.60, 0.110, 0.58, 0.52),
    ("metro_plumbing", "social", "Water Heater", 70, 1.50, 0.025, 0.40, 0.50),
    ("valley_solar", "search", "Solar Panels", 26, 12.90, 0.050, 0.45, 0.58),
    ("valley_solar", "social", "Solar Panels", 140, 1.10, 0.018, 0.25, 0.40),
    ("valley_solar", "social", "Home Battery", 60, 1.40, 0.015, 0.28, 0.42),
]
WEEKDAY = [1.15, 1.10, 1.05, 1.00, 0.95, 0.80, 0.70]  # Monday .. Sunday
FORM_SHARE = 0.6  # of paid leads; the rest call
LOST_CLICK_ID = 0.07  # form leads whose click id never reaches the CRM
CLICK_ID_AS_PARAM = 0.15  # form leads whose click id is stored as "gclid=..." / "fbclid=..."
FORM_ALSO_CALLS = 0.12  # form leads who also phone; the agent opens a second CRM record
DOUBLE_SUBMIT = 0.05  # form leads who submit twice
CALL_HAS_CLICK_ID = 0.85  # calls from the website where call tracking knows the click id
SHORT_CALL = 0.15  # calls under 30 s never become a CRM record
ORGANIC_A_DAY = (2.5, 1.5)  # per client: calls and forms from people who never clicked an ad
ORGANIC_ISSUE, ORGANIC_DEMO = 0.45, 0.55
RESTATE_DAYS = 3  # each search spend file carries this many days
DOUBLE_DELIVERED = ("social_spend", date(2026, 5, 14))
CLICK_PARAM = {"search": "gclid", "social": "fbclid"}


def campaign_id(client: str, platform: str, theme: str) -> str:
    return f"{client}__{platform}__{theme.lower().replace(' ', '_')}"


@dataclass
class Delivery:
    source: str
    file: str
    delivered_at: datetime
    rows: pd.DataFrame
    declared_rows: int


@dataclass
class World:
    deliveries: list[Delivery]
    truth: pd.DataFrame  # one row per person-lead
    spend: pd.DataFrame  # final spend per campaign and day
    campaigns: pd.DataFrame
    meta: dict = field(default_factory=dict)


def _days() -> list[date]:
    return [d.date() for d in pd.date_range(FIRST_DAY, AS_OF, freq="D")]


def _phone_digits(rng, area: str) -> str:
    return area + "555" + f"{rng.integers(0, 10_000):04d}"


def phone_as_typed(rng, digits: str) -> str:
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return [f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"+1 {a} {b} {c}", digits][rng.integers(0, 4)]


def _email(rng, n: int) -> str:
    name = f"homeowner{n:05d}@example.com"
    return name.upper() if rng.random() < 0.15 else (name.capitalize() + " " if rng.random() < 0.1 else name)


def _click_id(rng) -> str:
    return "".join(rng.choice(list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"), 14))


def spend_name(platform: str, client: str, theme: str) -> str:
    label = CLIENTS[client][0]
    if platform == "search":
        return f"{label} - {theme}"
    return f"{label}_{theme}".upper().replace(" ", "_", 1).replace(" ", "-")


def simulate() -> World:
    rng = np.random.default_rng(SEED)
    days = _days()
    campaigns = pd.DataFrame([{"campaign_id": campaign_id(c, p, t), "client": c, "platform": p, "theme": t}
                              for c, p, t, *_ in CAMPAIGNS])
    used_phones: set[str] = set()

    def new_phone(area: str) -> str:
        while True:
            d = _phone_digits(rng, area)
            if d not in used_phones:
                used_phones.add(d)
                return d

    spend_rows, clicks, calls, crm, people = [], [], [], [], []
    n_person = n_record = n_call = 0

    def add_person(client, cid, at: datetime, issue_p, demo_p, via_form, click_id, platform):
        nonlocal n_person
        n_person += 1
        area = CLIENTS[client][1]
        digits = new_phone(area)
        email = _email(rng, n_person)
        issued = rng.random() < issue_p
        demo = issued and rng.random() < demo_p
        # the outcome lands on the first record, a few days after the lead came in; later days stay unseen
        issued_at = at + timedelta(days=int(rng.integers(1, 4)), hours=int(rng.integers(1, 8)))
        demo_at = issued_at + timedelta(days=int(rng.integers(2, 11)))
        rejected_at = at + timedelta(days=int(rng.integers(1, 3)))
        end = datetime.combine(AS_OF, datetime.max.time())
        records = []

        def record(source, created, cl_raw, phone_raw):
            nonlocal n_record
            n_record += 1
            records.append({"crm_id": f"L{n_record:06d}", "client": client, "source": source, "created_at": created,
                            "phone": phone_raw, "email": email if source == "web_form" else None,
                            "click_id": cl_raw})

        def call(started, with_click) -> bool:
            nonlocal n_call
            n_call += 1
            calls.append({"call_id": "", "started_at": started, "caller": "+1" + digits,
                          "tracking_number": tracking[cid] if cid else main_line[client],
                          "duration_s": int(rng.integers(45, 900)), "click_id": click_id if with_click else None})
            return with_click

        call_click = False
        if via_form:
            raw = None
            if click_id and rng.random() >= LOST_CLICK_ID:
                raw = f"{CLICK_PARAM[platform]}={click_id}" if rng.random() < CLICK_ID_AS_PARAM else click_id
            record("web_form", at, raw, phone_as_typed(rng, digits))
            if rng.random() < DOUBLE_SUBMIT:
                record("web_form", at + timedelta(minutes=int(rng.integers(1, 20))), raw, phone_as_typed(rng, digits))
            if rng.random() < FORM_ALSO_CALLS:
                t = at + timedelta(minutes=int(rng.integers(10, 600)))
                call_click = call(t, click_id is not None and rng.random() < CALL_HAS_CLICK_ID)
                record("phone", t + timedelta(minutes=5), None, phone_as_typed(rng, digits))
        else:
            call_click = call(at, click_id is not None and rng.random() < CALL_HAS_CLICK_ID)
            record("phone", at + timedelta(minutes=5), None, phone_as_typed(rng, digits))
        first = records[0]
        status_changes = [("new", first["created_at"])]
        if issued:
            status_changes.append(("issued", issued_at))
            if demo:
                status_changes.append(("demo_done", demo_at))
        elif rng.random() < 0.8:
            status_changes.append(("rejected", rejected_at))
        seen = [(s, t) for s, t in status_changes if t <= end]
        for r in records:
            crm.append({**r, "status": "new", "updated_at": r["created_at"]})
        for s, t in seen[1:]:
            crm.append({**first, "status": s, "updated_at": t})
        people.append({"person": n_person, "client": client, "campaign_id": cid, "phone": digits,
                       "came_by": "form" if via_form else "call", "first_at": at,
                       "click_id_reaches_crm": bool(records[0]["click_id"]),
                       "call_has_click_id": call_click,
                       "issued": seen[-1][0] in ("issued", "demo_done"), "demo": seen[-1][0] == "demo_done",
                       "crm_records": len(records)})

    tracking = {}
    for i, (c, p, t, *_) in enumerate(CAMPAIGNS):
        tracking[campaign_id(c, p, t)] = CLIENTS[c][1] + "555" + f"{2000 + i:04d}"
    main_line = {c: area + "5550100" for c, (_, area) in CLIENTS.items()}

    for day in days:
        wd = WEEKDAY[day.weekday()]
        for c, p, t, base, cpc, lead_rate, issue_p, demo_p in CAMPAIGNS:
            cid = campaign_id(c, p, t)
            n = int(rng.poisson(base * wd))
            cost = round(float(n * cpc * rng.lognormal(0, 0.08)), 2)
            spend_rows.append({"day": day, "campaign_id": cid, "platform": p, "clicks": n,
                               "impressions": int(n * (rng.uniform(18, 40) if p == "search" else rng.uniform(60, 120))),
                               "spend": cost})
            for _ in range(n):
                at = datetime.combine(day, datetime.min.time()) + timedelta(seconds=int(rng.integers(6 * 3600,
                                                                                                   23 * 3600)))
                cl = _click_id(rng)
                clicks.append({"platform": p, "click_id": cl, "clicked_at": at, "campaign_id": cid})
                if rng.random() < lead_rate:
                    via_form = rng.random() < FORM_SHARE
                    if not via_form and rng.random() < SHORT_CALL:
                        n_call_short(calls, rng, at, cl, tracking[cid], c)
                        continue
                    add_person(c, cid, at + timedelta(minutes=int(rng.integers(1, 30))), issue_p, demo_p, via_form,
                               cl, p)
        for c in CLIENTS:
            for via_form, lam in ((False, ORGANIC_A_DAY[0]), (True, ORGANIC_A_DAY[1])):
                for _ in range(int(rng.poisson(lam * wd))):
                    at = datetime.combine(day, datetime.min.time()) + timedelta(seconds=int(rng.integers(7 * 3600,
                                                                                                       21 * 3600)))
                    add_person(c, None, at, ORGANIC_ISSUE, ORGANIC_DEMO, via_form, None, None)

    spend = pd.DataFrame(spend_rows)
    clicks_df = pd.DataFrame(clicks)
    calls_df = pd.DataFrame(calls).sort_values("started_at", kind="stable").reset_index(drop=True)
    calls_df["call_id"] = [f"C{i + 1:06d}" for i in range(len(calls_df))]
    crm_df = pd.DataFrame(crm).sort_values(["updated_at", "crm_id"], kind="stable").reset_index(drop=True)
    truth = pd.DataFrame(people)
    deliveries = _deliveries(rng, spend, clicks_df, calls_df, crm_df, tracking, campaigns)
    return World(deliveries, truth, spend, campaigns,
                 {"tracking": tracking, "main_line": main_line, "clicks": len(clicks_df), "calls": len(calls_df),
                  "crm_rows": len(crm_df)})


def n_call_short(calls, rng, at, click_id, number, client):
    """A caller who hangs up within 30 s: call tracking keeps it, nobody opens a CRM record."""
    digits = CLIENTS[client][1] + "556" + f"{rng.integers(0, 10_000):04d}"
    calls.append({"call_id": "", "started_at": at + timedelta(minutes=int(rng.integers(1, 30))),
                  "caller": "+1" + digits, "tracking_number": number, "duration_s": int(rng.integers(3, 30)),
                  "click_id": click_id if rng.random() < CALL_HAS_CLICK_ID else None})


def _file(source: str, day: date, delivered: datetime, df: pd.DataFrame) -> Delivery:
    return Delivery(source, f"{source}_{day:%Y%m%d}.csv", delivered, df.reset_index(drop=True), len(df))


def _deliveries(rng, spend, clicks, calls, crm, tracking, campaigns) -> list[Delivery]:
    out: list[Delivery] = []
    theme = campaigns.set_index("campaign_id")
    name = {(p, r.campaign_id): spend_name(p, r.client, r.theme) for r in campaigns.itertuples()
            for p in ("search", "social")}
    days = _days()
    for day in days:
        at = datetime.combine(day + timedelta(days=1), datetime.min.time()) + timedelta(hours=6)
        # search: the last three days, earlier days restated by a little (the last file's value is final)
        window = spend[(spend["platform"] == "search") & (spend["day"] > day - timedelta(days=RESTATE_DAYS))
                       & (spend["day"] <= day)]
        rows = []
        for r in window.itertuples():
            age = (day - r.day).days
            factor = 1.0 if age == min(RESTATE_DAYS - 1, (AS_OF - r.day).days) else float(rng.uniform(0.93, 0.99))
            rows.append({"date": r.day.isoformat(), "campaign_name": name["search", r.campaign_id],
                         "impressions": r.impressions, "clicks": r.clicks,
                         "cost_micros": int(round(r.spend * factor * 1_000_000))})
        out.append(_file("search_spend", day, at, pd.DataFrame(rows)))
        today = spend[(spend["platform"] == "social") & (spend["day"] == day)]
        rows = []
        for r in today.itertuples():
            label = name["social", r.campaign_id] + (" " if rng.random() < 0.1 else "")
            rows.append({"date_start": r.day.strftime("%m/%d/%Y"), "campaign": label, "impressions": r.impressions,
                         "link_clicks": r.clicks, "amount_spent": f"{r.spend:.2f}"})
        d = _file("social_spend", day, at + timedelta(minutes=20), pd.DataFrame(rows))
        out.append(d)
        if (d.source, day) == DOUBLE_DELIVERED:
            out.append(Delivery(d.source, d.file, at + timedelta(hours=3), d.rows.copy(), d.declared_rows))
        for p in ("search", "social"):
            c = clicks[(clicks["platform"] == p) & (clicks["clicked_at"].dt.date == day)]
            names = [name[p, i] for i in c["campaign_id"]]
            out.append(_file(f"{p}_clicks", day, at + timedelta(minutes=40),
                             pd.DataFrame({"click_id": c["click_id"].values, "clicked_at": c["clicked_at"].values,
                                           "campaign_name": names})))
        cl = calls[calls["started_at"].dt.date == day]
        out.append(_file("calls", day, at + timedelta(minutes=50), cl))
        cr = crm[crm["updated_at"].dt.date == day]
        out.append(_file("crm_leads", day, at + timedelta(minutes=55), cr))
    tn = [{"tracking_number": f"({n[:3]}) {n[3:6]}-{n[6:]}", "platform": theme.loc[cid, "platform"].capitalize(),
           "campaign_label": f"{CLIENTS[theme.loc[cid, 'client']][0]} | {theme.loc[cid, 'theme']}"}
          for cid, n in tracking.items()]
    out.append(_file("tracking_numbers", FIRST_DAY, datetime.combine(FIRST_DAY, datetime.min.time()), pd.DataFrame(tn)))
    return sorted(out, key=lambda d: d.delivered_at)
