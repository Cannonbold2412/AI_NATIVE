"""Pre-execution environment drift detection.

Before a skill runs, navigates to the start URL and checks whether the page
structure matches what was recorded. Returns a drift report that identifies
missing landmarks so the user can decide whether to proceed or re-record.

This is a deterministic check — no LLM, no screenshots. It uses the
structural_fingerprint compiled into SkillMeta at compile time.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page


async def check_drift(
    page: Page,
    structural_fingerprint: dict[str, Any],
    *,
    timeout_ms: int = 8000,
) -> dict[str, Any]:
    """Navigate to start URL and score landmark presence against the fingerprint.

    Returns:
        {
            "drift_score": float,       # 0.0 = no drift, 1.0 = all landmarks missing
            "landmarks_total": int,
            "landmarks_found": int,
            "landmarks_missing": list[dict],
            "page_url": str,
            "safe_to_proceed": bool,    # True if drift_score < 0.5
        }
    """
    landmarks: list[dict[str, Any]] = structural_fingerprint.get("landmarks") or []
    if not landmarks:
        return {
            "drift_score": 0.0,
            "landmarks_total": 0,
            "landmarks_found": 0,
            "landmarks_missing": [],
            "page_url": page.url,
            "safe_to_proceed": True,
            "note": "No structural fingerprint available — skip drift check",
        }

    missing: list[dict[str, Any]] = []
    found_count = 0

    for lm in landmarks:
        found = await _check_landmark(page, lm, timeout_ms=min(timeout_ms, 3000))
        if found:
            found_count += 1
        else:
            missing.append(lm)

    total = len(landmarks)
    drift_score = round(1.0 - found_count / max(total, 1), 3)

    return {
        "drift_score": drift_score,
        "landmarks_total": total,
        "landmarks_found": found_count,
        "landmarks_missing": missing,
        "page_url": page.url,
        "safe_to_proceed": drift_score < 0.5,
    }


async def _check_landmark(page: Page, lm: dict[str, Any], *, timeout_ms: int) -> bool:
    """Return True if the landmark can be found on the current page."""
    primary = str(lm.get("primary_selector") or "").strip()
    data_testid = str(lm.get("data_testid") or "").strip()
    aria_label  = str(lm.get("aria_label") or "").strip()
    inner_text  = str(lm.get("inner_text") or "").strip()
    tag         = str(lm.get("tag") or "").strip()

    # Try in order of stability: data-testid, aria-label, primary CSS, text
    candidates: list[str] = []
    if data_testid:
        candidates += [f'[data-testid="{data_testid}"]', f'[data-test="{data_testid}"]']
    if aria_label:
        candidates.append(f'[aria-label="{aria_label}"]')
    if primary:
        candidates.append(primary)
    if inner_text and tag:
        candidates.append(f'{tag}:has-text("{inner_text[:40]}")')

    for sel in candidates:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="attached", timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False
