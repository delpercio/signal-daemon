"""Signal daemon — runs all adapters and the queue sender."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time

from signal_daemon.adapters.antigravity import AntigravityAdapter
from signal_daemon.adapters.claude_code import (
    ClaudeCodeConversationHandler,
    ClaudeCodeTaskHandler,
)
from signal_daemon.adapters.codex import CodexAdapter
from signal_daemon.config import SignalConfig
from signal_daemon.queue import DeliveryQueue, QueueSender
from signal_daemon.schema import SignalEvent

logger = logging.getLogger(__name__)


class SignalDaemon:
    """Main daemon that orchestrates all adapters and the delivery queue."""

    def __init__(self, config: SignalConfig | None = None):
        self.config = config or SignalConfig()
        self.config.ensure_dirs()
        self._setup_logging()

        self.queue = DeliveryQueue(
            db_path=self.config.queue_db_path,
            max_bytes=self.config.queue_max_bytes,
            max_age_days=self.config.queue_max_age_days,
        )

        self.sender = QueueSender(
            queue=self.queue,
            anton_url=self.config.anton_url,
            api_key=self.config.api_key,
            batch_size=self.config.queue_batch_size,
            retry_base=self.config.queue_retry_base_seconds,
            retry_max=self.config.queue_retry_max_seconds,
        )

        # Adapters
        self.antigravity = AntigravityAdapter(
            brain_dir=self.config.antigravity_brain_dir,
            device_id=self.config.device_id,
            on_events=self._on_events,
            state_dir=self.config.state_dir,
        )

        self.claude_conv = ClaudeCodeConversationHandler(
            projects_dir=self.config.claude_projects_dir,
            device_id=self.config.device_id,
            on_events=self._on_events,
            state_dir=self.config.state_dir,
        )

        self.claude_tasks = ClaudeCodeTaskHandler(
            tasks_dir=self.config.claude_tasks_dir,
            device_id=self.config.device_id,
            on_events=self._on_events,
            state_dir=self.config.state_dir,
        )

        self.codex = CodexAdapter(
            codex_dir=self.config.codex_dir,
            device_id=self.config.device_id,
            on_events=self._on_events,
            state_dir=self.config.state_dir,
        )

        self._running = False
        self._sender_thread: threading.Thread | None = None
        self._codex_thread: threading.Thread | None = None

    def _setup_logging(self) -> None:
        """Configure logging to stdout and file."""
        root = logging.getLogger()
        root.setLevel(getattr(logging, self.config.log_level.upper(), logging.INFO))

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

        # File
        try:
            file_handler = logging.FileHandler(str(self.config.log_file))
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Could not open log file: %s", exc)

    def _on_events(self, events: list[SignalEvent]) -> None:
        """Callback from adapters — enqueue events for delivery."""
        count = self.queue.enqueue_many(events)
        if count:
            logger.debug("Enqueued %d events (queue pending: %d)", count, self.queue.pending_count())

    def _sender_loop(self) -> None:
        """Background thread: periodically drain the queue."""
        while self._running:
            try:
                if self.queue.pending_count() > 0:
                    self.sender.send_batch()
                self.queue.enforce_limits()
            except Exception as exc:
                logger.error("Sender error: %s", exc)

            # Sleep in small increments so we can exit quickly
            for _ in range(50):
                if not self._running:
                    break
                time.sleep(0.2)

    def _codex_poll_loop(self) -> None:
        """Background thread: poll Codex SQLite databases."""
        while self._running:
            try:
                self.codex.poll()
            except Exception as exc:
                logger.error("Codex poll error: %s", exc)

            # Sleep in small increments
            intervals = int(self.config.codex_poll_interval_seconds / 0.2)
            for _ in range(intervals):
                if not self._running:
                    break
                time.sleep(0.2)

    def start(self) -> None:
        """Start the daemon."""
        self._running = True
        logger.info("Signal daemon starting (device: %s)", self.config.device_id)

        # Initial scan of existing data
        logger.info("Running initial scan of existing data...")
        try:
            events = self.antigravity.scan_existing()
            self._on_events(events)
        except Exception as exc:
            logger.error("Antigravity initial scan failed: %s", exc)

        try:
            events = self.claude_conv.scan_existing()
            self._on_events(events)
        except Exception as exc:
            logger.error("Claude Code conv scan failed: %s", exc)

        try:
            events = self.claude_tasks.scan_existing()
            self._on_events(events)
        except Exception as exc:
            logger.error("Claude Code task scan failed: %s", exc)

        try:
            self.codex.poll()
        except Exception as exc:
            logger.error("Codex initial poll failed: %s", exc)

        # Start filesystem watchers
        self.antigravity.start()
        self.claude_conv.start()
        self.claude_tasks.start()

        # Start background threads
        self._sender_thread = threading.Thread(
            target=self._sender_loop, name="signal-sender", daemon=True
        )
        self._sender_thread.start()

        self._codex_thread = threading.Thread(
            target=self._codex_poll_loop, name="signal-codex", daemon=True
        )
        self._codex_thread.start()

        stats = self.queue.stats()
        logger.info(
            "Signal daemon started — pending: %d, delivered: %d, db: %.1f MB",
            stats["pending"],
            stats["delivered"],
            stats["db_size_mb"],
        )

    def stop(self) -> None:
        """Stop the daemon gracefully."""
        logger.info("Signal daemon stopping...")
        self._running = False

        self.antigravity.stop()
        self.claude_conv.stop()
        self.claude_tasks.stop()

        if self._sender_thread:
            self._sender_thread.join(timeout=5)
        if self._codex_thread:
            self._codex_thread.join(timeout=5)

        # Final flush attempt
        try:
            if self.queue.pending_count() > 0:
                logger.info("Final flush: %d events pending", self.queue.pending_count())
                self.sender.send_batch()
        except Exception as exc:
            logger.warning("Final flush failed: %s", exc)

        stats = self.queue.stats()
        logger.info(
            "Signal daemon stopped — pending: %d, delivered: %d",
            stats["pending"],
            stats["delivered"],
        )

    def run_forever(self) -> None:
        """Run until SIGTERM or SIGINT."""

        def handle_signal(signum, frame):
            logger.info("Received signal %d", signum)
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        self.start()

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
