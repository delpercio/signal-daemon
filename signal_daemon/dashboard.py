"""Local dashboard for viewing captured activity.

Serves a read-only view of the local queue database over stdlib HTTP — no
extra dependencies, so it works from the standalone binary. Binds to loopback
by default: the queue holds conversation payloads and should not be exposed
on the network.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from signal_daemon.config import SignalConfig
from signal_daemon.dashboard_html import DASHBOARD_HTML
from signal_daemon.metrics import EventMetrics, extract_metrics, summarise

logger = logging.getLogger(__name__)

MAX_RECENT = 100
DEFAULT_MAX_ATTEMPTS = 10


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def load_metrics(db_path: Path, days: int = 0) -> list[EventMetrics]:
    """Read events from the local queue DB and normalise them.

    Opens read-only so a running daemon is never disturbed.
    """
    if not db_path.exists():
        return []

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT payload_json FROM events ORDER BY id DESC"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Could not read queue database: %s", exc)
        return []
    finally:
        conn.close()

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None
    )

    out: list[EventMetrics] = []
    for (payload_json,) in rows:
        try:
            raw = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            continue

        ts = _parse_ts(raw.get("timestamp"))
        if cutoff and (ts is None or ts < cutoff):
            continue

        payload = raw.get("payload")
        out.append(
            extract_metrics(
                event_id=raw.get("event_id", ""),
                provider=str(raw.get("provider", "")),
                event_type=str(raw.get("event_type", "")),
                session_id=str(raw.get("session_id", "")),
                project=str(raw.get("project", "")),
                timestamp=ts,
                payload=payload if isinstance(payload, dict) else {},
                device_id=str(raw.get("device_id", "")),
                payload_bytes=raw.get("payload_bytes") or 0,
            )
        )
    return out


def _matches(m: EventMetrics, q: str) -> bool:
    if not q:
        return True
    needle = q.lower()
    haystack = (
        m.session_id,
        m.project,
        m.model,
        m.event_type,
        m.provider,
        m.role,
        *m.tool_names,
    )
    return any(needle in str(v).lower() for v in haystack)


def build_payload(config: SignalConfig, query: dict) -> dict:
    """Assemble the JSON the dashboard renders."""

    def one(key: str, default: str = "") -> str:
        values = query.get(key)
        return values[0].strip() if values else default

    try:
        days = int(one("days", "0") or 0)
    except ValueError:
        days = 0

    everything = load_metrics(config.queue_db_path, days=days)

    provider = one("provider")
    project = one("project")
    model = one("model")
    search = one("q")

    filtered = [
        m
        for m in everything
        if (not provider or m.provider == provider)
        and (not project or (m.project or "(unattributed)") == project)
        and (not model or (m.model or "(no model)") == model)
        and _matches(m, search)
    ]

    summary = summarise(filtered)

    recent = []
    for m in filtered[:MAX_RECENT]:
        recent.append(
            {
                "time": m.timestamp.astimezone().strftime("%m-%d %H:%M")
                if m.timestamp
                else "—",
                "provider": m.provider,
                "project": m.project,
                "model": m.model,
                "event_type": m.event_type,
                "input_tokens": m.usage.input_tokens,
                "output_tokens": m.usage.output_tokens,
                "cost_usd": m.cost_usd,
                "cost_is_estimate": m.cost_is_estimate,
            }
        )

    # Facets come from the unfiltered set so a selection never empties the
    # dropdown that produced it.
    def facet(values) -> list[str]:
        return sorted({v for v in values if v})

    queue_stats = {"pending": 0, "delivered": 0, "total": 0, "stuck": 0}
    if config.queue_db_path.exists():
        try:
            from signal_daemon.queue import DeliveryQueue

            q = DeliveryQueue(db_path=config.queue_db_path)
            stats = q.stats()
            queue_stats = {
                "pending": stats["pending"],
                "delivered": stats["delivered"],
                "total": stats["total"],
                "stuck": q.stuck_count(DEFAULT_MAX_ATTEMPTS),
            }
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug("Queue stats unavailable: %s", exc)

    range_label = f"last {days} day(s)" if days > 0 else "all time"

    return {
        **summary,
        "recent": recent,
        "queue": queue_stats,
        "device_id": config.device_id,
        "range_label": range_label,
        "facets": {
            "providers": facet(m.provider for m in everything),
            "projects": facet(
                (m.project or "(unattributed)") for m in everything
            ),
            "models": facet((m.model or "(no model)") for m in everything),
        },
    }


class _Handler(BaseHTTPRequestHandler):
    config: SignalConfig = None  # set by serve()
    server_version = "SignalDashboard/1.0"

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Local-only page; keep it out of any embedding context.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self._send(
                200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8"
            )
            return

        if parsed.path == "/api/summary":
            try:
                payload = build_payload(self.config, parse_qs(parsed.query))
                body = json.dumps(payload, default=str).encode("utf-8")
            except Exception as exc:
                logger.exception("Dashboard query failed")
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(500, body, "application/json")
                return
            self._send(200, body, "application/json")
            return

        self._send(404, b"Not found", "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("dashboard %s", fmt % args)


def serve(
    config: SignalConfig,
    host: str = "127.0.0.1",
    port: int = 8787,
    open_browser: bool = True,
) -> None:
    """Run the dashboard until interrupted."""
    config.ensure_dirs()

    handler = type("Handler", (_Handler,), {"config": config})
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
