#!/usr/bin/env bash
# Backend start script for Render.
set -euo pipefail

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-0}"

echo "=== Ensuring Playwright Chromium is installed ==="
python -m playwright install chromium

echo "=== Starting API ==="
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
