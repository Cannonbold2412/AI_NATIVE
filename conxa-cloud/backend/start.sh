#!/usr/bin/env bash
# Backend start script for Render. The schema is created by init_db() on startup.
set -euo pipefail

echo "=== Starting API ==="
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
