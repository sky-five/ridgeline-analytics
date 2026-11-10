"""Checks one outbound note against the facts of the lead it is for. Works on any text: drafted, edited or model.

A note fails when it:
- is outside 40 to 90 words, or doesn't greet the company by its exact name, or doesn't end with a question;
- quotes a number (digits or a word like "three") that is not one of the lead's facts or the few fixed ones a
  note needs ("first 14 days", "two weeks", "a 15-minute call");
- mentions an activity or a channel the lead has no fact for (a signed proposal when nothing was signed, a
  referral when the lead came from a trade show);
- mentions the score, a ranking or selection, or offers money, discounts or deadlines; or leaves a [placeholder].

It reads words, not meaning: "you didn't send a proposal" passes the proposal rule if the lead sent one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MIN_WORDS, MAX_WORDS = 40, 90
FIXED_NUMBERS = {14, 2, 15}  # "first 14 days", "two weeks", "15-minute call"
WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
WORD_NUMBER = re.compile(r"\b(" + "|".join(w for w in WORDS if w not in ("zero", "one")) + r")\b", re.I)
DIGITS = re.compile(r"\d+")

BANNED = {
    "mentions the score or a ranking": r"\bscor(e|ed|ing)\b|\bdecile|\branked\b|\branking\b|\bselected\b|"
                                       r"\bpredict|\bmodel\b|\blikely to (buy|pay|convert)",
    "offers money, a discount or a deadline": r"\$|%|\bdiscount|\bprice|\bpricing\b|\bfree months?\b|\bdeadline|"
                                              r"\blimited time\b|\bexpires?\b|\boffer ends\b",
    "leaves a placeholder": r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>",
}

# a mention of the left side needs the fact on the right
CLAIMS = [
    ("a signed proposal", r"\bsigned\b(?! up)|\bsignature\b", lambda f: f["signed_14d"] > 0),
    ("proposals", r"\bproposals?\b", lambda f: f["proposals_14d"] > 0),
    ("measurements", r"\bmeasurements?\b", lambda f: f["measurements_14d"] > 0),
    ("a referral", r"\breferr(al|ed)\b", lambda f: f["channel"] == "referral"),
    ("a trade show", r"\btrade show\b", lambda f: f["channel"] == "trade_show"),
    ("a supplier partner", r"\bsupplier\b", lambda f: f["channel"] == "supplier_partner"),
    ("Facebook", r"\bfacebook\b", lambda f: f["channel"] == "facebook"),
]


@dataclass
class Result:
    problems: list[str] = field(default_factory=list)
    numbers: int = 0  # how many numbers were checked

    @property
    def ok(self) -> bool:
        return not self.problems


def allowed_numbers(f: dict) -> set[int]:
    crew = {int(x) for x in DIGITS.findall(f["crew_size"])}
    counts = {f[k] for k in ("measurements_14d", "proposals_14d", "signed_14d", "logins_14d", "active_days_14d",
                             "days_since_signup")}
    week1 = {1} if f["proposal_wk1"] else set()  # "sent a proposal in week 1"
    return FIXED_NUMBERS | crew | counts | week1


def check(text: str, f: dict) -> Result:
    r = Result()
    words = len(text.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        r.problems.append(f"{words} words; keep it to {MIN_WORDS}-{MAX_WORDS}")
    if f["company"] not in text:
        r.problems.append(f"does not name {f['company']!r}")
    if not text.rstrip().endswith("?"):
        r.problems.append("does not end with a question")

    allowed = allowed_numbers(f)
    # "15-minute" and "6-15" are read as their numbers; digits inside the company name are not quotes
    body = text.replace(f["company"], "")
    found = [int(n) for n in DIGITS.findall(body)] + [WORDS[w.lower()] for w in WORD_NUMBER.findall(body)]
    r.numbers = len(found)
    for n in found:
        if n not in allowed:
            r.problems.append(f"the number {n} is not one of this lead's facts")

    lower = body.lower()
    for what, pattern in BANNED.items():
        if re.search(pattern, lower):
            r.problems.append(what)
    for what, pattern, has in CLAIMS:
        if re.search(pattern, lower) and not has(f):
            r.problems.append(f"mentions {what}, which this lead has no fact for")
    return r
