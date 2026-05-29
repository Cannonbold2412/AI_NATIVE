"""Plugin testing workflow.

Usage:
  python scripts/test_plugin.py <plugin-name> [--prepare | --finalize | --skip-phase2]
                                              [--skip-phase5] [--execute --inputs path]
  python scripts/test_plugin.py <plugin-name> --loop --inputs path/to/inputs.json [--max-iters 5] [--no-autofix]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.plugin_test import (  # noqa: E402
    phase1_structure,
    phase2_claude,
    phase3_steps,
    phase4_recovery,
    phase5_execution,
    report,
)
from scripts.plugin_test.common import find_bundle  # noqa: E402
from scripts.plugin_test.loop_runner import run as loop_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin_name")
    parser.add_argument("--prepare", action="store_true", help="Run det. phases + emit Phase 2 brief; do not write final report")
    parser.add_argument("--finalize", action="store_true", help="Read PHASE2_RESULT.json and write final report")
    parser.add_argument("--skip-phase2", action="store_true")
    parser.add_argument("--skip-phase5", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Phase 5 full-run (otherwise dry-run)")
    parser.add_argument("--inputs", type=Path, help="JSON file with values for {{var}} interpolation")
    parser.add_argument("--loop", action="store_true", help="Full execution loop: run → fix → re-run until perfect")
    parser.add_argument("--max-iters", type=int, default=5, help="Max iterations for --loop (default 5)")
    parser.add_argument("--no-autofix", action="store_true", help="Disable auto-fix of execution.json/recovery.json between loop iterations")
    args = parser.parse_args()

    bundle = find_bundle(args.plugin_name, PROJECT_ROOT)

    # --loop mode: full execution loop, skips phases 2 and 5
    if args.loop:
        if not args.inputs:
            print("error: --loop requires --inputs <path/to/inputs.json>", file=sys.stderr)
            return 1
        loop_result = loop_run(
            bundle,
            inputs_path=args.inputs,
            max_iters=args.max_iters,
            autofix=not args.no_autofix,
        )
        score_suffix = f" (score {loop_result.score}/10)" if loop_result.score is not None else ""
        print(f"  {loop_result.name}: {'PASS' if loop_result.passed else 'FAIL'}{score_suffix}")
        if loop_result.extras.get("report"):
            print(f"  Report: {loop_result.extras['report']}")
        return 0 if loop_result.passed else 1

    results = [
        phase1_structure.run(bundle),
        phase3_steps.run(bundle),
        phase4_recovery.run(bundle),
    ]

    if args.prepare:
        brief = phase2_claude.write_brief(bundle)
        print(f"Phase 2 brief written: {brief}")
        print(f"Have Claude read it and write {bundle.root / phase2_claude.RESULT_FILENAME}, then run --finalize.")
        for r in results:
            print(f"  {r.name}: {'PASS' if r.passed else 'FAIL'}")
        return 0

    if not args.skip_phase2:
        results.insert(1, phase2_claude.run(bundle))

    if args.execute or (args.inputs and not args.skip_phase5):
        results.append(phase5_execution.run(bundle, execute=args.execute, inputs_path=args.inputs))

    target = report.write(bundle, results)
    print(f"Report: {target}")
    for r in results:
        suffix = ""
        if r.score is not None:
            suffix = f" (score {r.score}/10)"
        print(f"  {r.name}: {'PASS' if r.passed else 'FAIL'}{suffix}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
