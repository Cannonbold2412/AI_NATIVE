#!/usr/bin/env python3
"""Sync runtime template files into the conxa npm package source.

The source-of-truth for runtime/cli logic is
`app/storage/plugin_templates/runtime/`. This script mirrors it into
`packages/conxa-cli/lib/` so the npm package always ships the same
code that `conxa init` lays down into `~/.conxa/runtime/`.

Run before `npm publish`:
    python scripts/sync_conxa_cli.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "app" / "storage" / "plugin_templates" / "runtime"
DST = REPO_ROOT / "packages" / "conxa-cli" / "lib"


def _clean(dst: Path) -> None:
    if dst.exists():
        for item in dst.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    dst.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not SRC.is_dir():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1
    _clean(DST)
    # Copy every file the runtime tree currently ships, preserving structure.
    for entry in SRC.rglob("*"):
        rel = entry.relative_to(SRC)
        target = DST / rel
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, target)
    print(f"synced {SRC} → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
