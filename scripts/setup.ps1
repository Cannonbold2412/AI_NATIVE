# Conxa Build Studio — Windows developer setup
# Run once after cloning: .\scripts\setup.ps1
# Requires: Python 3.11+, Node.js 20+
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

# ── 1. conxa-core (shared Python foundation) ──────────────────────────────────
Step "Installing conxa-core (shared Python foundation)"
python -m pip install -e "$Root\packages\conxa-core" --quiet

# ── 2. Build Studio Python backend ────────────────────────────────────────────
Step "Installing Build Studio Python dependencies"
python -m pip install -r "$Root\conxa-builder\python\requirements.txt" --quiet

# ── 3. Playwright Chromium ────────────────────────────────────────────────────
Step "Installing Playwright Chromium browser"
python -m playwright install chromium

# ── 4. Electron / renderer (Node dependencies) ────────────────────────────────
Step "Installing Electron dependencies"
Push-Location "$Root\conxa-builder\electron"
npm install --silent
Pop-Location

# ── 5. Runtime (Node dependencies) ────────────────────────────────────────────
Step "Installing runtime dependencies"
Push-Location "$Root\runtime"
npm install --silent
Pop-Location

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "To start the dev server:"
Write-Host "  cd conxa-builder\electron"
Write-Host "  npm run dev"
Write-Host ""
Write-Host "To build the Studio installer:"
Write-Host "  1. pyinstaller conxa-builder\pyinstaller.spec --noconfirm"
Write-Host "  2. cd conxa-builder\electron && npm run build"
Write-Host ""
Write-Host "To build the runtime (requires NASM + VS Build Tools):"
Write-Host "  cd runtime && npm run build:win"
