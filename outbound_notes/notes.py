"""Draft every lead's note, check it, and replay recorded model drafts without a key."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from outbound_notes import check, draft, leads

RESULTS = Path(__file__).resolve().parent / "results"
TEMPLATE_FILE = "notes-template.json"


def _note(f: dict, text: str, **extra) -> dict:
    c = check.check(text, f)
    return {"account_id": f["account_id"], "company": f["company"], "facts": leads.fingerprint(f), "text": text,
            "ok": c.ok, "problems": c.problems, "numbers_checked": c.numbers, **extra}


def summary(notes: list[dict]) -> dict:
    return {"leads": len(notes), "passed": sum(n["ok"] for n in notes),
            "numbers_checked": sum(n["numbers_checked"] for n in notes),
            "words": [min(len(n["text"].split()) for n in notes), max(len(n["text"].split()) for n in notes)]
            if notes else []}


def template_notes(lead_facts: list[dict], as_of: pd.Timestamp) -> dict:
    notes = [_note(f, draft.template(f)) for f in lead_facts]
    return {"as_of": f"{as_of:%Y-%m-%d}", "drafter": "template (no model)", "summary": summary(notes),
            "notes": notes}


def record(lead_facts: list[dict], as_of: pd.Timestamp, client, pace: float = 0.0,
           sleep: Callable[[float], None] = time.sleep) -> dict:
    """One model call per lead. The checker's verdict is stored next to each draft; failing drafts are kept."""
    notes = []
    for i, f in enumerate(lead_facts):
        if i and pace:
            sleep(pace)
        d = draft.model_draft(client, f)
        notes.append(_note(f, d.pop("text"), **d))
    return {"as_of": f"{as_of:%Y-%m-%d}", "drafter": f"{client.provider}/{client.model}",
            "recorded_at": f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d}", "system_prompt": draft.SYSTEM,
            "summary": summary(notes), "notes": notes}


def rescore(recorded: dict, lead_facts: list[dict]) -> dict:
    """Re-run the checker on recorded drafts after a checker change. The model's text is kept as recorded."""
    by_id = {f["account_id"]: f for f in lead_facts}
    kept = ("account_id", "company", "facts", "text", "ok", "problems", "numbers_checked")
    out = [_note(by_id[n["account_id"]], n["text"], **{k: v for k, v in n.items() if k not in kept})
           for n in recorded["notes"]]
    return recorded | {"summary": summary(out), "notes": out}


def replay(recorded: dict, lead_facts: list[dict]) -> list[str]:
    """Problems with a recording against today's warehouse: missing leads, changed facts, or a stored verdict
    that the checker no longer agrees with. An empty list means the recording replays as committed."""
    by_id = {f["account_id"]: f for f in lead_facts}
    out = []
    if {n["account_id"] for n in recorded["notes"]} != set(by_id):
        out.append("the recorded leads are not today's top-decile call list")
    for n in recorded["notes"]:
        f = by_id.get(n["account_id"])
        if f is None:
            continue
        if leads.fingerprint(f) != n["facts"]:
            out.append(f"{n['account_id']}: facts changed since the draft was recorded")
            continue
        c = check.check(n["text"], f)
        if (c.ok, c.problems) != (n["ok"], n["problems"]):
            out.append(f"{n['account_id']}: the checker now says {c.problems or 'ok'}, "
                       f"recorded {n['problems'] or 'ok'}")
    if recorded["summary"] != summary(recorded["notes"]):
        out.append("the stored summary does not match the stored notes")
    return out


def recorded_files() -> list[Path]:
    return sorted(p for p in RESULTS.glob("notes-*.json") if p.name != TEMPLATE_FILE)


def dumps(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
