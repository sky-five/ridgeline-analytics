"""An analyst agent that answers vehicle-sales and incentive questions only through the metric registry's
MCP server, and returns the SQL behind each answer.

    python -m metric_registry.agent "What is our incentive spend per unit on electric vehicles?"
    python -m metric_registry.agent --provider gemini "What was revenue in the west region?"

The agent starts `python -m metric_registry.server` as a subprocess and talks to it over stdio, as any MCP
client would. Its tools are the server's three (list_metrics, explain_metric, query_metrics), with the
names, descriptions and inputs the server lists. It has no SQL tool, so it cannot pick its own definition.

After the model answers, `check` holds the answer back unless:
- it cites at least one registry metric, and only metrics a query_metrics result in this conversation
  returned, and
- every number in the answer appears in a tool result (rounded to the dollar or given as a percent is fine).
A delivered answer carries its lineage: the SQL MetricFlow ran for every query that returned a cited metric.

The model client is analyst/llm.py's (Gemini's free tier, Claude, or the no-model baseline in
agent_baseline.py). Caps: MAX_TURNS model calls and MAX_TOKENS tokens per question.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path

from anyio.from_thread import start_blocking_portal

from analyst import llm
from analyst.prompt import parse_answer
from metric_registry.load import DEFAULT_DB
from trusted_metrics_agent.agent import plain_schema

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 6
MAX_TOKENS = 60_000

SYSTEM = """You answer questions about vehicle sales and incentive programs for a group of 40 car dealers. \
All data is synthetic and runs from 2025-01-01 to 2026-06-30.

Use only the tools. list_metrics shows every governed metric, what each may be grouped and filtered by, and \
the values the filters take; explain_metric gives a metric's registry definition; query_metrics returns \
values and the SQL that produced them.

Rules:
- Pick the governed metric whose definition fits the question, and answer with a value exactly as \
query_metrics returned it. Do not add, average, subtract, forecast or estimate. Shares are fractions \
(0.0533 is 5.33%). Money is USD.
- Filter or group to get exactly the slice asked about (a segment, region, finance type, program type, \
quarter end, returning customers, or a date range).
- If no metric answers the question (other data, forecasts, people, reasons, changes to data), refuse. \
Do not guess.

End your reply with one fenced json block, and nothing after it:
```json
{"answer": <value exactly as a tool returned it, or null when you refuse>,
 "unit": "<usd | count | share | text>",
 "metrics": ["<every metric the answer came from>"],
 "refused": <true or false>,
 "note": "<one short sentence>"}
```"""


class McpTools:
    """The server's tools as plain Python callables, over a stdio MCP session held open in a background
    event loop. Use as a context manager; one instance is one server process."""

    def __init__(self, db: Path = DEFAULT_DB):
        self.db = Path(db)
        self._stack = ExitStack()
        self.specs: dict[str, dict] = {}

    def __enter__(self) -> McpTools:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(command=sys.executable, cwd=str(ROOT),
                                       args=["-m", "metric_registry.server", "--db", str(self.db.resolve())])
        try:
            self._portal = self._stack.enter_context(start_blocking_portal())
            errlog = self._stack.enter_context(open(os.devnull, "w"))  # the server's own request log
            read, write = self._stack.enter_context(
                self._portal.wrap_async_context_manager(stdio_client(params, errlog=errlog)))
            self._session = self._stack.enter_context(
                self._portal.wrap_async_context_manager(ClientSession(read, write)))
            self._portal.call(self._session.initialize)
            listed = self._portal.call(self._session.list_tools).tools
        except BaseException:
            self._stack.close()
            raise
        self.specs = {t.name: {"name": t.name, "description": " ".join((t.description or "").split()),
                               "parameters": plain_schema(t.input_schema)} for t in listed}
        return self

    def __exit__(self, *exc) -> None:
        self._stack.close()

    def call(self, name: str, arguments: dict) -> dict:
        if name not in self.specs:
            return {"error": f"unknown tool {name}; available: {', '.join(self.specs)}"}
        res = self._portal.call(self._session.call_tool, name, arguments)
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": text.strip() or "empty tool result"}  # e.g. arguments the server's schema rejects


# ---- the check between the model's answer and the person asking

_NUM = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?")


def _numbers(value) -> set[float]:
    """Numbers in a tool result or an answer. Dates (2026-06-30), quarters (2026-Q1) and the SQL are not."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int | float):
        return {round(float(value), 6)}
    if isinstance(value, dict):
        vals = [v for k, v in value.items() if k != "sql"]
        return set().union(*(_numbers(v) for v in vals)) if vals else set()
    if isinstance(value, list):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    text = re.sub(r"\b\d{4}-(\d{2}(-\d{2})?|Q[1-4])\b", " ", str(value))
    return {round(float(m.replace("$", "").replace(",", "")), 6) for m in _NUM.findall(text)}


