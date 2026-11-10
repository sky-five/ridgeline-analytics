"""Two drafters with one output: a short note a rep sends a new trial account.

- `template` needs no model: it picks the lead's strongest signal and writes three sentences around it.
- `model_draft` asks any analyst.llm client (Gemini's free tier in CI) for the same note from the same facts.

The rep reads either one before it goes out; `check.py` runs on both.
"""
from __future__ import annotations

import json

SYSTEM = """You draft a short outbound note from a sales rep at a roofing-software company to a roofing
contractor who started a free trial in the last few weeks. Rules:
- 40 to 90 words, plain text, no subject line, no sign-off name, no placeholders in brackets.
- Greet the company by the exact name given.
- Mention one or two things they actually did in the trial, using only the facts given. Any number you write must
  be one of the numbers in the facts.
- Do not mention a score, a model, a ranking, a decile, or that they were selected.
- Do not offer discounts, prices, free months or deadlines, and do not claim results for their business.
- End with one low-pressure question offering a 15-minute call."""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def signals(f: dict) -> list[str]:
    """One sentence per reason the score gave, in the score's order, when the facts back it; at most two."""
    out: dict[str, str] = {}
    for reason in f["reasons"]:
        if reason == "got a proposal signed" and f["signed_14d"]:
            out.setdefault("signed", "A customer has already signed one of your proposals, which is a great start.")
        elif reason in ("sent a proposal in week 1", "sent several proposals") and f["proposals_14d"]:
            out.setdefault("proposals", f"I saw you sent {_plural(f['proposals_14d'], 'proposal')} "
                                        "in your first two weeks.")
        elif reason == "ordered measurements" and f["measurements_14d"]:
            out.setdefault("measurements", f"You also ordered {_plural(f['measurements_14d'], 'measurement report')}.")
        elif reason in ("logs in often", "active on many days") and f["active_days_14d"]:
            out.setdefault("active", f"Your team was in the app on {f['active_days_14d']} of your first 14 days.")
        elif reason == "came by referral" and f["channel"] == "referral":
            out.setdefault("channel", "Thanks for coming to us through a referral.")
    return list(out.values())[:2] or ["Thanks for trying the app over the last few weeks."]


def template(f: dict) -> str:
    """The no-model draft: greeting, up to two of the lead's own signals, one question."""
    return (f"Hi {f['company']} team, {' '.join(signals(f))} "
            "If it would help, I can walk your team through anything you haven't tried yet. "
            "Would a 15-minute call this week or next be useful?")


def prompt(f: dict) -> str:
    """The user message for a model: the facts and nothing else (no score, no account id)."""
    shown = {k: v for k, v in f.items() if k not in ("account_id", "channel")}
    return "Facts about this trial account:\n" + json.dumps(shown, indent=2) + "\n\nWrite the note."


def model_draft(client, f: dict) -> dict:
    """One model call, no tools. Returns the note and what produced it."""
    reply = client.complete(SYSTEM, [{"role": "user", "content": prompt(f)}], [])
    return {"text": (reply.text or "").strip(), "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens, "stop": reply.stop}
