"""Compiler stub until Phase 3 implements rule-based intent + recovery blocks."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.skill_spec import SkillBlock, SkillMeta, SkillPackage, SkillPolicies


def not_implemented_package(skill_id: str) -> SkillPackage:
    """Deterministic placeholder package (explicitly empty steps)."""
    now = datetime.now(timezone.utc).isoformat()
    return SkillPackage(
        meta=SkillMeta(id=skill_id, version=0, title="not-compiled", created_at=now),
        inputs=[],
        skills=[SkillBlock(name="recorded", steps=[])],
        policies=SkillPolicies(),
    )
