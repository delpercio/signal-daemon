"""Local SQLite-backed delivery queue with retry and deduplication.

Events are written locally first so data is never lost if Anton is offline.
A background sender drains the queue with exponential backoff + jitter.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils

from signal_agent.schema import SignalEvent, SignalEventBatch

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT UNIQUE NOT NULL,
    payload_json TEXT NOT NULL,
    enqueued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_pending
    ON events(delivered, id) WHERE delivered = 0;

CREATE INDEX IF NOT EXISTS idx_events_enqueued
    ON events(enqueued_at);
"""


class DeliveryQueue:
    """Persistent local queue backed by SQLite."""

    def __init__(
        self,
        db_path: Path,
        max_bytes: int = 500 * 1024 * 1024,
        max_age_days: int = 7,
    ):
        self.db_path = db_path
        self.max_bytes = max_bytes
        self.max_age_days = max_age_days
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite_utils.Database(str(db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        self.db.executescript(_SCHEMA_SQL)

    def enqueue(self, event: SignalEvent) -> bool:
        """Add an event to the queue. Returns False if duplicate."""
        try:
            self.db["events"].insert(
                {
                    "event_id": event.event_id,
                    "payload_json": event.model_dump_json(),
                    "enqueued_at": datetime.now(timezone.utc).isoformat(),
                    "attempts": 0,
                    "delivered": 0,
                },
                pk="id",
            )
            logger.debug("Enqueued event %s", event.event_id)
            return True
        except Exception:
            # Duplicate event_id — UNIQUE constraint
            logger.debug("Duplicate event %s, skipping", event.event_id)
            return False

    def enqueue_many(self, events: list[SignalEvent]) -> int:
        """Enqueue multiple events. Returns count of newly enqueued."""
        count = 0
        for event in events:
            if self.enqueue(event):
                count += 1
        return count

    def pending_count(self) -> int:
        """Number of events waiting to be delivered."""
        rows = list(
            self.db.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE delivered = 0"
            ).fetchall()
        )
        return rows[0][0] if rows else 0

    def fetch_batch(self, batch_size: int = 50) -> list[dict]:
        """Fetch the next batch of undelivered events, oldest first."""
        rows = list(
            self.db.execute(
                "SELECT id, event_id, payload_json FROM events "
                "WHERE delivered = 0 ORDER BY id ASC LIMIT ?",
                [batch_size],
            ).fetchall()
        )
        return [
            {"id": r[0], "event_id": r[1], "payload_json": r[2]} for r in rows
        ]

    def mark_delivered(self, row_ids: list[int]) -> None:
        """Mark events as successfully delivered."""
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            f"UPDATE events SET delivered = 1, delivered_at = ? "
            f"WHERE id IN ({placeholders})",
            [now] + row_ids,
        )
        logger.info("Marked %d events as delivered", len(row_ids))

    def mark_attempt(self, row_ids: list[int]) -> None:
        """Increment attempt counter for failed delivery."""
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            f"UPDATE events SET attempts = attempts + 1, last_attempt_at = ? "
            f"WHERE id IN ({placeholders})",
            [now] + row_ids,
        )

    def enforce_limits(self) -> int:
        """Remove old and over-quota events. Returns count removed."""
        removed = 0

        # Age limit
        if self.max_age_days > 0:
            from datetime import timedelta

            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=self.max_age_days)
            ).isoformat()
            result = self.db.execute(
                "DELETE FROM events WHERE delivered = 1 AND delivered_at < ?",
                [cutoff],
            )
            removed += result.rowcount

            # Also remove very old undelivered events
            result = self.db.execute(
                "DELETE FROM events WHERE delivered = 0 AND enqueued_at < ?",
                [cutoff],
            )
            removed += result.rowcount

        # Size limit
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        if db_size > self.max_bytes:
            # Remove oldest delivered events first
            result = self.db.execute(
                "DELETE FROM events WHERE delivered = 1 "
                "ORDER BY delivered_at ASC LIMIT 1000"
            )
            removed += result.rowcount
            if self.db_path.stat().st_size > self.max_bytes:
                self.db.execute("VACUUM")

        if removed > 0:
            logger.info("Queue cleanup: removed %d events", removed)
        return removed

    def stats(self) -> dict:
        """Return queue statistics."""
        rows = list(
            self.db.execute(
                "SELECT "
                "  COUNT(*) as total, "
                "  SUM(CASE WHEN delivered = 0 THEN 1 ELSE 0 END) as pending, "
                "  SUM(CASE WHEN delivered = 1 THEN 1 ELSE 0 END) as delivered "
                "FROM events"
            ).fetchall()
        )
        r = rows[0] if rows else (0, 0, 0)
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total": r[0],
            "pending": r[1] or 0,
            "delivered": r[2] or 0,
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
        }


class QueueSender:
    """Background sender that drains the queue to Anton."""

    def __init__(
        self,
        queue: DeliveryQueue,
        anton_url: str,
        api_key: str,
        batch_size: int = 50,
        retry_base: float = 1.0,
        retry_max: float = 300.0,
    ):
        self.queue = queue
        self.ingest_url = f"{anton_url.rstrip('/')}/api/signal/ingest"
        self.api_key = api_key
        self.batch_size = batch_size
        self.retry_base = retry_base
        self.retry_max = retry_max
        self._consecutive_failures = 0

    def _backoff_delay(self) -> float:
        """Calculate delay with exponential backoff + jitter."""
        delay = min(
            self.retry_base * (2 ** self._consecutive_failures),
            self.retry_max,
        )
        # Add jitter: ±25%
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return max(0.1, delay + jitter)

    def send_batch(self) -> bool:
        """Attempt to send one batch. Returns True if successful or queue empty."""
        import httpx

        batch = self.queue.fetch_batch(self.batch_size)
        if not batch:
            self._consecutive_failures = 0
            return True

        row_ids = [r["id"] for r in batch]
        events = []
        for row in batch:
            try:
                event = SignalEvent.model_validate_json(row["payload_json"])
                events.append(event)
            except Exception as exc:
                logger.warning("Corrupt event %s: %s", row["event_id"], exc)

        if not events:
            # All events were corrupt — mark them delivered to skip
            self.queue.mark_delivered(row_ids)
            return True

        payload = SignalEventBatch(events=events)

        try:
            resp = httpx.post(
                self.ingest_url,
                content=payload.model_dump_json(),
                headers={
                    "Content-Type": "application/json",
                    "X-Signal-Key": self.api_key,
                },
                timeout=30.0,
            )
            if resp.status_code in (200, 201):
                self.queue.mark_delivered(row_ids)
                self._consecutive_failures = 0
                logger.info(
                    "Delivered %d events to Anton (%s)",
                    len(events),
                    resp.text[:200],
                )
                return True
            else:
                logger.warning(
                    "Anton returned %d: %s", resp.status_code, resp.text[:200]
                )
                self.queue.mark_attempt(row_ids)
                self._consecutive_failures += 1
                return False
        except Exception as exc:
            logger.warning("Failed to send to Anton: %s", exc)
            self.queue.mark_attempt(row_ids)
            self._consecutive_failures += 1
            return False

    def drain(self, max_iterations: int = 100) -> int:
        """Send all pending events. Returns total events sent."""
        total_sent = 0
        for _ in range(max_iterations):
            if self.queue.pending_count() == 0:
                break
            if self.send_batch():
                batch = self.queue.fetch_batch(1)
                if not batch:
                    break
                total_sent += self.batch_size
            else:
                delay = self._backoff_delay()
                logger.info("Backing off %.1fs before retry", delay)
                time.sleep(delay)
        return total_sent
