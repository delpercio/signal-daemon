"""Signal daemon CLI."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import click

from signal_daemon.config import SignalConfig
from signal_daemon.queue import DeliveryQueue, QueueSender
from signal_daemon.schema import EventType, Provider, SignalEvent


@click.group()
def cli():
    """Signal — AI development activity capture daemon."""
    pass


@cli.command()
def start():
    """Start the Signal capture daemon."""
    from signal_daemon.daemon import SignalDaemon

    config = SignalConfig()
    if not config.api_key:
        click.echo(
            "⚠  SIGNAL_API_KEY not set. Events will be queued locally but not "
            "delivered until Anton's API key is configured.",
            err=True,
        )
        click.echo(
            "   Set it in ~/.signal-daemon/.env or as an environment variable.",
            err=True,
        )

    daemon = SignalDaemon(config)
    click.echo(f"Signal daemon starting (device: {config.device_id})...")
    daemon.run_forever()


@cli.command()
def status():
    """Show queue status and adapter health."""
    config = SignalConfig()
    config.ensure_dirs()

    queue = DeliveryQueue(db_path=config.queue_db_path)
    stats = queue.stats()

    click.echo("Signal Daemon Status")
    click.echo("=" * 40)
    click.echo(f"Device ID:       {config.device_id}")
    click.echo(f"Anton URL:       {config.anton_url}")
    click.echo(f"API Key:         {'✓ configured' if config.api_key else '✗ not set'}")
    click.echo()
    click.echo("Queue:")
    click.echo(f"  Pending:       {stats['pending']}")
    click.echo(f"  Delivered:     {stats['delivered']}")
    click.echo(f"  Total:         {stats['total']}")
    click.echo(f"  DB size:       {stats['db_size_mb']} MB")
    click.echo()
    click.echo("Watch Paths:")
    click.echo(f"  Antigravity:   {config.antigravity_brain_dir}")
    click.echo(f"    exists:      {'✓' if config.antigravity_brain_dir.exists() else '✗'}")
    click.echo(f"  Claude Code:   {config.claude_projects_dir}")
    click.echo(f"    exists:      {'✓' if config.claude_projects_dir.exists() else '✗'}")
    click.echo(f"  Claude Tasks:  {config.claude_tasks_dir}")
    click.echo(f"    exists:      {'✓' if config.claude_tasks_dir.exists() else '✗'}")
    click.echo(f"  Codex:         {config.codex_dir}")
    click.echo(f"    exists:      {'✓' if config.codex_dir.exists() else '✗'}")


@cli.command()
def flush():
    """Force immediate delivery of all pending events."""
    config = SignalConfig()
    config.ensure_dirs()

    if not config.api_key:
        click.echo("Error: SIGNAL_API_KEY not set. Cannot deliver events.", err=True)
        sys.exit(1)

    queue = DeliveryQueue(db_path=config.queue_db_path)
    pending = queue.pending_count()

    if pending == 0:
        click.echo("Queue is empty — nothing to flush.")
        return

    click.echo(f"Flushing {pending} pending events to {config.anton_url}...")
    sender = QueueSender(
        queue=queue,
        anton_url=config.anton_url,
        api_key=config.api_key,
    )
    sender.drain()

    remaining = queue.pending_count()
    click.echo(f"Done. Remaining in queue: {remaining}")


@cli.command()
def test():
    """Send a test event to Anton to verify connectivity."""
    config = SignalConfig()
    config.ensure_dirs()

    if not config.api_key:
        click.echo("Error: SIGNAL_API_KEY not set.", err=True)
        sys.exit(1)

    event = SignalEvent(
        device_id=config.device_id,
        provider=Provider.ANTIGRAVITY,
        session_id="test-session",
        project="signal-test",
        event_type=EventType.TRANSCRIPT_STEP,
        timestamp=datetime.now(timezone.utc),
        payload={
            "test": True,
            "message": "Signal daemon connectivity test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    event.compute_hashes()

    click.echo(f"Sending test event to {config.anton_url}/api/signal/ingest...")

    import httpx

    from signal_daemon.schema import SignalEventBatch

    batch = SignalEventBatch(events=[event])
    try:
        resp = httpx.post(
            f"{config.anton_url.rstrip('/')}/api/signal/ingest",
            content=batch.model_dump_json(),
            headers={
                "Content-Type": "application/json",
                "X-Signal-Key": config.api_key,
            },
            timeout=10.0,
        )
        click.echo(f"Response: {resp.status_code} {resp.text}")
        if resp.status_code in (200, 201):
            click.echo("✓ Test event delivered successfully!")
        else:
            click.echo("✗ Delivery failed.", err=True)
            sys.exit(1)
    except Exception as exc:
        click.echo(f"✗ Connection failed: {exc}", err=True)
        sys.exit(1)


@cli.command()
def scan():
    """Run a one-time scan of all tools and report what would be captured."""
    config = SignalConfig()
    config.ensure_dirs()

    from signal_daemon.adapters.antigravity import AntigravityAdapter
    from signal_daemon.adapters.claude_code import (
        ClaudeCodeConversationHandler,
        ClaudeCodeTaskHandler,
    )
    from signal_daemon.adapters.codex import CodexAdapter

    collected: list[SignalEvent] = []

    click.echo("Scanning Antigravity...")
    ag = AntigravityAdapter(
        brain_dir=config.antigravity_brain_dir,
        device_id=config.device_id,
        on_events=collected.extend,
        state_dir=config.state_dir,
    )
    ag_events = ag.scan_existing()
    click.echo(f"  Found {len(ag_events)} events")

    click.echo("Scanning Claude Code conversations...")
    cc = ClaudeCodeConversationHandler(
        projects_dir=config.claude_projects_dir,
        device_id=config.device_id,
        on_events=collected.extend,
        state_dir=config.state_dir,
    )
    cc_events = cc.scan_existing()
    click.echo(f"  Found {len(cc_events)} events")

    click.echo("Scanning Claude Code tasks...")
    ct = ClaudeCodeTaskHandler(
        tasks_dir=config.claude_tasks_dir,
        device_id=config.device_id,
        on_events=collected.extend,
        state_dir=config.state_dir,
    )
    ct_events = ct.scan_existing()
    click.echo(f"  Found {len(ct_events)} events")

    click.echo("Scanning Codex...")
    cx = CodexAdapter(
        codex_dir=config.codex_dir,
        device_id=config.device_id,
        on_events=collected.extend,
        state_dir=config.state_dir,
    )
    cx_events = cx.poll()
    click.echo(f"  Found {len(cx_events)} events")

    total = len(ag_events) + len(cc_events) + len(ct_events) + len(cx_events)
    click.echo()
    click.echo(f"Total: {total} events across all tools")
    click.echo("(Events were enqueued locally — use 'flush' to deliver)")


if __name__ == "__main__":
    cli()
