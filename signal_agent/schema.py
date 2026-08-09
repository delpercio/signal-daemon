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

# Approximate per-1K-token costs (USD) as of mid-2026.
# These are rough estimates for cost tracking, not billing.
MODEL_COSTS_PER_1K: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4": {"input": 0.003, "output": 0.015},
    "claude-haiku-3.5": {"input": 0.0008, "output": 0.004},
    # Google
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.01},
    "gemini-2.5-flash": {"input": 0.00015, "output": 0.0006},
    "gemini-3.1-pro": {"input": 0.002, "output": 0.012},
    # OpenAI
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "o3": {"input": 0.01, "output": 0.04},
    "codex-mini": {"input": 0.0015, "output": 0.006},
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    # Try exact match first, then prefix match
    costs = MODEL_COSTS_PER_1K.get(model)
    if costs is None:
        for key, val in MODEL_COSTS_PER_1K.items():
            if model.startswith(key) or key.startswith(model):
                costs = val
                break
    if costs is None:
        # Unknown model — use a conservative mid-range estimate
        costs = {"input": 0.003, "output": 0.015}

    return (input_tokens / 1000 * costs["input"]) + (
        output_tokens / 1000 * costs["output"]
    )
