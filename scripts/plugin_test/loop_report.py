from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _status_icon(status: str) -> str:
    return {"ok": "✅", "recovered": "⚠️", "failed": "❌"}.get(status, status)


def _step_table(steps: list[dict]) -> str:
    header = "| # | type | selector | status | latency | note |\n|---|------|----------|--------|---------|------|"
    rows = []
    for s in steps:
        note = ""
        if s.get("recovered_via"):
            note = f"via `{s['recovered_via']}`"
        elif s.get("error"):
            note = s["error"][:80]
        latency = f"{s.get('latency_ms', 0)}ms"
        sel = (s.get("selector") or "")[:60]
        rows.append(
            f"| {s['step']} | {s['type']} | `{sel}` "
            f"| {_status_icon(s['status'])} {s['status']} | {latency} | {note} |"
        )
    return header + "\n" + "\n".join(rows)


def _final_failures(iterations: list[dict]) -> str:
    last = iterations[-1] if iterations else {}
    failed_steps = [s for s in last.get("steps", []) if s.get("status") == "failed"]
    if not failed_steps:
        return ""
    lines = ["## Final Failures\n"]
    for s in failed_steps:
        lines.append(
            f"- step {s['step']} `{s['type']}` `{s.get('selector', '')}`: "
            f"{s.get('error', 'unknown error')}\n"
            f"  **Fix Instructions**: check if the selector/label has changed on the live page.\n"
            f"  **Codegen Instructions**: `app/services/skill_pack_builder.py:generate_recovery` — "
            f"add more selector alternatives for this step type."
        )
    return "\n".join(lines)


def write(bundle_root: Path, skill_name: str, iterations: list[dict], sandbox_ack: bool) -> Path:
    out = bundle_root / "EXECUTION_LOOP.md"
    now = datetime.now().isoformat(timespec="seconds")

    last = iterations[-1] if iterations else {}
    overall_passed = last.get("passed", False)
    total_iters = len(iterations)

    if overall_passed:
        result_line = f"**PASS** after iteration {total_iters}"
    else:
        result_line = f"**FAIL** after {total_iters} iteration(s)"

    lines = [
        f"# Execution Loop Report — {bundle_root.name} / {skill_name}",
        f"Generated: {now}",
        f"Sandbox: {'CONXA_SANDBOX_ACK=1 (acknowledged)' if sandbox_ack else 'NOT SET'}",
        "",
        "## Result",
        result_line,
        "",
        "## Iterations",
    ]

    for idx, it in enumerate(iterations, start=1):
        summary = it.get("summary", {})
        ok = summary.get("ok", 0)
        recovered = summary.get("recovered", 0)
        failed = summary.get("failed", 0)
        total = summary.get("total", 0)
        lines.append(
            f"\n### Iteration {idx} — {ok}/{total} ok, {recovered} recovered, {failed} failed"
        )
        lines.append(_step_table(it.get("steps", [])))

        fixes = it.get("fixes_applied", [])
        if fixes:
            lines.append("\n**Auto-fixes applied for next iteration:**")
            for fix in fixes:
                lines.append(f"- {fix}")

    final_fail_section = _final_failures(iterations)
    if final_fail_section:
        lines.append("")
        lines.append(final_fail_section)

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
