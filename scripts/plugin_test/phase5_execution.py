from __future__ import annotations

import time
from pathlib import Path

from .common import Bundle, PhaseResult, load_json


def _try_locator(page, selector: str, timeout_ms: int = 5000) -> tuple[bool, str | None]:
    try:
        page.locator(selector).first.wait_for(timeout=timeout_ms)
        return True, None
    except Exception as e:
        return False, str(e).splitlines()[0][:200]


def _recover(page, recovery_entry: dict | None) -> str | None:
    if not recovery_entry:
        return None
    sel_ctx = recovery_entry.get("selector_context") or {}
    for alt in sel_ctx.get("alternatives") or []:
        ok, _ = _try_locator(page, alt, timeout_ms=2000)
        if ok:
            return alt
    for variant in (recovery_entry.get("fallback") or {}).get("text_variants") or []:
        sel = f"text={variant}"
        ok, _ = _try_locator(page, sel, timeout_ms=2000)
        if ok:
            return sel
    return None


def _interpolate(value, inputs: dict) -> str:
    import re
    if not isinstance(value, str):
        return value
    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", lambda m: str(inputs.get(m.group(1).strip(), "")), value)


def _run_skill(page, skill_dir: Path, execute: bool, inputs: dict) -> tuple[list[dict], int]:
    execution = load_json(skill_dir / "execution.json")
    recovery = load_json(skill_dir / "recovery.json")
    recovery_by_id = {e.get("step_id"): e for e in recovery.get("steps", [])}

    rows: list[dict] = []
    recoveries = 0

    for idx, step in enumerate(execution, start=1):
        stype = step.get("type")
        sel = _interpolate(step.get("selector", ""), inputs)
        start = time.time()
        row = {"step": idx, "type": stype, "selector": sel}

        if stype == "navigate":
            url = _interpolate(step.get("url", ""), inputs)
            try:
                page.goto(url, timeout=15000)
                row["status"] = "resolved"
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e).splitlines()[0][:200]
        elif stype == "scroll":
            try:
                page.evaluate(f"window.scrollBy(0, {step.get('delta_y', 0)})")
                row["status"] = "resolved"
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e).splitlines()[0][:200]
        elif stype in {"click", "fill", "assert_visible"}:
            ok, err = _try_locator(page, sel)
            if not ok:
                alt = _recover(page, recovery_by_id.get(idx))
                if alt:
                    sel = alt
                    ok = True
                    recoveries += 1
                    row["recovered_via"] = alt
            if not ok:
                row["status"] = "missing"
                row["error"] = err
            elif execute:
                try:
                    if stype == "click":
                        page.locator(sel).first.click(timeout=5000)
                    elif stype == "fill":
                        page.locator(sel).first.fill(_interpolate(step.get("value", ""), inputs), timeout=5000)
                    row["status"] = "resolved"
                except Exception as e:
                    row["status"] = "error"
                    row["error"] = str(e).splitlines()[0][:200]
            else:
                row["status"] = "resolved"
        else:
            row["status"] = "error"
            row["error"] = f"unknown step type '{stype}'"

        row["latency_ms"] = int((time.time() - start) * 1000)
        rows.append(row)

    return rows, recoveries


def run(bundle: Bundle, execute: bool = False, inputs_path: Path | None = None) -> PhaseResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return PhaseResult(
            name="Phase 5 Execution",
            passed=False,
            details=["playwright not installed — skip with --skip-phase5 or install playwright"],
            extras={"skipped": True},
        )

    inputs: dict = {}
    if inputs_path and inputs_path.exists():
        inputs = load_json(inputs_path)

    all_rows: list[dict] = []
    total_recoveries = 0
    failures: list[str] = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            return PhaseResult(
                name="Phase 5 Execution",
                passed=False,
                details=[f"chromium launch failed (run `playwright install chromium`): {e}"],
                extras={"skipped": True},
            )
        context = browser.new_context()
        page = context.new_page()

        for skill_dir in bundle.skills:
            execution = load_json(skill_dir / "execution.json")
            first_nav = next((s for s in execution if s.get("type") == "navigate"), None)
            if first_nav:
                first_url = _interpolate(first_nav.get("url", ""), inputs)
            else:
                first_url = inputs.get("__entry_url__") or "about:blank"

            if first_url and first_url != "about:blank":
                try:
                    page.goto(first_url, timeout=15000)
                except Exception as e:
                    failures.append(f"{skill_dir.name}: cannot navigate to '{first_url}': {str(e).splitlines()[0][:200]}")
                    continue
            else:
                try:
                    page.goto("about:blank", timeout=5000)
                except Exception:
                    pass

            rows, recoveries = _run_skill(page, skill_dir, execute, inputs)
            for r in rows:
                r["skill"] = skill_dir.name
                all_rows.append(r)
            total_recoveries += recoveries

        try:
            browser.close()
        except Exception:
            pass

    total = len(all_rows)
    resolved = sum(1 for r in all_rows if r.get("status") == "resolved")
    threshold = 1.0 if execute else 0.9
    passed = total > 0 and (resolved / total) >= threshold

    for r in all_rows:
        if r.get("status") != "resolved":
            failures.append(
                f"{r['skill']}/execution.json[step-{r['step']}] {r['type']}: {r.get('status')} — {r.get('error', '')}"
            )

    return PhaseResult(
        name="Phase 5 Execution",
        passed=passed,
        details=failures,
        extras={
            "mode": "full-run" if execute else "dry-run",
            "resolved": resolved,
            "total": total,
            "recoveries_used": total_recoveries,
            "rows": all_rows,
        },
    )
