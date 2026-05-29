#!/usr/bin/env bash
# Backend build script for Render.
set -euo pipefail

echo "=== Installing Python dependencies ==="
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "=== Installing Playwright Chromium ==="
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-0}"
python -m playwright install chromium

echo "=== Build complete ==="
