"""The analyst as a Claude API agent: same tools and instructions as the MCP server, with spending caps.

    python -m analyst.agent "What was MRR at the end of September 2026?"

Needs Anthropic credentials (ANTHROPIC_API_KEY or `ant auth login`). Caps: at most MAX_TURNS model calls
and MAX_TOKENS input+output tokens per question; the run stops cleanly when either is reached.
"""
import json
import sys
from dataclasses import dataclass, field

import anthropic
from anthropic import beta_tool

from analyst import tools
from analyst.prompt import SYSTEM, parse_answer

MODEL = "claude-opus-5-5"
MAX_TURNS = 12
MAX_TOKENS = 300_000


@beta_tool
def search_catalog(query: str) -> str:
    """Find marts, models and governed metrics related to a question. Start here.

    Args:
        query: A few words from the question, e.g. "churned mrr" or "lead close rate".
    """
    return json.dumps(tools.search_catalog(query))


@beta_tool
def describe_model(name: str) -> str:
    """Columns, description, tests, contract and direct parents/children of one dbt model.

    Args:
        name: Model name, e.g. fct_mrr_daily.
    """
    return json.dumps(tools.describe_model(name))


@beta_tool
def get_lineage(name: str, direction: str = "upstream") -> str:
    """Every model and source a model is built from (upstream) or feeds (downstream).

    Args:
        name: Model name, e.g. fct_mrr_daily.
        direction: "upstream" or "downstream".
    """
    return json.dumps(tools.get_lineage(name, direction))


@beta_tool
def list_metrics() -> str:
    """The governed metrics (MetricFlow): name, definition and the mart each is built on."""
    return json.dumps(tools.list_metrics())


@beta_tool
def query_metric(metrics: list[str], group_by: list[str] | None = None, where: list[str] | None = None,
                 order_by: list[str] | None = None, limit: int | None = None) -> str:
    """Query governed metrics through MetricFlow; returns the compiled SQL and the rows.

    Args:
        metrics: Metric names from list_metrics, e.g. ["mrr"].
        group_by: MetricFlow names, e.g. ["metric_time__month"] or ["account__channel"].
        where: Jinja filters, e.g. ["{{ TimeDimension('metric_time', 'day') }} >= '2026-01-01'"].
        order_by: e.g. ["-metric_time__month"] for newest first.
        limit: Maximum rows.
    """
    return json.dumps(tools.query_metric(metrics, group_by, where, order_by, limit))


@beta_tool
def run_sql(sql: str) -> str:
    """Run one read-only SELECT (DuckDB SQL) on the warehouse; at most 200 rows come back.

    Args:
        sql: A single SELECT or WITH ... SELECT statement.
    """
    return json.dumps(tools.run_sql(sql))


TOOLS = [search_catalog, describe_model, get_lineage, list_metrics, query_metric, run_sql]


@dataclass
class Result:
    text: str
    answer: dict | None
    turns: int
    input_tokens: int
    output_tokens: int
    stopped: str  # "done", "turn_cap", "token_cap", "refusal"
    tool_calls: list[str] = field(default_factory=list)


def ask(question: str, client: anthropic.Anthropic | None = None, model: str = MODEL,
        max_turns: int = MAX_TURNS, max_tokens_total: int = MAX_TOKENS) -> Result:
    client = client or anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        tools=TOOLS,
        messages=[{"role": "user", "content": question}],
        max_iterations=max_turns,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    turns = tin = tout = 0
    calls: list[str] = []
    last = None
    stopped = "turn_cap"
    for message in runner:
        last, turns = message, turns + 1
        tin += message.usage.input_tokens + (message.usage.cache_read_input_tokens or 0)
        tout += message.usage.output_tokens
        calls += [b.name for b in message.content if b.type == "tool_use"]
        if message.stop_reason == "refusal":
            stopped = "refusal"
            break
        if message.stop_reason == "end_turn":
            stopped = "done"
            break
        if tin + tout > max_tokens_total:
            stopped = "token_cap"
            break
    text = "".join(b.text for b in (last.content if last else []) if b.type == "text")
    return Result(text, parse_answer(text), turns, tin, tout, stopped, calls)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: python -m analyst.agent "your question"')
    r = ask(" ".join(sys.argv[1:]))
    print(r.text)
    print(f"\n[{r.stopped}: {r.turns} turns, {r.input_tokens:,} in / {r.output_tokens:,} out tokens, "
          f"tools: {', '.join(r.tool_calls) or 'none'}]", file=sys.stderr)


if __name__ == "__main__":
    main()
