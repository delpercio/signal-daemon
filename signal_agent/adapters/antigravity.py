"""Antigravity (Gemini) adapter.

Watches ~/.gemini/antigravity-ide/brain/ for new and modified transcripts,
artifacts, and scratch files. Each conversation UUID directory = one session.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from signal_agent.schema import EventType, Provider, SignalEvent

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _extract_project_from_transcript(path: Path) -> str:
    """Try to extract the project/workspace from the first transcript line."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("content", "")
                    # Look for workspace path in the content
                    if "Documents/" in content:
                        for part in content.split("Documents/"):
                            if "/" in part:
                                project = part.split("/")[0].split("\\")[0]
                                if project and len(project) < 100:
                                    return project
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return ""


class AntigravityAdapter(FileSystemEventHandler):
    """Filesystem watcher for Antigravity brain directory."""

    def __init__(
        self,
        brain_dir: Path,
        device_id: str,
        on_events: Callable[[list[SignalEvent]], None],
        state_dir: Path,
    ):
        self.brain_dir = brain_dir
        self.device_id = device_id
        self.on_events = on_events
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._observer: Observer | None = None

    def _state_file(self, conversation_id: str) -> Path:
        return self.state_dir / f"antigravity_{conversation_id}.json"

    def _load_state(self, conversation_id: str) -> dict:
        sf = self._state_file(conversation_id)
        if sf.exists():
            try:
                return json.loads(sf.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"last_step_index": -1, "seen_files": []}

    def _save_state(self, conversation_id: str, state: dict) -> None:
        sf = self._state_file(conversation_id)
        sf.write_text(json.dumps(state))

    def _parse_transcript(
        self, path: Path, conversation_id: str
    ) -> list[SignalEvent]:
        """Parse transcript JSONL, emitting only unseen steps."""
        state = self._load_state(conversation_id)
        last_seen = state.get("last_step_index", -1)
        project = _extract_project_from_transcript(path)

        events = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    step_index = data.get("step_index", -1)
                    if step_index <= last_seen:
                        continue

                    event = SignalEvent(
                        device_id=self.device_id,
                        provider=Provider.ANTIGRAVITY,
                        session_id=conversation_id,
                        project=project,
                        event_type=EventType.TRANSCRIPT_STEP,
                        timestamp=datetime.fromisoformat(data["created_at"])
                        if "created_at" in data
                        else datetime.now(timezone.utc),
                        payload=data,
                        source_file=str(path),
                    )
                    event.compute_hashes()
                    events.append(event)
                    last_seen = max(last_seen, step_index)

        except OSError as exc:
            logger.warning("Error reading transcript %s: %s", path, exc)

        if events:
            state["last_step_index"] = last_seen
            self._save_state(conversation_id, state)
            logger.info(
                "Antigravity: %d new steps from %s", len(events), conversation_id
            )

        return events

    def _handle_artifact(
        self, path: Path, conversation_id: str
    ) -> list[SignalEvent]:
        """Capture a non-transcript file as an artifact event."""
        state = self._load_state(conversation_id)
        seen = set(state.get("seen_files", []))
        file_key = str(path)

        if file_key in seen:
            return []

        try:
            stat = path.stat()
            mod_time = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except OSError:
            return []

        # For text files, capture content; for binary, just metadata
        payload: dict = {
            "filename": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
        }
        if path.suffix in (".md", ".py", ".json", ".jsonl", ".txt", ".ts", ".tsx"):
            try:
                payload["content"] = path.read_text(encoding="utf-8")[:50000]
            except OSError:
                pass

        event = SignalEvent(
            device_id=self.device_id,
            provider=Provider.ANTIGRAVITY,
            session_id=conversation_id,
            project="",
            event_type=EventType.ARTIFACT,
            timestamp=mod_time,
            payload=payload,
            source_file=str(path),
            source_file_hash=_file_hash(path),
            source_file_modified=mod_time,
        )
        event.compute_hashes()

        seen.add(file_key)
        state["seen_files"] = list(seen)
        self._save_state(conversation_id, state)
        return [event]

    def _conversation_id_from_path(self, path: Path) -> str | None:
        """Extract conversation UUID from a path within the brain directory."""
        try:
            rel = path.relative_to(self.brain_dir)
            parts = rel.parts
            if parts:
                return parts[0]
        except ValueError:
            pass
        return None

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle_fs_event(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_fs_event(event)

    def _handle_fs_event(self, fs_event: FileSystemEvent) -> None:
        if fs_event.is_directory:
            return

        path = Path(fs_event.src_path)
        conv_id = self._conversation_id_from_path(path)
        if not conv_id:
            return

        # Skip system-generated log files (we read them directly)
        if ".system_generated" in str(path) and path.name == "transcript_full.jsonl":
            return

        events: list[SignalEvent] = []
        if path.name == "transcript.jsonl":
            transcript_path = (
                self.brain_dir
                / conv_id
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            )
            if transcript_path.exists():
                events = self._parse_transcript(transcript_path, conv_id)
        elif path.suffix in (".md", ".py", ".json", ".txt", ".ts", ".tsx", ".webp"):
            events = self._handle_artifact(path, conv_id)

        if events:
            self.on_events(events)

    def scan_existing(self) -> list[SignalEvent]:
        """Scan for any existing conversations not yet captured."""
        all_events: list[SignalEvent] = []
        if not self.brain_dir.exists():
            return all_events

        for conv_dir in self.brain_dir.iterdir():
            if not conv_dir.is_dir() or conv_dir.name.startswith("."):
                continue

            conv_id = conv_dir.name
            transcript = (
                conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
            )
            if transcript.exists():
                events = self._parse_transcript(transcript, conv_id)
                all_events.extend(events)

        logger.info("Antigravity scan: found %d new events", len(all_events))
        return all_events

    def start(self) -> None:
        """Start watching the brain directory."""
        if not self.brain_dir.exists():
            logger.warning(
                "Antigravity brain dir does not exist: %s", self.brain_dir
            )
            return

        self._observer = Observer()
        self._observer.schedule(self, str(self.brain_dir), recursive=True)
        self._observer.start()
        logger.info("Antigravity watcher started: %s", self.brain_dir)

    def stop(self) -> None:
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("Antigravity watcher stopped")
