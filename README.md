# Signal Capture Daemon

Signal is a background daemon for macOS that captures your AI development activity (from Antigravity, Claude Code, and Codex) and securely forwards it to your Anton server for analytics, cost tracking, and logging.

## Installation (Mac)

You don't need to install Python or configure virtual environments. We build a standalone binary for macOS.

### The "Click to Install" Way (GitHub Releases)
1. Go to the **[Releases](../../releases/latest)** page on this GitHub repository.
2. Download the `signal-daemon` binary asset.
3. Open your Terminal and move the binary to your local bin path:
   ```bash
   mv ~/Downloads/signal-daemon ~/.local/bin/
   chmod +x ~/.local/bin/signal-daemon
   ```
4. Run the setup wizard to configure your connection to Anton and start the background process:
   ```bash
   signal-daemon setup
   ```

### The Developer Way (From Source)
If you want to run it from source (requires Python 3):
1. Clone this repository.
2. Run the included installer script:
   ```bash
   ./install.sh
   ```
   *This creates an isolated virtual environment and launches the setup wizard automatically.*

## Commands
- `signal-daemon setup` — Interactive configuration wizard (API key, Anton URL).
- `signal-daemon status` — Health, queue size, and captured token/cost totals.
- `signal-daemon dashboard` — Open a local web dashboard for browsing what was captured.
- `signal-daemon flush` — Force an immediate delivery of all pending events in the queue.
- `signal-daemon scan` — Dry-run scan reporting what would be captured. Add `--enqueue` to actually capture it.

## Viewing your data

```bash
signal-daemon dashboard
```

Opens `http://127.0.0.1:8787` with a breakdown of everything captured so far:
token usage (including cache reads and writes), estimated cost, activity per
day, and per-provider/model/project/tool splits — filterable by date range,
provider, project, model, and free-text search.

The dashboard reads the local queue database directly and needs no connection
to Anton, so it works offline and before anything has been delivered. It binds
to loopback by default because captured payloads contain your conversation
content; `--host` will override that, but only do so on a network you trust.

**Costs are estimates.** They are computed from published list prices —
including the cache-write premium and the discounted cache-read rate — not from
billing data. Figures shown in grey used a fallback rate because the model
wasn't recognised.

## How it works
The daemon runs locally on your Mac using a standard macOS `LaunchAgent`. It silently watches the output directories of your AI tools. When new data is found, it is securely queued in a local SQLite database and forwarded to your Anton server with exponential backoff and retry handling.

Each tool's payload is stored verbatim so nothing is lost in translation;
`signal_daemon/metrics.py` normalises those payloads into comparable token,
model, and cost figures for the dashboard and for Anton.

## Development

```bash
pip install -e ".[dev]"
pytest
```
