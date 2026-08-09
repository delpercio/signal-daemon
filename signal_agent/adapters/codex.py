"""Codex adapter.

Polls ~/.codex/logs_2.sqlite and ~/.codex/memories_1.sqlite periodically.
SQLite doesn't support reliable filesystem change notifications so we
poll every N seconds and track the last-seen row ID.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from signal_agent.schema import EventType, Provider, SignalEvent

logger = logging.getLogger(__name__)


class CodexAdapter:
    """Periodic SQLite reader for Codex data."""

    def __init__(
        self,
        codex_dir: Path,
        device_id: str,
        on_events: Callable[[list[SignalEvent]], None],
        state_dir: Path,
    ):
        self.codex_dir = codex_dir
        self.logs_db = codex_dir / "logs_2.sqlite"
        self.memories_db = codex_dir / "memories_1.sqlite"
        self.device_id = device_id
        self.on_events = on_events
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_file(self) -> Path:
        return self.state_dir / "codex_state.json"

    def _load_state(self) -> dict:
        sf = self._state_file()
        if sf.exists():
            try:
                return json.loads(sf.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"last_log_id": 0, "seen_memories": []}

    def _save_state(self, state: dict) -> None:
        self._state_file().write_text(json.dumps(state))

    def _read_logs(self, state: dict) -> list[SignalEvent]:
        """Read new rows from the logs SQLite database."""
        if not self.logs_db.exists():
            return []

        events = []
        last_id = state.get("last_log_id", 0)

        try:
            conn = sqlite3.connect(
                f"file:{self.logs_db}?mode=ro&immutable=0",
                uri=True,
                timeout=5,
            )
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT id, ts, ts_nanos, level, target, feedback_log_body, "
                "module_path, file, line, thread_id, process_uuid, estimated_bytes "
                "FROM logs WHERE id > ? ORDER BY id ASC LIMIT 500",
                (last_id,),
            )

            for row in cursor:
                payload = {
                    "id": row["id"],
                    "ts": row["ts"],
                    "ts_nanos": row["ts_nanos"],
                    "level": row["level"],
                    "target": row["target"],
                    "feedback_log_body": row["feedback_log_body"],
                    "module_path": row["module_path"],
                    "file": row["file"],
                    "line": row["line"],
                    "thread_id": row["thread_id"],
                    "process_uuid": row["process_uuid"],
                    "estimated_bytes": row["estimated_bytes"],
                }

                # Convert Unix timestamp to datetime
                ts = datetime.fromtimestamp(row["ts"], tz=timezone.utc)

                event = SignalEvent(
                    device_id=self.device_id,
                    provider=Provider.CODEX,
                    session_id=row["thread_id"] or row["process_uuid"] or "",
                    project="",
                    event_type=EventType.LOG_ENTRY,
                    timestamp=ts,
                    payload=payload,
                    source_file=str(self.logs_db),
                )
                event.compute_hashes()
                events.append(event)
                last_id = max(last_id, row["id"])

            conn.close()

        except sqlite3.Error as exc:
            logger.warning("Error reading Codex logs: %s", exc)

        if events:
            state["last_log_id"] = last_id
            logger.info("Codex: %d new log entries (last_id=%d)", len(events), last_id)

        return events

    def _read_memories(self, state: dict) -> list[SignalEvent]:
        """Read new memories from the memories SQLite database."""
        if not self.memories_db.exists():
            return []

        events = []
        seen = set(state.get("seen_memories", []))

        try:
            conn = sqlite3.connect(
                f"file:{self.memories_db}?mode=ro&immutable=0",
                uri=True,
                timeout=5,
            )
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT thread_id, source_updated_at, raw_memory, "
                "rollout_summary, rollout_slug, generated_at, "
                "usage_count, last_usage, selected_for_phase2 "
                "FROM stage1_outputs"
            )

            for row in cursor:
                thread_id = row["thread_id"]
                if thread_id in seen:
                    continue

                payload = {
                    "thread_id": thread_id,
                    "source_updated_at": row["source_updated_at"],
                    "raw_memory": row["raw_memory"],
                    "rollout_summary": row["rollout_summary"],
                    "rollout_slug": row["rollout_slug"],
                    "generated_at": row["generated_at"],
                    "usage_count": row["usage_count"],
                    "last_usage": row["last_usage"],
                    "selected_for_phase2": row["selected_for_phase2"],
                }

                ts = datetime.fromtimestamp(
                    row["source_updated_at"], tz=timezone.utc
                )

                event = SignalEvent(
                    device_id=self.device_id,
                    provider=Provider.CODEX,
                    session_id=thread_id,
                    project="",
                    event_type=EventType.MEMORY,
                    timestamp=ts,
                    payload=payload,
                    source_file=str(self.memories_db),
                )
                event.compute_hashes()
                events.append(event)
                seen.add(thread_id)

            conn.close()

        except sqlite3.Error as exc:
            logger.warning("Error reading Codex memories: %s", exc)

        if events:
            state["seen_memories"] = sorted(seen)
            logger.info("Codex: %d new memories", len(events))

        return events

    def poll(self) -> list[SignalEvent]:
        """Run one poll cycle — read new data from both databases."""
        state = self._load_state()
        events: list[SignalEvent] = []

        events.extend(self._read_logs(state))
        events.extend(self._read_memories(state))

        if events:
            self._save_state(state)
            self.on_events(events)

        return events
