"""Signal agent configuration."""

from __future__ import annotations

import socket
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_device_id() -> str:
    return socket.gethostname().split(".")[0].lower().replace(" ", "-")


class SignalConfig(BaseSettings):
    """Configuration for the Signal capture agent.

    Values are read from environment variables prefixed with SIGNAL_,
    or from a .env file at ~/.signal-agent/.env.
    """

    model_config = SettingsConfigDict(
        env_prefix="SIGNAL_",
        env_file=str(Path.home() / ".signal-agent" / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Anton connection
    anton_url: str = "http://192.168.0.9:8080"
    api_key: str = ""

    # Device identity
    device_id: str = Field(default_factory=_default_device_id)

    # Watch paths
    antigravity_brain_dir: Path = Field(
        default_factory=lambda: Path.home() / ".gemini" / "antigravity-ide" / "brain"
    )
    claude_projects_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )
    claude_tasks_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claude" / "tasks"
    )
    codex_dir: Path = Field(default_factory=lambda: Path.home() / ".codex")

    # Queue settings
    queue_db_path: Path = Field(
        default_factory=lambda: Path.home() / ".signal-agent" / "queue.db"
    )
    queue_max_bytes: int = 500 * 1024 * 1024  # 500MB
    queue_max_age_days: int = 7
    queue_retry_base_seconds: float = 1.0
    queue_retry_max_seconds: float = 300.0  # 5 minutes
    queue_batch_size: int = 50

    # Adapter settings
    codex_poll_interval_seconds: float = 30.0

    # State tracking
    state_dir: Path = Field(
        default_factory=lambda: Path.home() / ".signal-agent" / "state"
    )

    # Logging
    log_file: Path = Field(
        default_factory=lambda: Path.home() / ".signal-agent" / "signal-agent.log"
    )
    log_level: str = "INFO"

    def ensure_dirs(self) -> None:
        """Create necessary directories if they don't exist."""
        self.queue_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
