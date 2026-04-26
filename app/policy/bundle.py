"""Versioned policy bundle: single load point for thresholds, workflow, selectors, recovery, signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_POLICY_PATH = Path(__file__).resolve().parent / "default_policy.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _policy_fingerprint(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PolicyBundle:
    """Immutable resolved policy for a compile or runtime session."""

    version: str
    data: dict[str, Any]
    content_hash: str

    def section(self, *keys: str) -> Any:
        cur: Any = self.data
        for k in keys:
            if not isinstance(cur, dict):
                return {}
            cur = cur.get(k, {})
        return cur if isinstance(cur, dict) else {}

    def thresholds(self) -> dict[str, float]:
        t = self.section("confidence", "thresholds")
        return dict(t) if isinstance(t, dict) else {}

    def recovery_weights(self) -> dict[str, float]:
        w = self.section("confidence", "recovery_global_weights")
        return dict(w) if isinstance(w, dict) else {}

    def layer_scorers(self) -> dict[str, Any]:
        ls = self.section("confidence", "layer_scorers")
        return dict(ls) if isinstance(ls, dict) else {}

    def as_confidence_protocol_fragment(self) -> dict[str, Any]:
        unc = self.section("uncertainty")
        return {
            "layer_thresholds": self.thresholds(),
            "recovery_global_weights": self.recovery_weights(),
            "layer_scorers": self.layer_scorers(),
            "uncertainty_policy": {
                "candidate_ambiguity_margin": float(unc.get("candidate_ambiguity_margin", 0.03)),
                "min_anchors_warn": int(unc.get("min_anchors_warn", 1)),
                "failure_first": bool(unc.get("failure_first", True)),
                "assist_min_confidence": float(unc.get("assist_min_confidence", 0.75)),
                "recovery_candidate_budget": int(unc.get("recovery_candidate_budget", 5)),
            },
            "policy_version": self.version,
            "policy_hash": self.content_hash,
        }


def load_policy_bundle(path: Path | None = None, overrides: dict[str, Any] | None = None) -> PolicyBundle:
    p = path or _POLICY_PATH
    raw = json.loads(p.read_text(encoding="utf-8"))
    if overrides:
        raw = _deep_merge(raw, overrides)
    version = str(raw.get("version", "0.0.0"))
    h = _policy_fingerprint(raw)
    return PolicyBundle(version=version, data=raw, content_hash=h)


@lru_cache(maxsize=1)
def get_policy_bundle() -> PolicyBundle:
    """Process-wide default bundle (reload process to pick up JSON edits)."""

    return load_policy_bundle()


def get_default_policy_dict() -> dict[str, Any]:
    return dict(get_policy_bundle().data)
