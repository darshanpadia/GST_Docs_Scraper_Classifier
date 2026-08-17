#!/usr/bin/env bash
# One-shot local setup for macOS/Linux/WSL: creates a venv, installs the
# project (including dev deps for running tests), and prints next steps.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,llm]"

echo ""
echo "Setup complete."
echo "NOTE: this script ran in its own subshell, so the venv is NOT active"
echo "in YOUR terminal yet, even though setup just finished. Activate it now:"
echo ""
echo "    source .venv/bin/activate"
echo ""
echo "Then (and in any new terminal session -- activation doesn't persist):"
echo "    gst-agent --once"
echo "    gst-agent --stats"
echo ""
echo "Note: OCR needs the Tesseract system binary installed separately --"
echo "see README.md 'OCR setup' if you plan to process scanned PDFs."