def _seen(tool_results: list[dict]) -> set[float]:
    """Every number a tool returned, plus each rounded to the dollar and to 2 places, and shares as percents."""
    out = set()
    for n in _numbers(tool_results):
        out |= {n, round(n), round(n, 2)}
        if abs(n) <= 1:
            out |= {round(n * 100, 6), round(n * 100, 2), round(n * 100, 1)}
    return {round(float(n), 6) for n in out}


def lineage(tool_results: list[dict], cited: list[str]) -> list[dict]:
    """The SQL of every query that returned a cited metric: where the answer's number came from."""
    return [{"metrics": sorted(r["metrics"]), "sql": r["sql"]} for r in tool_results
            if isinstance(r.get("metrics"), dict) and "sql" in r and set(cited) & set(r["metrics"])]


@dataclass
class Checked:
    delivered: dict | None  # what the person sees: the parsed answer and its lineage, or None
    refused: bool
    held_back: str | None  # why the check stopped an answer, if it did


def check(text: str, tool_results: list[dict]) -> Checked:
    """Deliver the answer only if it cites metrics a query returned and every number came from a tool."""
    ans = parse_answer(text)
    if ans is None:
        return Checked(None, False, "no answer block")
    if ans.get("refused") or ans.get("answer") is None:
        return Checked(None, True, None)
    queried = {m for r in tool_results if "sql" in r and isinstance(r.get("metrics"), dict) for m in r["metrics"]}
    cited = [m for m in ans.get("metrics") or [] if isinstance(m, str)]
    if not cited:
        return Checked(None, False, "no metric cited")
    if not set(cited) <= queried:
        return Checked(None, False, f"cites {sorted(set(cited) - queried)} but no query returned it")
    made_up = sorted(n for n in _numbers(ans["answer"]) if n not in _seen(tool_results))
    if made_up:
        return Checked(None, False, f"numbers not in any tool result: {made_up}")
    return Checked({**ans, "lineage": lineage(tool_results, cited)}, False, None)


@dataclass
class Answer:
    question: str
    text: str
    delivered: dict | None
    refused: bool
    held_back: str | None
    tool_calls: list[dict]
    tool_results: list[dict]
    turns: int
    input_tokens: int
    output_tokens: int
    stopped: str

    def to_dict(self) -> dict:
        return asdict(self)


def ask(question: str, client: llm.Client, tools: McpTools) -> Answer:
    """One question through the loop (every tool call goes to the MCP server), then the check."""
    results: list[dict] = []
    calls: list[dict] = []

    class ServerSpecs:  # the model sees the server's own tool specs, not ones made from Python signatures
        provider, model = client.provider, client.model

        def complete(self, system, messages, _specs):
            return client.complete(system, messages, list(tools.specs.values()))

    def tool(name):
        def fn(**kw):
            out = tools.call(name, kw)
            calls.append({"name": name, "arguments": kw})
            results.append(out)
            return out
        fn.__name__ = name
        return fn

    r = llm.run(question, ServerSpecs(), [tool(n) for n in tools.specs], SYSTEM, MAX_TURNS, MAX_TOKENS)
    c = check(r.text, results)
    return Answer(question, r.text, c.delivered, c.refused, c.held_back, calls, results, r.turns,
                  r.input_tokens, r.output_tokens, r.stopped)


def render(a: Answer, sql: bool = False) -> str:
    if a.delivered is not None:
        d = a.delivered
        out = f"{d['answer']} {d.get('unit') or ''}".rstrip() + f"  (metric: {', '.join(d['metrics'])})"
        if sql:
            out += "".join(f"\n\n-- {', '.join(q['metrics'])}\n{q['sql']}" for q in d["lineage"])
        return out
    if a.refused:
        return "Refused: no governed metric answers that."
    return f"Held back: {a.held_back}."


def main() -> None:
    from metric_registry.agent_baseline import KeywordClient

    p = argparse.ArgumentParser(prog="python -m metric_registry.agent")
    p.add_argument("question", nargs="+")
    p.add_argument("--provider", choices=["baseline", *sorted(llm.PROVIDERS)], default="baseline")
    p.add_argument("--model", default=None)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--sql", action="store_true", help="print the SQL behind the answer")
    p.add_argument("--json", action="store_true", help="print the whole record")
    args = p.parse_args()
    client = KeywordClient() if args.provider == "baseline" else llm.make_client(args.provider, args.model)
    with McpTools(args.db) as tools:
        a = ask(" ".join(args.question), client, tools)
    print(json.dumps(a.to_dict(), indent=2, default=str) if args.json else render(a, args.sql))
    sys.exit(0 if a.delivered is not None else 1)


if __name__ == "__main__":
    main()
