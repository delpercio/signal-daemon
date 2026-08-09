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
- `signal-daemon status` — View the health, queue size, and captured event count.
- `signal-daemon flush` — Force an immediate delivery of all pending events in the queue.
- `signal-daemon scan` — Dry-run scan to see what events would be captured without sending anything.

## How it works
The daemon runs locally on your Mac using a standard macOS `LaunchAgent`. It silently watches the output directories of your AI tools. When new data is found, it is securely queued in a local SQLite database and forwarded to your Anton server with exponential backoff and retry handling.
