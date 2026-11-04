"""A small, provider-agnostic tool-calling loop for the analyst.

One message format for every provider:
    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "..." | None, "tool_calls": [ToolCall, ...]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "<json>"}

A client turns that into one provider request and returns a Reply. Two are included:

- AnthropicClient   the Claude Messages API (anthropic SDK; ANTHROPIC_API_KEY or `ant auth login`)
- ChatClient        any OpenAI-compatible chat-completions endpoint over plain HTTPS (standard library only);
                    `gemini()` points it at Google's free-tier Gemini API (GEMINI_API_KEY)

`run` executes the tools the model asks for and stops at the turn cap or the token cap, whichever comes first.
"""
import inspect
import json
import os
import re
import time
import types
import typing
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    extra: dict | None = None  # provider data to send back with this call (Gemini 3's thought_signature)


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    stop: str = "end"  # "end", "tool_use", "refusal", "length"


class Client(Protocol):
    provider: str
    model: str

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply: ...


# ---- tool specs from plain functions

_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}


def _schema(tp) -> tuple[dict, bool]:
    """JSON schema for a type hint, and whether None is allowed."""
    args = typing.get_args(tp)
    if typing.get_origin(tp) in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        schema, _ = _schema(inner[0])
        return schema, len(inner) < len(args)
    if typing.get_origin(tp) is list:
        return {"type": "array", "items": _schema(args[0])[0] if args else {}}, False
    return {"type": _JSON.get(tp, "string")}, False


def _docstring(fn: Callable) -> tuple[str, dict[str, str]]:
    """Description (everything before "Args:") and per-argument lines from a Google-style docstring."""
    doc = inspect.getdoc(fn) or ""
    head, _, args = doc.partition("\nArgs:\n")
    params = dict(re.findall(r"^\s+(\w+):\s*(.+)$", args, flags=re.M))
    return " ".join(head.split()), params


def tool_spec(fn: Callable, params: dict[str, str] | None = None) -> dict:
    """{"name", "description", "parameters"} for a function, from its signature and docstring."""
    description, documented = _docstring(fn)
    documented |= params or {}
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        schema, nullable = _schema(hints.get(name, str))
        if name in documented:
            schema["description"] = documented[name]
        props[name] = schema
        if p.default is inspect.Parameter.empty and not nullable:
            required.append(name)
    return {"name": fn.__name__, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required}}


# ---- the loop

@dataclass
class Result:
    text: str
    turns: int
    input_tokens: int
    output_tokens: int
    stopped: str  # "done", "turn_cap", "token_cap", "refusal", "length"
    tool_calls: list[str] = field(default_factory=list)
    tool_inputs: list[dict] = field(default_factory=list)


def call_tool(fns: dict[str, Callable], call: ToolCall) -> str:
    fn = fns.get(call.name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {call.name}; available: {', '.join(fns)}"})
    try:
        out = fn(**call.arguments)
    except TypeError as e:  # wrong or missing arguments: the model reads the message and retries
        out = {"error": f"TypeError: {e}"}
    return out if isinstance(out, str) else json.dumps(out, default=str)


def run(question: str, client: Client, tools: list[Callable], system: str, max_turns: int = 12,
        max_tokens_total: int = 300_000, params: dict[str, dict[str, str]] | None = None) -> Result:
    """Ask, run the requested tools, pass their results back, repeat until the model answers or a cap hits."""
    fns = {f.__name__: f for f in tools}
    specs = [tool_spec(f, (params or {}).get(f.__name__)) for f in tools]
    messages: list[dict] = [{"role": "user", "content": question}]
    turns = tin = tout = 0
    calls: list[str] = []
    inputs: list[dict] = []
    text, stopped = "", "turn_cap"
    while turns < max_turns:
        reply = client.complete(system, messages, specs)
        turns, tin, tout = turns + 1, tin + reply.input_tokens, tout + reply.output_tokens
        text = reply.text or ""
        if reply.stop in ("refusal", "length") and not reply.tool_calls:
            stopped = reply.stop
            break
        if not reply.tool_calls:
            stopped = "done"
            break
        messages.append({"role": "assistant", "content": reply.text or None, "tool_calls": reply.tool_calls})
        for c in reply.tool_calls:
            calls.append(c.name)
            inputs.append(c.arguments)
            messages.append({"role": "tool", "tool_call_id": c.id, "name": c.name,
                             "content": call_tool(fns, c)})
        if tin + tout > max_tokens_total:
            stopped = "token_cap"
            break
    return Result(text, turns, tin, tout, stopped, calls, inputs)


# ---- Anthropic

class AnthropicClient:
    provider = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5", sdk=None, max_tokens: int = 16000):
        if sdk is None:
            import anthropic

            sdk = anthropic.Anthropic()
        self.model, self._sdk, self._max_tokens = model, sdk, max_tokens

    @staticmethod
    def messages(messages: list[dict]) -> list[dict]:
        """Neutral messages -> Anthropic messages (tool results go back in one user turn)."""
        out: list[dict] = []
        for m in messages:
            if m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                           for c in m.get("tool_calls") or []]
                out.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            else:
                out.append({"role": "user", "content": m["content"]})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        msg = self._sdk.messages.create(
            model=self.model, max_tokens=self._max_tokens, system=system, messages=self.messages(messages),
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                   for t in tools])
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in msg.content if b.type == "tool_use"]
        u = msg.usage
        stop = {"tool_use": "tool_use", "refusal": "refusal", "max_tokens": "length"}.get(msg.stop_reason, "end")
        return Reply(text, calls, u.input_tokens + (getattr(u, "cache_read_input_tokens", 0) or 0),
                     u.output_tokens, stop)


