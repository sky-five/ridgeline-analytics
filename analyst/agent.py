"""The analyst as an API agent: same tools and instructions as the MCP server, with spending caps.

    python -m analyst.agent "What was MRR at the end of September 2026?"                  # Claude (default)
    python -m analyst.agent --provider gemini "What was MRR at the end of September 2026?"

The model provider is pluggable (analyst/llm.py): `anthropic` needs ANTHROPIC_API_KEY or `ant auth login`;
`gemini` needs GEMINI_API_KEY (Google AI Studio's free tier works). Caps, whatever the provider: at most
MAX_TURNS model calls and MAX_TOKENS input+output tokens per question; the run stops cleanly at either.
"""
import argparse
import sys

from analyst import llm, tools
from analyst.llm import Result
from analyst.prompt import SYSTEM, parse_answer

MODEL = "claude-opus-5-5"
MAX_TURNS = 12
MAX_TOKENS = 300_000

TOOLS = tools.ALL
PARAMS = {
    "search_catalog": {"query": 'A few words from the question, e.g. "churned mrr" or "lead close rate".'},
    "describe_model": {"name": "Model name, e.g. fct_mrr_daily."},
    "get_lineage": {"name": "Model name, e.g. fct_mrr_daily.", "direction": '"upstream" or "downstream".'},
    "query_metric": {
        "metrics": 'Metric names from list_metrics, e.g. ["mrr"].',
        "group_by": 'MetricFlow names, e.g. ["metric_time__month"] or ["account__channel"].',
        "where": "Jinja filters, e.g. [\"{{ TimeDimension('metric_time', 'day') }} >= '2026-01-01'\"].",
        "order_by": 'e.g. ["-metric_time__month"] for newest first.',
        "limit": "Maximum rows.",
    },
    "run_sql": {"sql": "A single SELECT or WITH ... SELECT statement."},
}

__all__ = ["MODEL", "MAX_TURNS", "MAX_TOKENS", "TOOLS", "Result", "ask"]


def ask(question: str, client: llm.Client | None = None, model: str = MODEL, max_turns: int = MAX_TURNS,
        max_tokens_total: int = MAX_TOKENS) -> Result:
    """Answer one question. Without a client, uses Claude (`model`)."""
    client = client or llm.AnthropicClient(model)
    return llm.run(question, client, TOOLS, SYSTEM, max_turns, max_tokens_total, PARAMS)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="+")
    p.add_argument("--provider", choices=sorted(llm.PROVIDERS), default="anthropic")
    p.add_argument("--model", default=None, help="model id; default: the provider's default")
    args = p.parse_args()
    r = ask(" ".join(args.question), llm.make_client(args.provider, args.model))
    print(r.text)
    ans = parse_answer(r.text)
    print(f"\n[{r.stopped}: {r.turns} turns, {r.input_tokens:,} in / {r.output_tokens:,} out tokens, "
          f"tools: {', '.join(r.tool_calls) or 'none'}, parsed answer: {ans is not None}]", file=sys.stderr)


if __name__ == "__main__":
    main()
