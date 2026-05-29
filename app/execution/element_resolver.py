"""Tiered element resolution metrics + LLM recovery (Phase 4).

The actual element lookup happens in the JS runtime (runtime/run.js) because that's
where Playwright is running. This module provides:

1. The recovery LLM call that the runtime invokes via HTTP when Tier 1+2 both fail.
2. Tier-usage metrics so the dashboard can track Tier 1 / 2 / 3 / 4 distribution.
3. The "promote selector after 5 wins" self-healing helper.

Hard rules from the architecture contract:
- Normal execution = 100% deterministic (Tier 1 + Tier 2 only).
- Tier 3 + 4 fire ONLY as recovery — every invocation is a signal that the
  compile phase may need to recompile.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from app.config import settings
from app.llm.openapi_client import resolve_element_recovery


# ─── Tier definitions ─────────────────────────────────────────────────────────

TIER_COMPILED = "tier1_compiled"      # try step.compiled_selectors (deterministic)
TIER_A11Y = "tier2_a11y"               # query a11y tree by role + name (deterministic)
TIER_LLM_RECOVERY = "tier3_llm"        # LLM resolves against current DOM (recovery)
TIER_VISION = "tier4_vision"           # vision model locates by screenshot (last resort)
TIER_FAIL = "tier_fail"                # all tiers failed → human escalation
ALL_TIERS = (TIER_COMPILED, TIER_A11Y, TIER_LLM_RECOVERY, TIER_VISION, TIER_FAIL)


# ─── Tier metrics ─────────────────────────────────────────────────────────────

@dataclass
class TierMetrics:
    """Per-tier resolution counters. Persisted in memory; surfaced via /admin/metrics."""

    counts: dict[str, int] = field(default_factory=lambda: {t: 0 for t in ALL_TIERS})
    _lock: Lock = field(default_factory=Lock)

    def record(self, tier: str) -> None:
        if tier not in self.counts:
            return
        with self._lock:
            self.counts[tier] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self.counts)
        total = sum(counts.values()) or 1
        return {
            "counts": counts,
            "distribution": {k: round(v / total, 4) for k, v in counts.items()},
            "total": sum(counts.values()),
            "recovery_rate": round((counts[TIER_LLM_RECOVERY] + counts[TIER_VISION]) / total, 4),
        }


tier_metrics = TierMetrics()


# ─── LLM recovery (Tier 3) ────────────────────────────────────────────────────

def llm_resolve_recovery(
    *,
    semantic_description: str,
    original_bbox: dict[str, int] | None,
    original_ancestors: list[dict[str, Any]] | None,
    current_dom_snippet: str,
    action_type: str,
) -> dict[str, Any] | None:
    """Tier 3: ask the LLM for a Playwright selector against the current DOM.

    Caller (runtime/run.js via HTTP) is responsible for validating that the
    returned selector resolves to exactly one element. Returns None on LLM failure.
    """
    return resolve_element_recovery(
        semantic_description=semantic_description,
        original_bbox=original_bbox,
        original_ancestors=original_ancestors,
        current_dom_snippet=current_dom_snippet,
        action_type=action_type,
    )


# ─── Self-healing promotion ───────────────────────────────────────────────────

@dataclass
class _PromotionState:
    """Tracks how many consecutive successes a recovery-discovered selector has.

    Per the user decision: auto-promote to step.compiled_selectors after 5 wins.
    State is persisted to DB with in-memory cache for speed.
    """

    # In-memory cache: (skill_id, step_index, selector) → {count, last_seen}
    _cache: dict[tuple[str, int, str], dict[str, Any]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def _db_key(self, skill_id: str, step_index: int, selector: str) -> str:
        return f"{skill_id}:{step_index}:{selector}"

    def record_success(self, skill_id: str, step_index: int, selector: str) -> bool:
        """Increment the win counter. Returns True iff selector should now be promoted."""
        from app.db import db_get, db_set  # noqa: PLC0415
        key = (skill_id, int(step_index), selector)
        db_key = self._db_key(skill_id, step_index, selector)
        with self._lock:
            entry = db_get("selector_promotion", db_key) or self._cache.get(key) or {}
            n = int(entry.get("count", 0)) + 1
            entry["count"] = n
            entry["last_seen"] = time.time()
            self._cache[key] = entry
            db_set("selector_promotion", db_key, entry)
            return n >= 5

    def reset(self, skill_id: str, step_index: int, selector: str) -> None:
        """Selector failed → reset counter (don't promote a flaky selector)."""
        from app.db import db_delete  # noqa: PLC0415
        key = (skill_id, int(step_index), selector)
        db_key = self._db_key(skill_id, step_index, selector)
        with self._lock:
            self._cache.pop(key, None)
            db_delete("selector_promotion", db_key)

    def snapshot(self) -> dict[str, Any]:
        from app.db import db_list_kv  # noqa: PLC0415
        with self._lock:
            all_entries = db_list_kv("selector_promotion")
            candidates = []
            for db_key, entry in all_entries:
                if isinstance(entry, dict) and entry.get("count", 0) >= 3:
                    parts = db_key.split(":", 2)
                    if len(parts) == 3:
                        candidates.append({
                            "skill_id": parts[0],
                            "step_index": int(parts[1]) if parts[1].isdigit() else 0,
                            "selector": parts[2],
                            "wins": int(entry.get("count", 0)),
                        })
            return {
                "tracked_selectors": len(all_entries),
                "promotion_candidates": candidates,
            }


promotion_state = _PromotionState()


def promote_selector_to_step(skill_id: str, step_index: int, selector: str) -> bool:
    """Persist a recovery-discovered selector to step.compiled_selectors.

    Reads the skill package, prepends the new selector if it's not already there,
    and writes back. Returns True on successful persistence.
    """
    from app.storage import read_skill, write_skill  # noqa: PLC0415
    doc = read_skill(skill_id)
    if not isinstance(doc, dict):
        return False
    skills = doc.get("skills") or []
    if not isinstance(skills, list) or not skills:
        return False
    block = skills[0]
    steps = block.get("steps") if isinstance(block, dict) else None
    if not isinstance(steps, list) or step_index < 0 or step_index >= len(steps):
        return False
    step = steps[step_index]
    if not isinstance(step, dict):
        return False
    existing = list(step.get("compiled_selectors") or [])
    if selector in existing:
        return True  # already present
    # Prepend the promoted selector and cap at 5 entries.
    step["compiled_selectors"] = [selector, *existing][:5]
    write_skill(skill_id, doc)
    return True


# ─── Escalation (Tier 4 also failed) ──────────────────────────────────────────

@dataclass
class _EscalationQueue:
    """Failures after all 4 tiers → human review queue.

    Per the user decision: pause workflow, log full diagnostic context, no silent
    failures or guessing. State is kept in memory with DB write-through.
    """

    _items: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def add(self, *, skill_id: str, step_index: int, context: dict[str, Any]) -> None:
        from app.db import db_append  # noqa: PLC0415
        item = {
            "skill_id": skill_id,
            "step_index": int(step_index),
            "created_at": time.time(),
            "context": context,
        }
        with self._lock:
            self._items.append(item)
            db_append("human_escalation", "pending", [item])

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)


escalation_queue = _EscalationQueue()


def escalate_step_failure(
    *,
    skill_id: str,
    step_index: int,
    step: dict[str, Any] | None,
    error_summary: str,
    tier_attempts: list[dict[str, Any]],
) -> None:
    """Called from runtime when Tier 1+2+3+4 all fail. Logs diagnostic context."""
    tier_metrics.record(TIER_FAIL)
    escalation_queue.add(
        skill_id=skill_id,
        step_index=step_index,
        context={
            "step": step or {},
            "error_summary": error_summary,
            "tier_attempts": tier_attempts,
            "compile_required": True,
        },
    )