# ---- OpenAI-compatible chat completions (Gemini's free tier and others)

Transport = Callable[[str, dict, dict], dict]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
RETRY_CODES = (429, 500, 502, 503, 504)


def _urllib_transport(url: str, headers: dict, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


class ChatClient:
    """Chat completions with tools, over HTTPS. Retries rate limits and server errors with backoff
    (Retry-After when the server sends it), and can wait a fixed time before every request to stay
    under a requests-per-minute limit."""

    def __init__(self, url: str, model: str, api_key: str, provider: str = "openai-compatible",
                 transport: Transport = _urllib_transport, retries: int = 5, backoff_seconds: float = 4.0,
                 min_interval_seconds: float = 0.0, sleep: Callable[[float], None] = time.sleep):
        if not api_key:
            raise RuntimeError(f"{provider}: no API key")
        self.url, self.model, self.provider = url, model, provider
        self._key, self._transport, self._retries, self._backoff = api_key, transport, retries, backoff_seconds
        self._interval, self._sleep, self._last = min_interval_seconds, sleep, None
        self.retried = 0

    @staticmethod
    def payload(model: str, system: str, messages: list[dict], tools: list[dict]) -> dict:
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("content")}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [_tool_call_out(c) for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return {"model": model, "messages": out, "temperature": 0,
                "tools": [{"type": "function", "function": t} for t in tools]}

    def _pace(self) -> None:
        if self._interval and self._last is not None:
            wait = self._interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = time.monotonic()

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        body = self.payload(self.model, system, messages, tools)
        for attempt in range(self._retries + 1):
            self._pace()
            try:
                return parse_chat_completion(self._transport(self.url, headers, body))
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_CODES or attempt == self._retries:
                    raise
                after = e.headers.get("Retry-After") if e.headers else None
                self.retried += 1
                self._sleep(float(after) if after and after.isdigit() else self._backoff * 2 ** attempt)
        raise AssertionError("unreachable")


def _tool_call_out(c: ToolCall) -> dict:
    out = {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
    if c.extra:
        # Gemini 3 models reject the next turn unless each tool call's thought_signature comes back with it.
        out["extra_content"] = c.extra
    return out


def parse_chat_completion(data: dict) -> Reply:
    choice = data["choices"][0]
    message = choice["message"]
    calls = []
    for i, c in enumerate(message.get("tool_calls") or []):
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(c.get("id") or f"call_{i}", c["function"]["name"],
                              args if isinstance(args, dict) else {}, c.get("extra_content")))
    usage = data.get("usage") or {}
    stop = {"tool_calls": "tool_use", "length": "length", "content_filter": "refusal"}.get(
        choice.get("finish_reason"), "end")
    return Reply(message.get("content") or "", calls, usage.get("prompt_tokens", 0),
                 usage.get("completion_tokens", 0), stop)


# New free-tier keys can't use gemini-2.5-* (checked 2026-11-04), and gemini-3.5-flash allows 20 free
# requests a day; one eval answer takes several requests, so the default is the lite model.
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"


def gemini(model: str = GEMINI_DEFAULT_MODEL, api_key: str | None = None, **kw) -> ChatClient:
    """Google's Gemini API through its OpenAI-compatible endpoint; a free-tier key from AI Studio works."""
    return ChatClient(GEMINI_URL, model, api_key or os.environ.get("GEMINI_API_KEY", ""), provider="gemini", **kw)


PROVIDERS = {"anthropic": lambda model=None, **kw: AnthropicClient(model or "claude-opus-5-5"),
             "gemini": lambda model=None, **kw: gemini(model or GEMINI_DEFAULT_MODEL, **kw)}


def make_client(provider: str, model: str | None = None, **kw) -> Client:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
    return PROVIDERS[provider](model, **kw)
