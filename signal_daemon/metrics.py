"""Metric extraction — turns raw captured payloads into usable numbers.

The adapters store each tool's payload verbatim, which preserves fidelity but
means nothing is directly queryable: token counts and model names are buried at
different paths for each provider. This module normalises them into a single
`EventMetrics` shape so the dashboard (and Anton) can aggregate without knowing
anything about Antigravity/Claude Code/Codex internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from signal_daemon.schema import EventType, Provider

# ---------- Pricing ----------

# USD per 1M tokens. Anthropic rates are first-party API list prices;
# non-Anthropic rates are approximations for rough cost tracking only.
#
# Cache multipliers (Anthropic): a 5-minute cache write costs 1.25x the input
# rate, a 1-hour write 2x, and a cache read 0.1x.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10

MODEL_PRICES_PER_1M: dict[str, dict[str, float]] = {
    # Anthropic — current
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-mythos-5": {"input": 10.0, "output": 50.0},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    # Anthropic — legacy
    "claude-opus-4-1": {"input": 15.0, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0},
    # Google (approximate)
    "gemini-3.1-pro": {"input": 2.0, "output": 12.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    # OpenAI (approximate)
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "o3": {"input": 2.0, "output": 8.0},
    "codex-mini": {"input": 1.50, "output": 6.0},
}

# Used when a model is seen that isn't in the table. Deliberately mid-range;
# callers can check `priced` on the result to tell a real price from a guess.
_FALLBACK_PRICE = {"input": 3.0, "output": 15.0}

# Longest first, so "gpt-4o-mini" wins over "gpt-4o" and "claude-opus-4-8"
# wins over "claude-opus-4".
_PRICE_KEYS_BY_LENGTH = sorted(MODEL_PRICES_PER_1M, key=len, reverse=True)


def resolve_price(model: str) -> tuple[dict[str, float], bool]:
    """Look up per-1M-token pricing for a model.

    Returns (price, priced) where `priced` is False if we fell back to an
    estimate. Matching is exact first, then longest-prefix — an empty or
    unrecognised model never silently inherits an unrelated model's rate.
    """
    if not model:
        return _FALLBACK_PRICE, False

    exact = MODEL_PRICES_PER_1M.get(model)
    if exact is not None:
        return exact, True

    for key in _PRICE_KEYS_BY_LENGTH:
        if model.startswith(key):
            return MODEL_PRICES_PER_1M[key], True

    return _FALLBACK_PRICE, False


@dataclass
class TokenUsage:
    """Token counts for a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    def __bool__(self) -> bool:
        return self.total > 0


def estimate_cost(model: str, usage: TokenUsage) -> tuple[float, bool]:
    """Estimate USD cost for one model call.

    Returns (cost, priced). Cache writes and reads are billed off the input
    rate at their respective multipliers rather than at full price — ignoring
    that overstates the cost of a cache-heavy session several times over.
    """
    price, priced = resolve_price(model)
    per_input = price["input"] / 1_000_000
    per_output = price["output"] / 1_000_000

    cost = (
        usage.input_tokens * per_input
        + usage.output_tokens * per_output
        + usage.cache_creation_tokens * per_input * CACHE_WRITE_MULTIPLIER
        + usage.cache_read_tokens * per_input * CACHE_READ_MULTIPLIER
    )
    return cost, priced


@dataclass
class EventMetrics:
    """Normalised metrics for a single captured event."""

    event_id: str
    provider: str
    event_type: str
    session_id: str
    project: str
    timestamp: datetime | None
    device_id: str = ""
    model: str = ""
    role: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    cost_is_estimate: bool = True
    payload_bytes: int = 0
    tool_names: list[str] = field(default_factory=list)
    text_chars: int = 0

    @property
    def has_usage(self) -> bool:
        return bool(self.usage)


# ---------- Payload extraction ----------


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _extract_claude_code(payload: dict) -> tuple[str, str, TokenUsage, list[str], int]:
    """Pull model/role/usage/tools out of a Claude Code JSONL record."""
    message = payload.get("message")
    if not isinstance(message, dict):
        message = {}

    model = message.get("model") or payload.get("model") or ""
    role = message.get("role") or payload.get("type") or ""

    raw_usage = message.get("usage")
    usage = TokenUsage()
    if isinstance(raw_usage, dict):
        usage = TokenUsage(
            input_tokens=_as_int(raw_usage.get("input_tokens")),
            output_tokens=_as_int(raw_usage.get("output_tokens")),
            cache_creation_tokens=_as_int(
                raw_usage.get("cache_creation_input_tokens")
            ),
            cache_read_tokens=_as_int(raw_usage.get("cache_read_input_tokens")),
        )

    tools: list[str] = []
    text_chars = 0
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name")
                if isinstance(name, str):
                    tools.append(name)
            elif block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_chars += len(text)
    elif isinstance(content, str):
        text_chars = len(content)

    return str(model), str(role), usage, tools, text_chars


def _extract_antigravity(payload: dict) -> tuple[str, str, TokenUsage, int]:
    """Pull what we can out of an Antigravity transcript step or artifact."""
    model = payload.get("model") or payload.get("model_name") or ""
    role = payload.get("role") or payload.get("step_type") or ""

    usage = TokenUsage()
    raw_usage = payload.get("usage") or payload.get("token_usage")
    if isinstance(raw_usage, dict):
        usage = TokenUsage(
            input_tokens=_as_int(
                raw_usage.get("input_tokens") or raw_usage.get("prompt_tokens")
            ),
            output_tokens=_as_int(
                raw_usage.get("output_tokens") or raw_usage.get("completion_tokens")
            ),
            cache_creation_tokens=_as_int(
                raw_usage.get("cache_creation_input_tokens")
            ),
            cache_read_tokens=_as_int(raw_usage.get("cache_read_input_tokens")),
        )

    text_chars = 0
    for key in ("content", "text", "body"):
        value = payload.get(key)
        if isinstance(value, str):
            text_chars = max(text_chars, len(value))

    return str(model), str(role), usage, text_chars


