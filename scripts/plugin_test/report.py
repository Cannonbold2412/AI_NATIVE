from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .common import Bundle, PhaseResult


def _fmt_phase(r: PhaseResult) -> str:
    icon = "PASS" if r.passed else "FAIL"
    line = f"- **{r.name}**: {icon}"
    if r.score is not None:
        line += f" — score {r.score}/10"
    if r.extras.get("total") is not None and r.score is None:
        line += f" — {r.extras.get('passing', r.extras.get('resolved', 0))}/{r.extras['total']}"
    if r.name == "Phase 5 Execution" and not r.extras.get("skipped"):
        line += f" ({r.extras.get('mode')}, recoveries used: {r.extras.get('recoveries_used', 0)})"
    return line


def _fix_instructions(results: list[PhaseResult], bundle: Bundle) -> list[str]:
    out: list[str] = []
    for r in results:
        if r.passed:
            continue
        for d in r.details:
            if "missing field" in d or "must be" in d or "empty" in d or "missing on disk" in d:
                out.append(f"- Edit `{bundle.root.name}/...`: {d}")
            elif "not declared" in d:
                out.append(f"- Add the variable to `input.json` or remove its reference: {d}")
            elif "overly generic" in d:
                out.append(f"- Re-record this step with a more specific selector (text= or [name=]): {d}")
            elif "missing skill file" in d or "missing bundle file" in d:
                out.append(f"- Re-run the package builder; bundle is incomplete: {d}")
    return out


def _codegen_instructions(results: list[PhaseResult]) -> list[str]:
    out: list[str] = []
    for r in results:
        if r.passed:
            continue
        for d in r.details:
            if "L2 anchors empty" in d or "L3 fallback.text_variants empty" in d:
                out.append(
                    f"- `app/services/skill_pack_builder.py::generate_recovery` (~line 1329): "
                    f"ensure anchors and text_variants always include `target.text` as a fallback. ({d})"
                )
            elif "L1 selector_context.primary empty" in d:
                out.append(
                    "- `generate_recovery`: refuse to emit a recovery entry when the source step has no selector. "
                    f"({d})"
                )
            elif "action_type" in d and "!=" in d:
                out.append(
                    f"- `generate_recovery`: action_type drift between recovery and execution. ({d})"
                )
            elif "overly generic" in d:
                out.append(
                    f"- `compiler/action_semantics.py`: tighten selector scoring to reject generic shapes earlier. ({d})"
                )
    return out


def write(bundle: Bundle, results: list[PhaseResult]) -> Path:
    overall_pass = all(r.passed for r in results)
    lines = [
        f"# Plugin Test Report — {bundle.name}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        *[_fmt_phase(r) for r in results],
        "",
    ]

    if overall_pass:
        lines += ["## Result", "", "Ready to publish."]
    else:
        lines += ["## Failures", ""]
        for r in results:
            if r.passed or not r.details:
                continue
            lines.append(f"### {r.name}")
            for d in r.details:
                lines.append(f"- {d}")
            lines.append("")

        fixes = _fix_instructions(results, bundle)
        codegen = _codegen_instructions(results)
        lines += ["## Fix Instructions (apply to /output/skill_package/" + bundle.name + "/)", ""]
        lines += fixes or ["- (no auto-suggestions; see Failures section)"]
        lines += ["", "## Codegen Instructions (apply to app/services/skill_pack_builder.py)", ""]
        lines += codegen or ["- (no codegen suggestions; failure is bundle-local)"]

    target = bundle.root / "TEST_REPORT.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
