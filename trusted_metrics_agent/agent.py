"""An agent that answers HR and payroll questions only through the trusted-metrics MCP server.

    python -m trusted_metrics_agent.agent --role people_manager "What was attrition in Sales in September 2026?"
    python -m trusted_metrics_agent.agent --role finance --provider gemini "Payroll cost in August 2026?"

The agent starts `python -m trusted_metrics_agent.server --role <role>` as a subprocess and talks to it over
stdio, as any MCP client would. Its tools are the server's three (list_metrics, describe_metric,
query_metric), with the names, descriptions and inputs the server lists. It has no SQL and no way to change
its role: the server fixes the role when it starts.

After the model answers, `check` holds the answer back unless:
- it cites at least one metric definition (`trusted_metrics_agent/metrics.yml#<metric>`), and only
  definitions a query_metric result in this conversation came from, and
- every number in the answer appears in a tool result (a share may be given as a percent).
A reply that says the role cannot see something is a decline, and carries no value.

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
from trusted_metrics_agent.load import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[1]
MAX_TURNS = 6
MAX_TOKENS = 60_000
SOURCE = re.compile(r"^trusted_metrics_agent/metrics\.yml#\w+$")

SYSTEM = """You answer HR and payroll questions for Ridgeline, a software company of about 300 people. All \
data is synthetic. You work for one person, whose role the metrics server fixed when it started: {role}.

Use only the tools. Start with list_metrics to see what this role may query. Every query_metric result \
names the governed definition it came from (source, e.g. trusted_metrics_agent/metrics.yml#headcount).

Rules:
- Answer with a value exactly as query_metric returned it. Do not add, average, compare by subtraction, \
forecast or estimate. Shares are fractions (0.1909 is 19.09%). Money is USD. Months are YYYY-MM.
- If a tool says "declined", or the metric or breakdown is not in this role's list, decline: say the role \
cannot see it. Do not try another way to get the same number.
- If the metrics can't answer the question (individual people, other data, forecasts, reasons, changes to \
data), refuse. Do not guess.

End your reply with one fenced json block, and nothing after it:
```json
{{"answer": <value exactly as a tool returned it, or text; null when you decline or refuse>,
 "unit": "<people | share | months | usd | text>",
 "sources": ["<the source of every result the answer came from>"],
 "declined": <true if the role may not see it, else false>,
 "refused": <true if the metrics can't answer it, else false>,
 "note": "<one short sentence>"}}
```"""


def plain_schema(schema: dict) -> dict:
    """The server's JSON schema in the small subset every provider accepts: optional inputs ("X or null")
    become X, and titles, defaults and additionalProperties are dropped. Required inputs stay required."""
    if not isinstance(schema, dict):
        return schema
    if "anyOf" in schema:
        kinds = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(kinds) == 1:
            return plain_schema(kinds[0])
    out = {k: v for k, v in schema.items() if k not in ("title", "default", "additionalProperties")}
    if "properties" in out:
        out["properties"] = {k: plain_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = plain_schema(out["items"])
    return out


class McpTools:
    """The server's tools as plain Python callables, over a stdio MCP session held open in a background
    event loop. Use as a context manager; one instance is one server process with one role."""

    def __init__(self, role: str, db: Path = DEFAULT_DB):
        self.role, self.db = role, Path(db)
        self._stack = ExitStack()
        self.specs: dict[str, dict] = {}

    def __enter__(self) -> McpTools:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=sys.executable, cwd=str(ROOT),
            args=["-m", "trusted_metrics_agent.server", "--role", self.role, "--db", str(self.db.resolve())])
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
        """One tool call. The server's {"error"} and {"declined"} replies come back as they are."""
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
    """Numbers in a tool result or an answer, rounded to 6 places. Months (2026-09) are not numbers."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, int | float):
        return {round(float(value), 6)}
    if isinstance(value, dict):
        return set().union(*(_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_numbers(v) for v in value)) if value else set()
    text = re.sub(r"\b\d{4}-\d{2}(-\d{2})?\b|#\w+", " ", str(value))
    return {round(float(m.replace("$", "").replace(",", "")), 6) for m in _NUM.findall(text)}


@dataclass
class Checked:
    delivered: dict | None  # what the person sees: the parsed answer, or None when declined, refused or held back
    declined: bool
    refused: bool
    held_back: str | None  # why the check stopped an answer, if it did


def check(text: str, tool_results: list[dict]) -> Checked:
    """Deliver the answer only if it cites definitions a query read and every number came from a tool."""
    ans = parse_answer(text)
    if ans is None:
        return Checked(None, False, False, "no answer block")
    if ans.get("declined"):
        return Checked(None, True, False, None)
    if ans.get("refused") or ans.get("answer") is None:
        return Checked(None, False, True, None)
    read = {r["source"] for r in tool_results if "rows" in r and "source" in r}
    cited = [s for s in ans.get("sources") or [] if isinstance(s, str)]
    if not cited:
        return Checked(None, False, False, "no definition cited")
    if not set(cited) <= read:
        return Checked(None, False, False, f"cites {sorted(set(cited) - read)} but no query returned it")
    seen = _numbers(tool_results)
    made_up = sorted(n for n in _numbers(ans["answer"]) if n not in seen and round(n / 100, 6) not in seen)
    if made_up:
        return Checked(None, False, False, f"numbers not in any tool result: {made_up}")
    return Checked(ans, False, False, None)


@dataclass
class Answer:
    question: str
    role: str
    text: str
    delivered: dict | None
    declined: bool
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

    r = llm.run(question, ServerSpecs(), [tool(n) for n in tools.specs], SYSTEM.format(role=tools.role),
                MAX_TURNS, MAX_TOKENS)
    c = check(r.text, results)
    return Answer(question, tools.role, r.text, c.delivered, c.declined, c.refused, c.held_back, calls, results,
                  r.turns, r.input_tokens, r.output_tokens, r.stopped)


def render(a: Answer) -> str:
    if a.delivered is not None:
        d = a.delivered
        return f"{d['answer']} {d.get('unit') or ''}".rstrip() + f"  (definition: {', '.join(d['sources'])})"
    if a.declined:
        return f"Declined: the {a.role} role cannot see that."
    if a.refused:
        return "Refused: the governed HR metrics don't answer that."
    return f"Held back: {a.held_back}."


def main() -> None:
    from trusted_metrics_agent.agent_baseline import KeywordClient

    p = argparse.ArgumentParser(prog="python -m trusted_metrics_agent.agent")
    p.add_argument("question", nargs="+")
    p.add_argument("--role", default="all_staff")
    p.add_argument("--provider", choices=["baseline", *sorted(llm.PROVIDERS)], default="baseline")
    p.add_argument("--model", default=None)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--json", action="store_true", help="print the whole record")
    args = p.parse_args()
    client = KeywordClient() if args.provider == "baseline" else llm.make_client(args.provider, args.model)
    with McpTools(args.role, args.db) as tools:
        a = ask(" ".join(args.question), client, tools)
    print(json.dumps(a.to_dict(), indent=2, default=str) if args.json else render(a))
    sys.exit(0 if a.delivered is not None else 1)


if __name__ == "__main__":
    main()
