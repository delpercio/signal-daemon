#!/usr/bin/env bash

set -e

echo "========================================"
echo " Signal Daemon Installer"
echo "========================================"
echo ""

# Ensure Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found in PATH."
    exit 1
fi

INSTALL_DIR="$HOME/.signal-daemon"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"

echo "1. Creating installation directory at $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

echo "2. Setting up isolated Python virtual environment..."
python3 -m venv "$VENV_DIR"

echo "3. Installing signal-daemon..."
# Install from the current directory
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install . --quiet

echo "4. Creating symlink in $BIN_DIR..."
ln -sf "$VENV_DIR/bin/signal-daemon" "$BIN_DIR/signal-daemon"

echo ""
echo "========================================"
echo " Installation Complete!"
echo "========================================"
echo ""

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "⚠ Note: $BIN_DIR is not in your PATH."
    echo "  You may want to add it to your ~/.zshrc or ~/.bash_profile:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo "Starting the setup wizard..."
echo ""
# Run the setup wizard
"$VENV_DIR/bin/signal-daemon" setup
