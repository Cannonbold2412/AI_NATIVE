#!/usr/bin/env bash
# Conxa Build Studio — macOS / Linux developer setup
# Run once after cloning: ./scripts/setup.sh
# Requires: Python 3.11+, Node.js 20+
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

step() { echo ""; echo "==> $1"; }

# ── 1. conxa-core (shared Python foundation) ──────────────────────────────────
step "Installing conxa-core (shared Python foundation)"
python3 -m pip install -e "$ROOT/packages/conxa-core" --quiet

# ── 2. Build Studio Python backend ────────────────────────────────────────────
step "Installing Build Studio Python dependencies"
python3 -m pip install -r "$ROOT/conxa-builder/python/requirements.txt" --quiet

# ── 3. Playwright Chromium ────────────────────────────────────────────────────
step "Installing Playwright Chromium browser"
python3 -m playwright install chromium

# ── 4. Electron / renderer (Node dependencies) ────────────────────────────────
step "Installing Electron dependencies"
(cd "$ROOT/conxa-builder/electron" && npm install --silent)

# ── 5. Runtime (Node dependencies) ────────────────────────────────────────────
step "Installing runtime dependencies"
(cd "$ROOT/runtime" && npm install --silent)

echo ""
echo "Setup complete."
echo ""
echo "To start the dev server:"
echo "  cd conxa-builder/electron && npm run dev"
echo ""
echo "To build the Studio installer:"
echo "  1. pyinstaller conxa-builder/pyinstaller.spec --noconfirm"
echo "  2. cd conxa-builder/electron && npm run build"
echo ""
echo "To build the runtime (requires NASM + VS Build Tools on Windows):"
echo "  cd runtime && npm run build:win   # or build:mac"
