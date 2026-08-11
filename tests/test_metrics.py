"""Tests for metric extraction and costing."""

from datetime import datetime, timezone

import pytest

from signal_daemon.metrics import (
    CACHE_READ_MULTIPLIER,
    MODEL_PRICES_PER_1M,
    TokenUsage,
    estimate_cost,
    extract_metrics,
    metrics_from_event,
    resolve_price,
    summarise,
)
from signal_daemon.schema import EventType, Provider, SignalEvent


class TestResolvePrice:
    def test_exact_match(self):
        price, priced = resolve_price("claude-opus-5")
        assert priced
        assert price["input"] == 5.0
        assert price["output"] == 25.0

    def test_longest_prefix_wins(self):
        # "gpt-4o-mini" must not be captured by the shorter "gpt-4o" key.
        mini, _ = resolve_price("gpt-4o-mini")
        full, _ = resolve_price("gpt-4o")
        assert mini["input"] == 0.15
        assert full["input"] == 2.50

    def test_dated_suffix_resolves_to_base(self):
        price, priced = resolve_price("claude-haiku-4-5-20251001")
        assert priced
        assert price["input"] == 1.0

    @pytest.mark.parametrize("model", ["", "totally-unknown-model"])
    def test_unknown_is_flagged_not_guessed(self, model):
        """An empty/unknown model must not inherit an unrelated model's rate."""
        price, priced = resolve_price(model)
        assert priced is False
        assert price["input"] == 3.0

    def test_no_reverse_prefix_match(self):
        # A bare vendor prefix should not match a full model id.
        _, priced = resolve_price("claude")
        assert priced is False


class TestEstimateCost:
    def test_cache_reads_are_discounted(self):
        """Cache reads bill at 0.1x input, not full price."""
        usage = TokenUsage(cache_read_tokens=1_000_000)
        cost, _ = estimate_cost("claude-opus-5", usage)
        full_rate = MODEL_PRICES_PER_1M["claude-opus-5"]["input"]
        assert cost == pytest.approx(full_rate * CACHE_READ_MULTIPLIER)

    def test_cache_writes_carry_a_premium(self):
        write, _ = estimate_cost("claude-opus-5", TokenUsage(cache_creation_tokens=1_000_000))
        plain, _ = estimate_cost("claude-opus-5", TokenUsage(input_tokens=1_000_000))
        assert write > plain

    def test_zero_usage_is_free(self):
        cost, _ = estimate_cost("claude-opus-5", TokenUsage())
        assert cost == 0.0

    def test_output_priced_higher_than_input(self):
        i, _ = estimate_cost("claude-sonnet-5", TokenUsage(input_tokens=1000))
        o, _ = estimate_cost("claude-sonnet-5", TokenUsage(output_tokens=1000))
        assert o > i


def _claude_payload(model="claude-opus-5", **usage):
    return {
        "sessionId": "s1",
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": usage.get("input_tokens", 100),
                "output_tokens": usage.get("output_tokens", 50),
                "cache_creation_input_tokens": usage.get("cache_creation", 0),
                "cache_read_input_tokens": usage.get("cache_read", 0),
            },
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "name": "Read", "input": {}},
            ],
        },
    }


class TestExtraction:
    def _extract(self, payload, provider=Provider.CLAUDE_CODE):
        return extract_metrics(
            event_id="e1",
            provider=str(provider),
            event_type=str(EventType.CONVERSATION_TURN),
            session_id="s1",
            project="proj",
            timestamp=datetime(2026, 8, 11, tzinfo=timezone.utc),
            payload=payload,
        )

    def test_pulls_model_usage_and_tools(self):
        m = self._extract(_claude_payload(cache_read=9000))
        assert m.model == "claude-opus-5"
        assert m.usage.input_tokens == 100
        assert m.usage.output_tokens == 50
        assert m.usage.cache_read_tokens == 9000
        assert m.tool_names == ["Read"]
        assert m.text_chars == len("hello")
        assert m.cost_usd > 0
        assert m.cost_is_estimate is False

    def test_unknown_model_marks_cost_as_estimate(self):
        m = self._extract(_claude_payload(model="some-new-model"))
        assert m.cost_is_estimate is True

    def test_user_turn_has_no_usage(self):
        m = self._extract({"type": "user", "message": {"role": "user", "content": "hi"}})
        assert not m.has_usage
        assert m.cost_usd == 0.0

    def test_malformed_payload_does_not_raise(self):
        for payload in ({}, {"message": "not-a-dict"}, {"message": {"usage": None}}):
            m = self._extract(payload)
            assert m.usage.total == 0

    def test_non_numeric_token_counts_ignored(self):
        m = self._extract({"message": {"model": "claude-opus-5", "usage": {"input_tokens": "lots"}}})
        assert m.usage.input_tokens == 0

    def test_codex_uses_estimated_bytes(self):
        m = self._extract(
            {"level": "INFO", "feedback_log_body": "x" * 40, "estimated_bytes": 512},
            provider=Provider.CODEX,
        )
        assert m.payload_bytes == 512
        assert m.text_chars == 40

    def test_from_signal_event(self):
        event = SignalEvent(
            device_id="dev",
            provider=Provider.CLAUDE_CODE,
            session_id="s1",
            project="proj",
            event_type=EventType.CONVERSATION_TURN,
            payload=_claude_payload(),
        )
        event.compute_hashes()
        m = metrics_from_event(event)
        assert m.model == "claude-opus-5"
        assert m.payload_bytes == event.payload_bytes


class TestSummarise:
    def _items(self):
        return [
            extract_metrics(
                event_id=f"e{i}",
                provider=str(Provider.CLAUDE_CODE),
                event_type=str(EventType.CONVERSATION_TURN),
                session_id=f"s{i % 2}",
                project="proj" if i % 2 else "other",
                timestamp=datetime(2026, 8, 10 + (i % 2), tzinfo=timezone.utc),
                payload=_claude_payload(),
            )
            for i in range(4)
        ]

    def test_totals_and_breakdowns(self):
        s = summarise(self._items())
        assert s["totals"]["events"] == 4
        assert s["totals"]["input_tokens"] == 400
        assert s["totals"]["sessions"] == 2
        assert s["totals"]["events_with_usage"] == 4
        assert {r["name"] for r in s["by_project"]} == {"proj", "other"}
        assert len(s["by_day"]) == 2
        assert s["by_tool"][0] == {"name": "Read", "count": 4}

    def test_days_sorted_ascending(self):
        s = summarise(self._items())
        names = [r["name"] for r in s["by_day"]]
        assert names == sorted(names)

    def test_empty_input(self):
        s = summarise([])
        assert s["totals"]["events"] == 0
        assert s["totals"]["cost_usd"] == 0.0
        assert s["by_provider"] == []

    def test_missing_timestamp_bucketed_as_unknown(self):
        m = extract_metrics(
            event_id="e",
            provider="claude_code",
            event_type="conversation_turn",
            session_id="s",
            project="",
            timestamp=None,
            payload={},
        )
        assert summarise([m])["by_day"][0]["name"] == "unknown"
