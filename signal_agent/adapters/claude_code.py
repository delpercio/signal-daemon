"""Claude Code adapter.

Watches ~/.claude/projects/ for JSONL conversation files and
~/.claude/tasks/ for task JSON files. Session ID comes from
the filename (UUID) and the encoded workspace path gives us the project.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from signal_agent.schema import EventType, Provider, SignalEvent

logger = logging.getLogger(__name__)


def _decode_project_path(encoded: str) -> str:
    """Decode Claude Code's directory-name encoding to extract project name.

    Example: '-Users-stevendelpercio-Documents-Anton-Workspace' -> 'Anton workspace'
    """
    # Remove leading dash, split on dash, take last meaningful segment
    parts = encoded.lstrip("-").split("-")
    # Find 'Documents' index and take what follows
    try:
        doc_idx = parts.index("Documents")
        remaining = parts[doc_idx + 1 :]
        if remaining:
            return " ".join(remaining).replace("Workspace", "workspace")
    except ValueError:
        pass
    # Fallback: use last 2 segments
    if len(parts) >= 2:
        return "-".join(parts[-2:])
    return encoded


class ClaudeCodeConversationHandler(FileSystemEventHandler):
    """Watches JSONL conversation files in ~/.claude/projects/."""

    def __init__(
        self,
        projects_dir: Path,
        device_id: str,
        on_events: Callable[[list[SignalEvent]], None],
        state_dir: Path,
    ):
        self.projects_dir = projects_dir
        self.device_id = device_id
        self.on_events = on_events
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._observer: Observer | None = None

    def _state_file(self, session_id: str) -> Path:
        return self.state_dir / f"claude_conv_{session_id}.json"

    def _load_line_count(self, session_id: str) -> int:
        sf = self._state_file(session_id)
        if sf.exists():
            try:
                data = json.loads(sf.read_text())
                return data.get("last_line", 0)
            except (json.JSONDecodeError, OSError):
                pass
        return 0

    def _save_line_count(self, session_id: str, count: int) -> None:
        sf = self._state_file(session_id)
        sf.write_text(json.dumps({"last_line": count}))

    def _parse_jsonl(self, path: Path) -> list[SignalEvent]:
        """Parse new lines from a Claude Code JSONL conversation file."""
        session_id = path.stem  # UUID filename without .jsonl
        project_dir = path.parent.name
        project = _decode_project_path(project_dir)

        last_line = self._load_line_count(session_id)
        events = []
        current_line = 0

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    current_line += 1
                    if current_line <= last_line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Extract timestamp
                    ts_str = data.get("timestamp")
                    ts = (
                        datetime.fromisoformat(ts_str)
                        if ts_str
                        else datetime.now(timezone.utc)
                    )

                    event = SignalEvent(
                        device_id=self.device_id,
                        provider=Provider.CLAUDE_CODE,
                        session_id=data.get("sessionId", session_id),
                        project=project,
                        event_type=EventType.CONVERSATION_TURN,
                        timestamp=ts,
                        payload=data,
                        source_file=str(path),
                    )
                    event.compute_hashes()
                    events.append(event)

        except OSError as exc:
            logger.warning("Error reading Claude Code JSONL %s: %s", path, exc)

        if events:
            self._save_line_count(session_id, current_line)
            logger.info(
                "Claude Code: %d new turns from session %s",
                len(events),
                session_id[:8],
            )

        return events

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, fs_event: FileSystemEvent) -> None:
        if fs_event.is_directory:
            return
        path = Path(fs_event.src_path)
        if path.suffix != ".jsonl":
            return
        events = self._parse_jsonl(path)
        if events:
            self.on_events(events)

    def scan_existing(self) -> list[SignalEvent]:
        """Scan for existing JSONL files not yet fully captured."""
        all_events: list[SignalEvent] = []
        if not self.projects_dir.exists():
            return all_events

        for project_dir in self.projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                events = self._parse_jsonl(jsonl_file)
                all_events.extend(events)

        logger.info("Claude Code conv scan: found %d new events", len(all_events))
        return all_events

    def start(self) -> None:
        if not self.projects_dir.exists():
            logger.warning(
                "Claude Code projects dir does not exist: %s", self.projects_dir
            )
            return
        self._observer = Observer()
        self._observer.schedule(self, str(self.projects_dir), recursive=True)
        self._observer.start()
        logger.info("Claude Code conversation watcher started: %s", self.projects_dir)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Claude Code conversation watcher stopped")


class ClaudeCodeTaskHandler(FileSystemEventHandler):
    """Watches JSON task files in ~/.claude/tasks/."""

    def __init__(
        self,
        tasks_dir: Path,
        device_id: str,
        on_events: Callable[[list[SignalEvent]], None],
        state_dir: Path,
    ):
        self.tasks_dir = tasks_dir
        self.device_id = device_id
        self.on_events = on_events
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._observer: Observer | None = None

    def _state_file(self, session_id: str) -> Path:
        return self.state_dir / f"claude_task_{session_id}.json"

    def _load_seen_tasks(self, session_id: str) -> set[str]:
        sf = self._state_file(session_id)
        if sf.exists():
            try:
                data = json.loads(sf.read_text())
                return set(data.get("seen", []))
            except (json.JSONDecodeError, OSError):
                pass
        return set()

    def _save_seen_tasks(self, session_id: str, seen: set[str]) -> None:
        sf = self._state_file(session_id)
        sf.write_text(json.dumps({"seen": sorted(seen)}))

    def _parse_task(self, path: Path, session_id: str) -> SignalEvent | None:
        """Parse a single task JSON file."""
        task_key = f"{session_id}/{path.name}"
        seen = self._load_seen_tasks(session_id)

        # Check content hash to detect updates
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Skipping task file %s: %s", path, exc)
            return None

        content_hash = f"{task_key}:{hash(content)}"
        if content_hash in seen:
            return None

        stat = path.stat()
        event = SignalEvent(
            device_id=self.device_id,
            provider=Provider.CLAUDE_CODE,
            session_id=session_id,
            project="",
            event_type=EventType.TASK_UPDATE,
            timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            payload=data,
            source_file=str(path),
        )
        event.compute_hashes()

        seen.add(content_hash)
        self._save_seen_tasks(session_id, seen)
        return event

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def _handle(self, fs_event: FileSystemEvent) -> None:
        if fs_event.is_directory:
            return
        path = Path(fs_event.src_path)
        if path.suffix != ".json" or path.name.startswith("."):
            return

        session_id = path.parent.name
        event = self._parse_task(path, session_id)
        if event:
            self.on_events([event])

    def scan_existing(self) -> list[SignalEvent]:
        """Scan existing task directories."""
        all_events: list[SignalEvent] = []
        if not self.tasks_dir.exists():
            return all_events

        for session_dir in self.tasks_dir.iterdir():
            if not session_dir.is_dir():
                continue
            session_id = session_dir.name
            for task_file in session_dir.glob("*.json"):
                if task_file.name.startswith("."):
                    continue
                event = self._parse_task(task_file, session_id)
                if event:
                    all_events.append(event)

        logger.info("Claude Code task scan: found %d new events", len(all_events))
        return all_events

    def start(self) -> None:
        if not self.tasks_dir.exists():
            logger.warning(
                "Claude Code tasks dir does not exist: %s", self.tasks_dir
            )
            return
        self._observer = Observer()
        self._observer.schedule(self, str(self.tasks_dir), recursive=True)
        self._observer.start()
        logger.info("Claude Code task watcher started: %s", self.tasks_dir)

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Claude Code task watcher stopped")
