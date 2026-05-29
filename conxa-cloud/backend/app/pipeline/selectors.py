"""Selector canonicalization and normalization (deterministic)."""

from __future__ import annotations

import hashlib
from typing import Any

from app.policy.bundle import get_policy_bundle


def normalize_selector_string(value: str) -> str:
    return " ".join((value or "").split())


def normalize_selectors_block(selectors: dict[str, str]) -> dict[str, str]:
    return {k: normalize_selector_string(v) for k, v in selectors.items()}


def canonicalize_selectors(
    selectors: dict[str, str],
    policy: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns normalized selectors plus canonical metadata used by the compiler.

    Primary kind is the first non-empty in policy-defined canonical order.
    """
    pol = policy or get_policy_bundle().data
    sp = pol.get("selectors") if isinstance(pol.get("selectors"), dict) else {}
    order_keys = list(sp.get("canonical_order") or ["css", "aria", "text_based", "xpath"])
    normalized = normalize_selectors_block(selectors)
    key_to_val = {k: normalized.get(k, "") for k in order_keys}
    ordered = [(k, key_to_val.get(k, "")) for k in order_keys]
    first_non_empty = next((k for k, v in ordered if v), order_keys[0] if order_keys else "css")
    signature_src = "||".join(str(key_to_val.get(k, "")) for k in order_keys)
    signature = hashlib.sha256(signature_src.encode("utf-8")).hexdigest()[:16]
    canonical_meta = {
        "primary_selector_kind": first_non_empty,
        "fallback_selector_order": ",".join(order_keys),
        "selector_signature": signature,
    }
    return normalized, canonical_meta
