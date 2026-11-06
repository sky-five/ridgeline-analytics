"""Failure alerting for the DAG: one JSON line per failed task, plus an optional webhook.

Airflow calls `on_failure(context)` when a task fails for good (after its retries). The alert always goes
to an append-only JSON-lines file, so a failure is visible without any outside service. If
RIDGELINE_ALERT_WEBHOOK is set, the same payload is POSTed there as JSON (a chat or paging webhook).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_ALERTS = Path(__file__).resolve().parent.parent / "warehouse" / "alerts.jsonl"


def build_alert(context: dict[str, Any]) -> dict[str, Any]:
    ti = context.get("task_instance") or context.get("ti")
    exc = context.get("exception")
    logical = context.get("logical_date")
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dag_id": getattr(ti, "dag_id", None),
        "task_id": getattr(ti, "task_id", None),
        "run_id": context.get("run_id") or getattr(ti, "run_id", None),
        "logical_date": logical.isoformat() if hasattr(logical, "isoformat") else logical,
        "try_number": getattr(ti, "try_number", None),
        "error": f"{type(exc).__name__}: {exc}"[:500] if exc is not None else None,
    }


def send(alert: dict[str, Any], path: Path | None = None, webhook: str | None = None, timeout: float = 10) -> None:
    path = Path(os.environ.get("RIDGELINE_ALERTS_FILE", DEFAULT_ALERTS)) if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(alert, sort_keys=True) + "\n")
    webhook = os.environ.get("RIDGELINE_ALERT_WEBHOOK") if webhook is None else webhook
    if webhook:
        req = urllib.request.Request(webhook, data=json.dumps(alert).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=timeout).close()
        except OSError as e:  # never let a broken webhook hide the original failure
            print(f"alert webhook failed: {e}")


def on_failure(context: dict[str, Any]) -> None:
    alert = build_alert(context)
    print("ALERT", json.dumps(alert, sort_keys=True))
    send(alert)
