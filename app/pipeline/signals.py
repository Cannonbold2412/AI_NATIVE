"""Apply signal relevance budgets from policy (post-capture, pre-compile)."""

from __future__ import annotations

from typing import Any

from app.policy.bundle import get_policy_bundle


def apply_signal_budget(ev: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    pol = policy or get_policy_bundle().data
    sec = pol.get("signals") if isinstance(pol.get("signals"), dict) else {}
    sib_max = int(sec.get("pipeline_siblings_max", 4))
    text_max = int(sec.get("build_inner_text_max", 240))
    norm_max = int(sec.get("semantic_normalized_max", 500))

    out = dict(ev)
    ctx = dict(out.get("context") or {})
    sibs = list(ctx.get("siblings") or [])[:sib_max]
    ctx["siblings"] = sibs
    out["context"] = ctx
    tgt = dict(out.get("target") or {})
    if tgt.get("inner_text") is not None:
        t = str(tgt.get("inner_text") or "")
        tgt["inner_text"] = t[:text_max]
    out["target"] = tgt
    sem = dict(out.get("semantic") or {})
    if sem.get("normalized_text") is not None:
        sem["normalized_text"] = str(sem.get("normalized_text") or "")[:norm_max]
    out["semantic"] = sem
    return out