def extract_metrics(
    event_id: str,
    provider: str,
    event_type: str,
    session_id: str,
    project: str,
    timestamp: datetime | None,
    payload: dict,
    device_id: str = "",
    payload_bytes: int = 0,
) -> EventMetrics:
    """Normalise one captured event into `EventMetrics`."""
    model = ""
    role = ""
    usage = TokenUsage()
    tools: list[str] = []
    text_chars = 0

    if not isinstance(payload, dict):
        payload = {}

    if provider == Provider.CLAUDE_CODE:
        model, role, usage, tools, text_chars = _extract_claude_code(payload)
    elif provider == Provider.ANTIGRAVITY:
        model, role, usage, text_chars = _extract_antigravity(payload)
    elif provider == Provider.CODEX:
        role = str(payload.get("level") or "")
        body = payload.get("feedback_log_body") or payload.get("raw_memory")
        if isinstance(body, str):
            text_chars = len(body)
        if not payload_bytes:
            payload_bytes = _as_int(payload.get("estimated_bytes"))

    cost, priced = estimate_cost(model, usage) if usage else (0.0, bool(model))

    return EventMetrics(
        event_id=event_id,
        provider=provider,
        event_type=event_type,
        session_id=session_id,
        project=project,
        timestamp=timestamp,
        device_id=device_id,
        model=model,
        role=role,
        usage=usage,
        cost_usd=cost,
        cost_is_estimate=not priced,
        payload_bytes=payload_bytes,
        tool_names=tools,
        text_chars=text_chars,
    )


def metrics_from_event(event) -> EventMetrics:
    """Build `EventMetrics` from a `SignalEvent`."""
    return extract_metrics(
        event_id=event.event_id,
        provider=str(event.provider),
        event_type=str(event.event_type),
        session_id=event.session_id,
        project=event.project,
        timestamp=event.timestamp,
        payload=event.payload,
        device_id=event.device_id,
        payload_bytes=event.payload_bytes,
    )


# ---------- Aggregation ----------


def _bucket_key(metrics: EventMetrics) -> str:
    return metrics.timestamp.date().isoformat() if metrics.timestamp else "unknown"


def summarise(items: list[EventMetrics]) -> dict:
    """Aggregate a list of event metrics into dashboard-ready totals."""
    totals = {
        "events": len(items),
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "estimated_cost_usd": 0.0,
        "events_with_usage": 0,
        "payload_bytes": 0,
    }

    by_provider: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_project: dict[str, dict] = {}
    by_event_type: dict[str, int] = {}
    by_day: dict[str, dict] = {}
    by_tool: dict[str, int] = {}
    sessions: set[str] = set()

    def slot(store: dict, key: str) -> dict:
        return store.setdefault(
            key,
            {
                "events": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0.0,
            },
        )

    for m in items:
        u = m.usage
        totals["input_tokens"] += u.input_tokens
        totals["output_tokens"] += u.output_tokens
        totals["cache_creation_tokens"] += u.cache_creation_tokens
        totals["cache_read_tokens"] += u.cache_read_tokens
        totals["total_tokens"] += u.total
        totals["cost_usd"] += m.cost_usd
        totals["payload_bytes"] += m.payload_bytes
        if m.has_usage:
            totals["events_with_usage"] += 1
        if m.cost_is_estimate:
            totals["estimated_cost_usd"] += m.cost_usd

        if m.session_id:
            sessions.add(f"{m.provider}:{m.session_id}")

        by_event_type[m.event_type] = by_event_type.get(m.event_type, 0) + 1
        for tool in m.tool_names:
            by_tool[tool] = by_tool.get(tool, 0) + 1

        for store, key in (
            (by_provider, m.provider or "unknown"),
            (by_model, m.model or "(no model)"),
            (by_project, m.project or "(unattributed)"),
            (by_day, _bucket_key(m)),
        ):
            s = slot(store, key)
            s["events"] += 1
            s["input_tokens"] += u.input_tokens
            s["output_tokens"] += u.output_tokens
            s["cache_creation_tokens"] += u.cache_creation_tokens
            s["cache_read_tokens"] += u.cache_read_tokens
            s["total_tokens"] += u.total
            s["cost_usd"] += m.cost_usd

    totals["sessions"] = len(sessions)

    def rows(store: dict) -> list[dict]:
        out = [{"name": k, **v} for k, v in store.items()]
        out.sort(key=lambda r: (r["cost_usd"], r["events"]), reverse=True)
        return out

    return {
        "totals": totals,
        "by_provider": rows(by_provider),
        "by_model": rows(by_model),
        "by_project": rows(by_project),
        "by_day": sorted(
            ({"name": k, **v} for k, v in by_day.items()), key=lambda r: r["name"]
        ),
        "by_event_type": sorted(
            ({"name": k, "events": v} for k, v in by_event_type.items()),
            key=lambda r: r["events"],
            reverse=True,
        ),
        "by_tool": sorted(
            ({"name": k, "count": v} for k, v in by_tool.items()),
            key=lambda r: r["count"],
            reverse=True,
        )[:25],
    }
