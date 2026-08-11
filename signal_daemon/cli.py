"""Signal daemon CLI."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import click

from signal_daemon.config import SignalConfig
from signal_daemon.queue import DeliveryQueue, QueueSender
from signal_daemon.schema import EventType, Provider, SignalEvent


@click.group()
def cli():
    """Signal — AI development activity capture daemon."""
    pass


@cli.command()
def setup():
    """Interactive setup wizard to configure the daemon."""
    click.echo("Signal Daemon Setup")
    click.echo("===================\n")

    # 1. Config directory
    config_dir = Path.home() / ".signal-daemon"
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / ".env"

    # Default device ID
    default_device = socket.gethostname().split(".")[0].lower().replace(" ", "-")

    # Load existing if any
    existing_url = "http://192.168.0.9:8080"
    existing_key = ""
    existing_device = default_device

    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("SIGNAL_ANTON_URL="):
                existing_url = line.split("=", 1)[1].strip()
            elif line.startswith("SIGNAL_API_KEY="):
                existing_key = line.split("=", 1)[1].strip()
            elif line.startswith("SIGNAL_DEVICE_ID="):
                existing_device = line.split("=", 1)[1].strip()

    # 2. Prompts
    anton_url = click.prompt("Anton Server URL", default=existing_url)
    
    # Hide input for API key, don't show default in prompt string if it exists
    if existing_key:
        click.echo("API Key is already configured.")
        new_key = click.prompt("New API Key (leave empty to keep existing)", default="", hide_input=True, show_default=False)
        api_key = new_key if new_key else existing_key
    else:
        api_key = click.prompt("Signal API Key", hide_input=True)

    device_id = click.prompt("Device ID", default=existing_device)

    # 3. Write .env
    env_content = f"SIGNAL_ANTON_URL={anton_url}\nSIGNAL_API_KEY={api_key}\nSIGNAL_DEVICE_ID={device_id}\n"
    env_file.write_text(env_content)
    click.echo(f"\n✓ Configuration saved to {env_file}")

    # 4. LaunchAgent setup
    install_agent = click.confirm("\nInstall macOS LaunchAgent to start automatically on login?", default=True)
    
    if install_agent:
        executable = shutil.which("signal-daemon")
        if not executable:
            click.echo("⚠ Could not find 'signal-daemon' in PATH. Make sure to install it first (e.g., 'pip install -e .')")
            return

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.delpercio.signal-daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executable}</string>
    <string>start</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>/tmp/signal-daemon.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/signal-daemon.stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:{os.path.dirname(executable)}</string>
  </dict>
</dict>
</plist>"""

        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents_dir / "com.delpercio.signal-daemon.plist"
        
        plist_path.write_text(plist_content)
        click.echo(f"✓ Created LaunchAgent plist at {plist_path}")

        # Unload if it already exists, then load
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        res = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
        
        if res.returncode == 0:
            click.echo("✓ Daemon loaded and started in the background.")
        else:
            click.echo(f"⚠ Failed to load daemon: {res.stderr.decode()}")
    
    click.echo("\nSetup complete! You can view status with: signal-daemon status")



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
    stuck = queue.stuck_count(10)
    if stuck:
        click.echo(f"  Stuck:         {stuck} (retries exhausted, being skipped)")
    click.echo()

    if stats["total"]:
        from signal_daemon.dashboard import load_metrics
        from signal_daemon.metrics import summarise

        totals = summarise(load_metrics(config.queue_db_path))["totals"]
        click.echo("Captured (all time):")
        click.echo(f"  Sessions:      {totals['sessions']}")
        click.echo(
            f"  Tokens:        {totals['total_tokens']:,} "
            f"({totals['input_tokens']:,} in / {totals['output_tokens']:,} out)"
        )
        click.echo(
            f"  Cache:         {totals['cache_read_tokens']:,} read / "
            f"{totals['cache_creation_tokens']:,} written"
        )
        click.echo(f"  Est. cost:     ${totals['cost_usd']:.4f}")
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
@click.option(
    "--enqueue",
    is_flag=True,
    help="Queue what is found for delivery instead of only reporting it.",
)
def scan(enqueue: bool):
    """Report what would be captured, without consuming it.

    By default this is a true dry run: capture cursors are written to a
    throwaway directory so the daemon still picks these events up later.
    Pass --enqueue to actually capture them.
    """
    config = SignalConfig()
    config.ensure_dirs()

    from signal_daemon.adapters.antigravity import AntigravityAdapter
    from signal_daemon.adapters.claude_code import (
        ClaudeCodeConversationHandler,
        ClaudeCodeTaskHandler,
    )
    from signal_daemon.adapters.codex import CodexAdapter
    from signal_daemon.metrics import metrics_from_event, summarise

    collected: list[SignalEvent] = []

    with tempfile.TemporaryDirectory(prefix="signal-scan-") as scratch:
        if enqueue:
            state_dir = config.state_dir
        else:
            # Copy existing cursors so the scan starts from the real position
            # but never advances the daemon's own state.
            state_dir = Path(scratch)
            if config.state_dir.exists():
                shutil.copytree(config.state_dir, state_dir, dirs_exist_ok=True)

        def adapter_args(**extra):
            return dict(
                device_id=config.device_id,
                on_events=collected.extend,
                state_dir=state_dir,
                **extra,
            )

        click.echo("Scanning Antigravity...")
        ag_events = AntigravityAdapter(
            **adapter_args(brain_dir=config.antigravity_brain_dir)
        ).scan_existing()
        click.echo(f"  Found {len(ag_events)} events")

        click.echo("Scanning Claude Code conversations...")
        cc_events = ClaudeCodeConversationHandler(
            **adapter_args(projects_dir=config.claude_projects_dir)
        ).scan_existing()
        click.echo(f"  Found {len(cc_events)} events")

        click.echo("Scanning Claude Code tasks...")
        ct_events = ClaudeCodeTaskHandler(
            **adapter_args(tasks_dir=config.claude_tasks_dir)
        ).scan_existing()
        click.echo(f"  Found {len(ct_events)} events")

        click.echo("Scanning Codex...")
        cx_events = CodexAdapter(**adapter_args(codex_dir=config.codex_dir)).poll()
        click.echo(f"  Found {len(cx_events)} events")

    found = ag_events + cc_events + ct_events + cx_events
    click.echo()
    click.echo(f"Total: {len(found)} events across all tools")

    if found:
        summary = summarise([metrics_from_event(e) for e in found])
        t = summary["totals"]
        click.echo()
        click.echo("Metrics:")
        click.echo(f"  Sessions:      {t['sessions']}")
        click.echo(
            f"  Tokens:        {t['total_tokens']:,} "
            f"({t['input_tokens']:,} in / {t['output_tokens']:,} out)"
        )
        click.echo(
            f"  Cache:         {t['cache_read_tokens']:,} read / "
            f"{t['cache_creation_tokens']:,} written"
        )
        click.echo(f"  Est. cost:     ${t['cost_usd']:.4f}")
        if summary["by_model"]:
            click.echo("  Models:")
            for row in summary["by_model"][:5]:
                click.echo(
                    f"    {row['name']:<28} {row['total_tokens']:>12,} tok  "
                    f"${row['cost_usd']:.4f}"
                )

    click.echo()
    if enqueue:
        queue = DeliveryQueue(db_path=config.queue_db_path)
        added = queue.enqueue_many(found)
        click.echo(f"Enqueued {added} new event(s) — use 'flush' to deliver.")
    else:
        click.echo(
            "Dry run: nothing was captured or queued. "
            "Re-run with --enqueue to capture these events."
        )


@cli.command()
@click.option("--port", default=8787, show_default=True, help="Port to listen on.")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Address to bind. Loopback by default — captured payloads are private.",
)
@click.option("--no-browser", is_flag=True, help="Don't open a browser window.")
def dashboard(port: int, host: str, no_browser: bool):
    """Open a local dashboard for browsing the captured data."""
    from signal_daemon.dashboard import serve

    config = SignalConfig()
    config.ensure_dirs()

    if not config.queue_db_path.exists():
        click.echo(
            "No captured data yet — start the daemon with 'signal-daemon start' "
            "or run 'signal-daemon scan --enqueue' first.",
            err=True,
        )

    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo(
            f"⚠  Binding to {host} exposes captured conversation data to your "
            "network.",
            err=True,
        )

    click.echo(f"Signal dashboard: http://{host}:{port}/  (Ctrl-C to stop)")
    try:
        serve(config, host=host, port=port, open_browser=not no_browser)
    except OSError as exc:
        click.echo(f"Could not start dashboard: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
