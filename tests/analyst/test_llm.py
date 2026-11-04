"""The provider-agnostic agent loop and its clients, with fake transports: no network, no key."""
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from analyst import agent, llm
from analyst.llm import AnthropicClient, ChatClient, Reply, ToolCall


class Scripted:
    provider, model = "scripted", "scripted-1"

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def complete(self, system, messages, tools):
        self.seen.append(([dict(m) for m in messages], tools))
        return self.replies.pop(0)


def add(a: int, b: int = 0) -> dict:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return {"sum": a + b}


def test_tool_spec_reads_types_defaults_and_docstring():
    spec = llm.tool_spec(add)
    assert spec["name"] == "add" and spec["description"] == "Add two numbers."
    assert spec["parameters"]["properties"]["a"] == {"type": "integer", "description": "First number."}
    assert spec["parameters"]["required"] == ["a"]


def test_tool_spec_for_optional_lists_and_extra_descriptions():
    spec = llm.tool_spec(agent.tools.query_metric, agent.PARAMS["query_metric"])
    props = spec["parameters"]["properties"]
    assert props["metrics"]["type"] == "array" and props["metrics"]["items"] == {"type": "string"}
    assert props["group_by"]["type"] == "array" and "metric_time__month" in props["group_by"]["description"]
    assert spec["parameters"]["required"] == ["metrics"]


def test_every_analyst_tool_has_a_spec_with_described_parameters():
    for fn in agent.TOOLS:
        spec = llm.tool_spec(fn, agent.PARAMS.get(fn.__name__))
        assert spec["description"]
        assert all("description" in p for p in spec["parameters"]["properties"].values()), fn.__name__


def test_loop_runs_tools_and_passes_results_back_by_id():
    client = Scripted(Reply("", [ToolCall("t1", "add", {"a": 2, "b": 3})], 10, 5, "tool_use"),
                      Reply("five", [], 20, 2))
    r = llm.run("2+3?", client, [add], "sys")
    assert (r.text, r.stopped, r.turns, r.input_tokens, r.output_tokens) == ("five", "done", 2, 30, 7)
    assert r.tool_calls == ["add"] and r.tool_inputs == [{"a": 2, "b": 3}]
    tool_msg = client.seen[1][0][-1]
    assert tool_msg == {"role": "tool", "tool_call_id": "t1", "name": "add", "content": '{"sum": 5}'}


def test_unknown_tools_and_bad_arguments_come_back_as_errors():
    client = Scripted(Reply("", [ToolCall("t1", "nope", {}), ToolCall("t2", "add", {"x": 1})], stop="tool_use"),
                      Reply("gave up", []))
    llm.run("?", client, [add], "sys")
    results = [json.loads(m["content"]) for m in client.seen[1][0] if m["role"] == "tool"]
    assert "unknown tool nope" in results[0]["error"] and results[1]["error"].startswith("TypeError")


def test_turn_cap_and_token_cap():
    loop = Reply("", [ToolCall("t", "add", {"a": 1})], 100, 100, "tool_use")
    r = llm.run("?", Scripted(*[loop] * 5), [add], "sys", max_turns=3)
    assert (r.stopped, r.turns) == ("turn_cap", 3)
    r = llm.run("?", Scripted(*[loop] * 5), [add], "sys", max_tokens_total=350)
    assert (r.stopped, r.turns) == ("token_cap", 2)


def test_refusal_stops_the_loop():
    r = llm.run("?", Scripted(Reply("no", [], stop="refusal")), [add], "sys")
    assert r.stopped == "refusal"


def test_agent_ask_uses_the_analyst_tools_prompt_and_caps():
    client = Scripted(Reply('```json\n{"answer": 1}\n```', []))
    r = agent.ask("q", client)
    _, tools = client.seen[0]
    assert [t["name"] for t in tools] == [f.__name__ for f in agent.TOOLS]
    assert r.stopped == "done"


# ---- Anthropic client against a fake SDK

def test_anthropic_client_maps_messages_tools_and_usage():
    sent = {}

    def create(**kw):
        sent.update(kw)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="looking"),
                     SimpleNamespace(type="tool_use", id="tu1", name="add", input={"a": 1})],
            usage=SimpleNamespace(input_tokens=7, output_tokens=3, cache_read_input_tokens=5),
            stop_reason="tool_use")

    client = AnthropicClient("claude-x", sdk=SimpleNamespace(messages=SimpleNamespace(create=create)))
    history = [{"role": "user", "content": "q"},
               {"role": "assistant", "content": None,
                "tool_calls": [ToolCall("a", "add", {}), ToolCall("b", "add", {})]},
               {"role": "tool", "tool_call_id": "a", "name": "add", "content": "1"},
               {"role": "tool", "tool_call_id": "b", "name": "add", "content": "2"}]
    reply = client.complete("sys", history, [llm.tool_spec(add)])
    assert sent["model"] == "claude-x" and sent["system"] == "sys"
    assert sent["tools"][0]["input_schema"]["required"] == ["a"]
    assert [b["tool_use_id"] for b in sent["messages"][2]["content"]] == ["a", "b"]  # one user turn
    assert len(sent["messages"]) == 3
    assert reply == Reply("looking", [ToolCall("tu1", "add", {"a": 1})], 12, 3, "tool_use")


