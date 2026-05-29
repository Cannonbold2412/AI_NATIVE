from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .common import Bundle, PhaseResult, dump_json, load_json
from .loop_report import write as _write_report


def _ensure_node_deps(bundle_root: Path) -> str | None:
    playwright_dir = bundle_root / "node_modules" / "playwright"
    if playwright_dir.is_dir():
        return None
    pkg = bundle_root / "package.json"
    if not pkg.exists():
        return "package.json missing from bundle root — cannot install node deps"
    try:
        subprocess.run(
            "npm install",
            cwd=bundle_root,
            shell=True,
            timeout=120,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            "npx playwright install chromium",
            cwd=bundle_root,
            shell=True,
            timeout=180,
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return "npm not found — install Node.js to run the execution loop"
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b"").decode(errors="replace")[-400:]
        return f"npm install failed: {tail}"
    except subprocess.TimeoutExpired:
        return "npm install timed out"
    return None


def _run_executor(bundle_root: Path, skill_name: str, inputs_path: Path, result_path: Path) -> tuple[int, str]:
    executor = bundle_root / "execution" / "executor.js"
    if not executor.exists():
        return 1, "execution/executor.js not found"
    cmd = (
        f'node "{executor}" --skill {skill_name} '
        f'--inputs "{inputs_path}" --result "{result_path}" --headless 1'
    )
    try:
        proc = subprocess.run(cmd, cwd=bundle_root, shell=True, timeout=300, capture_output=True)
        output = proc.stdout.decode(errors="replace") + proc.stderr.decode(errors="replace")
        return proc.returncode, output
    except FileNotFoundError:
        return 1, "node not found — install Node.js"
    except subprocess.TimeoutExpired:
        return 1, "executor timed out after 300s"


def _apply_autofix(
    skill_dir: Path,
    step_rows: list[dict],
) -> list[str]:
    fixes: list[str] = []
    exec_path = skill_dir / "execution.json"
    recovery_path = skill_dir / "recovery.json"
    if not exec_path.exists() or not recovery_path.exists():
        return fixes

    execution: list[dict] = load_json(exec_path)
    recovery_data: dict = load_json(recovery_path)
    recovery_steps: list[dict] = recovery_data.get("steps", [])
    recovery_by_id: dict[int, dict] = {
        int(e.get("step_id", 0)): e for e in recovery_steps if e.get("step_id")
    }

    exec_dirty = False
    rec_dirty = False

    for row in step_rows:
        idx = int(row.get("step", 0))
        if idx < 1 or idx > len(execution):
            continue

        step = execution[idx - 1]
        rec_entry = recovery_by_id.get(idx)

        if row.get("status") == "recovered" and row.get("recovered_via"):
            new_sel = row["recovered_via"]
            old_sel = step.get("selector", "")
            if old_sel != new_sel:
                step["selector"] = new_sel
                exec_dirty = True
                fixes.append(
                    f"execution.json[{idx}].selector: promoted `{new_sel}` (was `{old_sel}`)"
                )
                if rec_entry:
                    alts: list[str] = rec_entry.setdefault("selector_context", {}).setdefault("alternatives", [])
                    if old_sel and old_sel not in alts:
                        alts.append(old_sel)
                        rec_dirty = True
                        fixes.append(
                            f"recovery.json.steps[step_id={idx}].selector_context.alternatives: appended `{old_sel}`"
                        )

        elif row.get("status") == "failed" and rec_entry:
            error_text = row.get("error", "").lower()
            anchors = rec_entry.get("anchors", [])
            fallback = rec_entry.setdefault("fallback", {})
            variants: list[str] = fallback.setdefault("text_variants", [])
            for anchor in anchors:
                text = (anchor.get("text") or "").strip()
                if text and text.lower() in error_text and text not in variants:
                    variants.insert(0, text)
                    rec_dirty = True
                    fixes.append(
                        f"recovery.json.steps[step_id={idx}].fallback.text_variants: promoted `{text}` to head"
                    )

    if exec_dirty:
        dump_json(exec_path, execution)
    if rec_dirty:
        dump_json(recovery_path, recovery_data)

    return fixes


def run(
    bundle: Bundle,
    inputs_path: Path,
    max_iters: int = 5,
    autofix: bool = True,
) -> PhaseResult:
    inputs_path = inputs_path.resolve()
    sandbox_ack = os.environ.get("CONXA_SANDBOX_ACK") == "1"
    if not sandbox_ack:
        return PhaseResult(
            name="Execution Loop",
            passed=False,
            details=[
                "Refusing destructive run — set CONXA_SANDBOX_ACK=1 after confirming "
                "inputs.json targets a sandbox account with a disposable database."
            ],
        )

    if not inputs_path.exists():
        return PhaseResult(
            name="Execution Loop",
            passed=False,
            details=[f"inputs file not found: {inputs_path}"],
        )

    # Determine the skill to run (first skill dir in bundle)
    skills = bundle.skills
    if not skills:
        return PhaseResult(
            name="Execution Loop",
            passed=False,
            details=["no skill directories found under skills/"],
        )
    skill_dir = skills[0]
    skill_name = skill_dir.name

    # Install Node deps once
    dep_err = _ensure_node_deps(bundle.root)
    if dep_err:
        return PhaseResult(
            name="Execution Loop",
            passed=False,
            details=[dep_err],
        )

    result_path = bundle.root / "EXECUTION_RESULT.json"
    iterations: list[dict] = []
    final_passed = False

    for iteration in range(1, max_iters + 1):
        print(f"[loop] iteration {iteration}/{max_iters} ...", flush=True)
        _rc, output = _run_executor(bundle.root, skill_name, inputs_path, result_path)
        sys.stdout.buffer.write(output.encode(errors="replace"))
        sys.stdout.buffer.flush()

        if not result_path.exists():
            iterations.append({
                "passed": False,
                "steps": [],
                "summary": {},
                "fixes_applied": [],
                "executor_crash": output[-600:],
            })
            _write_report(bundle.root, skill_name, iterations, sandbox_ack)
            break

        try:
            result: dict[str, Any] = load_json(result_path)
        except Exception as exc:
            iterations.append({
                "passed": False,
                "steps": [],
                "summary": {},
                "fixes_applied": [],
                "executor_crash": str(exc),
            })
            _write_report(bundle.root, skill_name, iterations, sandbox_ack)
            break

        steps = result.get("steps", [])
        fixes: list[str] = []
        if autofix:
            fixes = _apply_autofix(skill_dir, steps)

        iterations.append({
            "passed": result.get("passed", False),
            "steps": steps,
            "summary": result.get("summary", {}),
            "fixes_applied": fixes,
        })

        _write_report(bundle.root, skill_name, iterations, sandbox_ack)

        if result.get("passed"):
            final_passed = True
            break

    report_path = _write_report(bundle.root, skill_name, iterations, sandbox_ack)
    print(f"[loop] report: {report_path}", flush=True)

    last = iterations[-1] if iterations else {}
    summary = last.get("summary", {})
    failed_steps = [s for s in last.get("steps", []) if s.get("status") == "failed"]
    details = [
        f"step {s['step']} {s['type']} `{s.get('selector', '')}`: {s.get('error', '')}"
        for s in failed_steps
    ]

    return PhaseResult(
        name="Execution Loop",
        passed=final_passed,
        details=details,
        score=10 if final_passed else max(
            0,
            round(10 * (summary.get("ok", 0) + summary.get("recovered", 0))
                  / max(summary.get("total", 1), 1))
        ),
        extras={
            "iterations": len(iterations),
            "final_summary": summary,
            "report": str(report_path),
        },
    )
