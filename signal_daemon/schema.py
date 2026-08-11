"""Universal event schema for Signal — the contract between the Mac agent and Anton."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Provider(StrEnum):
    ANTIGRAVITY = "antigravity"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class EventType(StrEnum):
    # Antigravity
    TRANSCRIPT_STEP = "transcript_step"
    ARTIFACT = "artifact"

    # Claude Code
    CONVERSATION_TURN = "conversation_turn"
    TASK_UPDATE = "task_update"

    # Codex
    LOG_ENTRY = "log_entry"
    MEMORY = "memory"

    # Shared
    FILE_CHANGE = "file_change"


class SignalEvent(BaseModel):
    """A single captured event from any AI coding tool."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    device_id: str
    provider: Provider
    session_id: str
    project: str = ""
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = ""
    payload_bytes: int = 0
    source_file: str = ""
    source_file_hash: str = ""
    source_file_modified: datetime | None = None

    def compute_hashes(self) -> None:
        """Compute payload hash and size from the current payload."""
        raw = json.dumps(self.payload, sort_keys=True, default=str)
        self.payload_bytes = len(raw.encode("utf-8"))
        self.payload_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SignalEventBatch(BaseModel):
    """A batch of events sent to Anton's ingestion endpoint."""

    events: list[SignalEvent]


class IngestResponse(BaseModel):
    """Response from Anton's ingestion endpoint."""

    accepted: int = 0
    duplicates: int = 0
    errors: int = 0


# ---------- Cost estimation helpers ----------


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts.

    Thin wrapper kept for callers that only have plain input/output counts.
    Prefer `signal_daemon.metrics.estimate_cost`, which also prices cache
    reads and writes — ignoring those overstates a cached session's cost.
    """
    from signal_daemon.metrics import TokenUsage
    from signal_daemon.metrics import estimate_cost as _estimate

    cost, _priced = _estimate(
        model, TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
    )
    return cost
