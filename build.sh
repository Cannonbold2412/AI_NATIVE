#!/usr/bin/env bash
# Backend build script for Render.
set -euo pipefail

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Playwright Chromium ==="
playwright install --with-deps chromium

echo "=== Build complete ==="
