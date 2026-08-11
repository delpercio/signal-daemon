"""Tests for the dashboard data layer and the non-destructive scan."""

import json

import pytest
from click.testing import CliRunner

from signal_daemon.cli import cli
from signal_daemon.config import SignalConfig
from signal_daemon.dashboard import build_payload, load_metrics
from signal_daemon.queue import DeliveryQueue
from signal_daemon.schema import EventType, Provider, SignalEvent


def usage_event(model="claude-opus-5", project="proj", session="s1", **usage):
    event = SignalEvent(
        device_id="dev",
        provider=Provider.CLAUDE_CODE,
        session_id=session,
        project=project,
        event_type=EventType.CONVERSATION_TURN,
        payload={
            "message": {
                "role": "assistant",
                "model": model,
                "usage": {
                    "input_tokens": usage.get("input_tokens", 1000),
                    "output_tokens": usage.get("output_tokens", 500),
                    "cache_read_input_tokens": usage.get("cache_read", 0),
                },
                "content": [{"type": "tool_use", "name": "Read", "input": {}}],
            }
        },
    )
    event.compute_hashes()
    return event


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNAL_DEVICE_ID", "testbox")
    cfg = SignalConfig(
        queue_db_path=tmp_path / "queue.db",
        state_dir=tmp_path / "state",
        log_file=tmp_path / "log.log",
    )
    cfg.ensure_dirs()
    return cfg


class TestLoadMetrics:
    def test_reads_and_normalises(self, config):
        queue = DeliveryQueue(db_path=config.queue_db_path)
        queue.enqueue_many([usage_event(), usage_event(session="s2")])

        items = load_metrics(config.queue_db_path)
        assert len(items) == 2
        assert all(m.model == "claude-opus-5" for m in items)
        assert all(m.usage.input_tokens == 1000 for m in items)

    def test_missing_db_is_empty(self, tmp_path):
        assert load_metrics(tmp_path / "nope.db") == []

    def test_corrupt_row_is_skipped(self, config):
        queue = DeliveryQueue(db_path=config.queue_db_path)
        queue.enqueue(usage_event())
        queue.db["events"].insert(
            {
                "event_id": "broken",
                "payload_json": "{not json",
                "enqueued_at": "2026-08-11T00:00:00+00:00",
                "attempts": 0,
                "delivered": 0,
            },
            pk="id",
        )
        assert len(load_metrics(config.queue_db_path)) == 1


class TestBuildPayload:
    @pytest.fixture
    def populated(self, config):
        queue = DeliveryQueue(db_path=config.queue_db_path)
        queue.enqueue_many(
            [
                usage_event(model="claude-opus-5", project="alpha", session="s1"),
                usage_event(model="claude-sonnet-5", project="beta", session="s2"),
                usage_event(model="claude-sonnet-5", project="beta", session="s2"),
            ]
        )
        return config

    def test_shape(self, populated):
        data = build_payload(populated, {})
        assert data["totals"]["events"] == 3
        assert data["totals"]["sessions"] == 2
        assert data["device_id"] == "testbox"
        assert data["queue"]["pending"] == 3
        assert {r["name"] for r in data["by_model"]} == {
            "claude-opus-5",
            "claude-sonnet-5",
        }

    def test_project_filter(self, populated):
        data = build_payload(populated, {"project": ["beta"]})
        assert data["totals"]["events"] == 2

    def test_model_filter(self, populated):
        data = build_payload(populated, {"model": ["claude-opus-5"]})
        assert data["totals"]["events"] == 1

    def test_search_matches_tool_names(self, populated):
        assert build_payload(populated, {"q": ["Read"]})["totals"]["events"] == 3
        assert build_payload(populated, {"q": ["Nonexistent"]})["totals"]["events"] == 0

    def test_facets_come_from_unfiltered_set(self, populated):
        """Selecting a project must not empty the dropdown that produced it."""
        data = build_payload(populated, {"project": ["beta"]})
        assert set(data["facets"]["projects"]) == {"alpha", "beta"}

    def test_bad_days_value_is_tolerated(self, populated):
        assert build_payload(populated, {"days": ["abc"]})["totals"]["events"] == 3

    def test_empty_database(self, config):
        data = build_payload(config, {})
        assert data["totals"]["events"] == 0
        assert data["recent"] == []


class TestScanCommand:
    """`scan` is documented as a dry run — it must not consume events."""

    def _fixture_home(self, tmp_path):
        proj = tmp_path / ".claude" / "projects" / "-Users-x-Documents-Demo"
        proj.mkdir(parents=True)
        (proj / "sess.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "sessionId": "sess",
                        "timestamp": "2026-08-11T10:00:00+00:00",
                        "type": "assistant",
                        "message": {
                            "model": "claude-opus-5",
                            "usage": {"input_tokens": 500, "output_tokens": 100},
                        },
                    }
                )
                for _ in range(3)
            )
            + "\n"
        )
        return tmp_path

    def test_dry_run_leaves_events_available(self, tmp_path, monkeypatch):
        home = self._fixture_home(tmp_path)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        runner = CliRunner()
        first = runner.invoke(cli, ["scan"])
        assert first.exit_code == 0, first.output
        assert "Total: 3 events" in first.output
        assert "Dry run" in first.output

        # The daemon must still be able to capture them.
        second = runner.invoke(cli, ["scan"])
        assert "Total: 3 events" in second.output

    def test_enqueue_persists_and_then_consumes(self, tmp_path, monkeypatch):
        home = self._fixture_home(tmp_path)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--enqueue"])
        assert result.exit_code == 0, result.output
        assert "Enqueued 3 new event(s)" in result.output

        db = home / ".signal-daemon" / "queue.db"
        assert db.exists()
        assert len(load_metrics(db)) == 3

        # Now the cursor has advanced, so a re-scan finds nothing.
        assert "Total: 0 events" in runner.invoke(cli, ["scan"]).output

    def test_reports_metrics(self, tmp_path, monkeypatch):
        home = self._fixture_home(tmp_path)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr("pathlib.Path.home", lambda: home)

        result = CliRunner().invoke(cli, ["scan"])
        assert "Est. cost:" in result.output
        assert "claude-opus-5" in result.output
