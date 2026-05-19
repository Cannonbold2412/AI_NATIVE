#!/usr/bin/env bash
# Backend build script for Render.
set -euo pipefail

echo "=== Installing NSIS ==="
sudo apt-get update -qq
sudo apt-get install -y nsis

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Playwright Chromium ==="
playwright install --with-deps chromium

echo "=== Build complete ==="
