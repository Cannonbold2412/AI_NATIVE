from __future__ import annotations

from pathlib import Path

from .common import Bundle, PhaseResult, load_json


def _check_entry(entry: dict, execution: list[dict], skill_rel: str) -> list[str]:
    sid = entry.get("step_id")
    tag = f"{skill_rel}/recovery.json[step_id={sid}]"
    issues: list[str] = []

    sel_ctx = entry.get("selector_context") or {}
    if not sel_ctx.get("primary"):
        issues.append(f"{tag}: L1 selector_context.primary empty")
    if not isinstance(sel_ctx.get("alternatives"), list):
        issues.append(f"{tag}: L1 selector_context.alternatives must be a list")

    anchors = entry.get("anchors") or []
    if not anchors:
        issues.append(f"{tag}: L2 anchors empty")
    for a in anchors:
        if "text" not in a or "priority" not in a:
            issues.append(f"{tag}: L2 anchor missing text/priority")

    fallback = entry.get("fallback") or {}
    text_variants = fallback.get("text_variants") or []
    if not text_variants:
        issues.append(f"{tag}: L3 fallback.text_variants empty")

    vmeta = entry.get("visual_metadata") or {}
    if not entry.get("visual_ref") or not vmeta.get("available"):
        issues.append(f"{tag}: L4 visual_ref/visual_metadata.available missing")

    target_text = (entry.get("target") or {}).get("text") or ""
    if target_text:
        anchor_texts = {a.get("text") for a in anchors}
        if target_text not in anchor_texts and target_text not in text_variants:
            issues.append(f"{tag}: target.text '{target_text}' not in anchors or text_variants")

    rmeta = entry.get("recovery_metadata") or {}
    if rmeta.get("mode") != "tiered":
        issues.append(f"{tag}: recovery_metadata.mode must be 'tiered'")

    if isinstance(sid, int) and 1 <= sid <= len(execution):
        exec_type = execution[sid - 1].get("type")
        if rmeta.get("action_type") != exec_type:
            issues.append(
                f"{tag}: action_type '{rmeta.get('action_type')}' != execution[{sid}].type '{exec_type}'"
            )

    return issues


def run(bundle: Bundle) -> PhaseResult:
    failures: list[str] = []
    total = 0
    passing = 0
    for skill_dir in bundle.skills:
        rel = skill_dir.name
        try:
            recovery = load_json(skill_dir / "recovery.json")
            execution = load_json(skill_dir / "execution.json")
        except Exception as e:
            failures.append(f"{rel}: failed to load recovery/execution: {e}")
            continue
        for entry in recovery.get("steps", []):
            total += 1
            entry_issues = _check_entry(entry, execution, rel)
            if not entry_issues:
                passing += 1
            failures.extend(entry_issues)

    score = round(10 * passing / total) if total else 0
    return PhaseResult(
        name="Phase 4 Recovery",
        passed=score >= 8,
        details=failures,
        score=score,
        extras={"passing": passing, "total": total},
    )