# ---- chat-completions client (Gemini) against a fake transport

def completion(content=None, calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, n, a in calls]
    return {"choices": [{"message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 4}}


def http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("u", code, "x", headers, io.BytesIO(b""))


def test_gemini_client_payload_and_parse():
    seen = []

    def transport(url, headers, body):
        seen.append((url, headers, body))
        return completion(calls=[("c1", "add", {"a": 4})], finish="tool_calls")

    client = llm.gemini("gemini-test", api_key="k", transport=transport)
    history = [{"role": "user", "content": "q"},
               {"role": "assistant", "content": None, "tool_calls": [ToolCall("c0", "add", {"a": 1})]},
               {"role": "tool", "tool_call_id": "c0", "name": "add", "content": "{}"}]
    reply = client.complete("sys", history, [llm.tool_spec(add)])
    url, headers, body = seen[0]
    assert url == llm.GEMINI_URL and headers["Authorization"] == "Bearer k"
    assert body["model"] == "gemini-test" and body["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"]
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    assert body["tools"][0]["function"]["name"] == "add"
    assert reply == Reply("", [ToolCall("c1", "add", {"a": 4})], 11, 4, "tool_use")


def test_chat_client_retries_rate_limits_with_backoff_then_succeeds():
    attempts, waits = [], []

    def transport(url, headers, body):
        attempts.append(1)
        if len(attempts) == 1:
            raise http_error(429, "7")
        if len(attempts) == 2:
            raise http_error(503)
        return completion("ok")

    client = ChatClient("u", "m", "k", transport=transport, backoff_seconds=2, sleep=waits.append)
    assert client.complete("s", [{"role": "user", "content": "q"}], []).text == "ok"
    assert waits == [7.0, 4.0] and client.retried == 2


def test_chat_client_gives_up_after_retries_and_does_not_retry_auth_errors():
    def always(code):
        def transport(url, headers, body):
            raise http_error(code)
        return transport

    client = ChatClient("u", "m", "k", transport=always(429), retries=2, sleep=lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        client.complete("s", [], [])
    assert client.retried == 2
    client = ChatClient("u", "m", "k", transport=always(401), sleep=lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        client.complete("s", [], [])
    assert client.retried == 0


def test_chat_client_paces_requests():
    waits = []
    client = ChatClient("u", "m", "k", transport=lambda *a: completion("ok"), min_interval_seconds=6,
                        sleep=waits.append)
    client.complete("s", [], [])
    client.complete("s", [], [])
    assert len(waits) == 1 and 5 < waits[0] <= 6


def test_bad_tool_arguments_from_the_model_parse_to_empty():
    data = completion(calls=[("c", "add", {})], finish="tool_calls")
    data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{not json"
    assert llm.parse_chat_completion(data).tool_calls == [ToolCall("c", "add", {})]


def test_missing_key_and_unknown_provider_fail_clearly(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no API key"):
        llm.gemini()
    with pytest.raises(ValueError, match="unknown provider"):
        llm.make_client("other")


def test_gemini_thought_signature_round_trips():
    """Gemini 3 returns a thought_signature with each tool call and rejects the next turn without it."""
    sig = {"google": {"thought_signature": "c2ln"}}
    data = completion(calls=[("c1", "add", {"a": 4})], finish="tool_calls")
    data["choices"][0]["message"]["tool_calls"][0]["extra_content"] = sig
    call = llm.parse_chat_completion(data).tool_calls[0]
    assert call.extra == sig
    body = ChatClient.payload("m", "s", [{"role": "assistant", "content": None, "tool_calls": [call]}], [])
    assert body["messages"][1]["tool_calls"][0]["extra_content"] == sig
    plain = ChatClient.payload("m", "s", [{"role": "assistant", "content": None,
                                           "tool_calls": [ToolCall("c", "add", {})]}], [])
    assert "extra_content" not in plain["messages"][1]["tool_calls"][0]


def test_gemini_default_model_is_open_to_new_free_keys():
    assert llm.make_client("gemini", api_key="k").model == "gemini-3.5-flash-lite"
