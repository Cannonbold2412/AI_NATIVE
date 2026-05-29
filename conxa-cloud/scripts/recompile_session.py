"""Recompile a recorded session and dump the compile report.

Usage: python scripts/recompile_session.py <session_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/recompile_session.py <session_id>")
        return 1

    session_id = sys.argv[1]

    from conxa_compile.compiler.build import compile_skill_package
    from conxa_core.config import settings
    from conxa_compile.pipeline.run import run_pipeline

    session_dir = settings.data_dir / "sessions" / session_id
    events_path = session_dir / "events.jsonl"
    if not events_path.is_file():
        print(f"events.jsonl not found at {events_path}")
        return 1

    raw_events: list[dict] = []
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw_events.append(json.loads(line))

    print(f"Loaded {len(raw_events)} events from {session_id}")

    try:
        normalized = run_pipeline(raw_events)
    except Exception as exc:
        print(f"Pipeline normalization failed: {exc}")
        return 1

    print(f"Pipeline produced {len(normalized)} normalized events")

    try:
        package = compile_skill_package(
            normalized,
            skill_id=f"skill_{session_id}",
            source_session_id=session_id,
            title=f"Recompiled {session_id[:8]}",
            version=1,
        )
    except Exception as exc:
        print(f"Compile failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    steps = package.skills[0].steps
    print(f"\nCompile produced {len(steps)} steps\n")

    # Print per-step summary
    for i, step in enumerate(steps):
        target = step.target or {}
        sel = target.get("primary_selector") or ""
        conf = target.get("selector_confidence") or 0.0
        source = target.get("selector_source") or "heuristic"
        action = step.action if isinstance(step.action, str) else step.action.get("action", "")
        binding = step.input_binding or "-"
        value_str = str(step.value)[:30] if step.value is not None else "-"
        print(f"  [{i:2d}] {action:<20} sel='{sel[:60]:<60}' conf={conf:.2f} src={source:<10} binding={binding:<25} value={value_str}")

    # Print compile report summary
    report = package.compile_report
    if report:
        print(f"\nCompile report:")
        print(f"  status: {report.get('status')}")
        print(f"  min_confidence: {report.get('min_confidence')}")
        print(f"  steps_total: {report.get('steps_total')}")
        print(f"  steps_with_warnings: {report.get('steps_with_warnings')}")
        router_stats = report.get("llm_router_stats", {})
        if router_stats:
            print(f"  llm_router: pool_size={router_stats.get('pool_size')}")
            for entry in router_stats.get("entries") or []:
                print(f"    {entry['provider']}: sent={entry['requests_sent']} 429={entry['requests_429']} cooled={entry['cooled']}")
        else:
            print(f"  llm_router: not active (no providers configured)")

    # Save full report to disk for inspection
    out_path = session_dir / "compile_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report written to {out_path}")

    # Save the package too
    pkg_path = session_dir / "compiled_package.json"
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(package.model_dump(mode="json"), f, indent=2)
    print(f"Full package written to {pkg_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
