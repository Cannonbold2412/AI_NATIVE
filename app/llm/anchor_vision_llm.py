"""Vision-only anchor generation at compile time (multimodal LLM)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.compiler.v3 import finalize_vision_anchors
from app.config import settings
from app.llm.client import call_llm, supports_multimodal_chat
from app.policy.bundle import get_policy_bundle


class VisionAnchorGenerationError(Exception):
    """Compile must abort when vision anchors cannot be produced."""

    def __init__(self, reason: str, *, step_index: int | None = None, hint: str | None = None):
        self.reason = reason
        self.step_index = step_index
        self.hint = hint.strip()[:500] if hint else None
        super().__init__(reason)

    def api_detail(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "code": "vision_anchors_failed",
            "reason": self.reason,
            "step_index": self.step_index,
        }
        if self.hint:
            d["hint"] = self.hint
        return d


def _cache_path() -> Path:
    p = settings.data_dir / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "anchor_vision_llm_cache.json"


def _read_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    _cache_path().write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _vision_cfg(policy: dict[str, Any]) -> dict[str, Any]:
    sec = policy.get("anchors") if isinstance(policy.get("anchors"), dict) else {}
    raw = sec.get("vision")
    return raw if isinstance(raw, dict) else {}


def _parse_viewport_wh(viewport: str) -> tuple[int | None, int | None]:
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", str(viewport or "").strip(), re.I)
    if not m:
        return None, None
    try:
        return int(m.group(1)), int(m.group(2))
    except ValueError:
        return None, None


def _apply_bbox_highlight(
    image_bytes: bytes,
    bbox: dict[str, Any],
    viewport: str,
    *,
    highlight_alpha: float,
) -> bytes:
    alpha = max(0.0, min(1.0, float(highlight_alpha)))
    try:
        x = float(bbox.get("x") or 0)
        y = float(bbox.get("y") or 0)
        w = float(bbox.get("w") or 0)
        h = float(bbox.get("h") or 0)
    except (TypeError, ValueError):
        return image_bytes
    if w < 1 or h < 1:
        return image_bytes
    with Image.open(io.BytesIO(image_bytes)) as im:
        im = im.convert("RGB")
        vw, vh = _parse_viewport_wh(viewport)
        dpr_x = (im.size[0] / vw) if vw and vw > 0 else 1.0
        dpr_y = (im.size[1] / vh) if vh and vh > 0 else dpr_x
        x1 = max(0, int(round(x * dpr_x)))
        y1 = max(0, int(round(y * dpr_y)))
        x2 = min(im.size[0], int(round((x + w) * dpr_x)))
        y2 = min(im.size[1], int(round((y + h) * dpr_y)))
        if x2 <= x1 or y2 <= y1:
            return image_bytes
        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        fill = (255, 0, 0, int(255 * alpha))
        outline = (255, 80, 80, 255)
        draw.rectangle((x1, y1, x2, y2), fill=fill, outline=outline, width=int(max(2, min(im.size) // 400)))
        base = im.convert("RGBA")
        base = Image.alpha_composite(base, overlay)
        base = base.convert("RGB")
        buf = io.BytesIO()
        base.save(buf, format="JPEG", quality=settings.screenshot_jpeg_quality, optimize=True)
        return buf.getvalue()


def resolve_screenshot_path(session_root: Path, rel: str) -> Path:
    """Resolve a screenshot path relative to ``session_root``.

    Compiled skills persist paths like ``sessions/<id>/images/foo.jpg``. Strip that
    prefix when it matches ``session_root`` so the same vision pipeline works for
    raw recorder events (``images/...`` only) and for editor-swapped visuals.
    """
    root = session_root.resolve()
    raw = rel.strip().replace("\\", "/")
    if not raw or ".." in raw:
        raise VisionAnchorGenerationError("screenshot_path_invalid")
    sid = session_root.name
    prefix = f"sessions/{sid}/"
    if raw.startswith(prefix):
        raw = raw[len(prefix) :]
    elif raw.startswith("sessions/"):
        raise VisionAnchorGenerationError("screenshot_path_wrong_session")
    candidate = (root / raw).resolve()
    if root not in candidate.parents and candidate != root:
        raise VisionAnchorGenerationError("screenshot_path_escapes_session")
    return candidate


def generate_anchors_for_step_or_raise(
    ev: dict[str, Any],
    *,
    session_root: Path,
    final_intent: str,
    policy: dict[str, Any],
    step_index: int,
) -> list[dict[str, Any]]:
    """Return vision-only anchors or raise VisionAnchorGenerationError."""
    if not bool(_vision_cfg(policy).get("enabled", True)):
        raise VisionAnchorGenerationError("vision_anchors_disabled_in_policy", step_index=step_index)
    if not settings.llm_enabled:
        raise VisionAnchorGenerationError("llm_disabled", step_index=step_index)
    if not settings.llm_anchor_vision:
        raise VisionAnchorGenerationError("llm_anchor_vision_disabled", step_index=step_index)
    if not str(settings.llm_endpoint or "").strip():
        raise VisionAnchorGenerationError("llm_endpoint_unset", step_index=step_index)
    if not supports_multimodal_chat():
        raise VisionAnchorGenerationError("llm_endpoint_not_multimodal_capable", step_index=step_index)

    visual = ev.get("visual") if isinstance(ev.get("visual"), dict) else {}
    rel_path = str(visual.get("full_screenshot") or "").strip()
    if not rel_path:
        raise VisionAnchorGenerationError("full_screenshot_path_missing", step_index=step_index)

    abs_path = resolve_screenshot_path(session_root, rel_path)
    if not abs_path.is_file():
        raise VisionAnchorGenerationError(f"screenshot_file_missing:{rel_path}", step_index=step_index)

    raw_bytes = abs_path.read_bytes()
    bbox = visual.get("bbox") if isinstance(visual.get("bbox"), dict) else {}
    viewport = str(visual.get("viewport") or "")
    vcfg = _vision_cfg(policy)
    hi = float(vcfg.get("highlight_alpha", 0.35))
    image_bytes = _apply_bbox_highlight(raw_bytes, bbox, viewport, highlight_alpha=hi)
    image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")

    prompt_ver = str(vcfg.get("prompt_version", "1"))
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "h": hashlib.sha256(image_bytes).hexdigest(),
                "bbox": bbox,
                "intent": final_intent,
                "pv": prompt_ver,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    cache = _read_cache()
    if cache_key in cache:
        entry = cache[cache_key]
        if isinstance(entry, dict) and entry.get("anchors"):
            return [dict(a) for a in entry["anchors"]]

    try:
        with Image.open(io.BytesIO(image_bytes)) as _im_sz:
            bw, bh = int(_im_sz.size[0]), int(_im_sz.size[1])
    except Exception:
        raise VisionAnchorGenerationError("screenshot_unreadable", step_index=step_index) from None

    user_text = (
        "Look at this UI screenshot. The highlighted region is the target element.\n\n"
        f"Image size (pixels): {bw}x{bh}. Viewport (CSS px): {viewport or 'unknown'}.\n"
        f"Target bounding box (CSS px): x={bbox.get('x')}, y={bbox.get('y')}, "
        f"w={bbox.get('w')}, h={bbox.get('h')}.\n"
        f"User intent hint (snake_case): {final_intent or 'unknown'}\n\n"
        "Describe what the target is in one short, human-friendly phrase (primary_phrase). "
        "Add up to three secondary anchors: section, parent, or nearby labeled controls — "
        "each with relation inside, above, below, or near.\n"
        "Avoid DOM jargon (no div/container/element-only). Return JSON only."
    )

    payload = {
        "model": settings.llm_vision_model or None,
        "user_text": user_text,
        "image_base64": image_b64,
        "image_mime": "image/jpeg",
    }
    err_lines: list[str] = []
    data = call_llm(
        "anchor_vision",
        payload,
        settings.llm_vision_timeout_ms,
        error_detail=err_lines,
    )
    if not isinstance(data, dict):
        joined = "; ".join(err_lines) if err_lines else ""
        if joined:
            raise VisionAnchorGenerationError(
                "vision_llm_request_failed",
                step_index=step_index,
                hint=joined,
            )
        raise VisionAnchorGenerationError("vision_llm_empty_response", step_index=step_index)

    primary = str(data.get("primary_phrase") or data.get("primary") or "").strip()
    sec_raw = data.get("secondary")
    if not isinstance(sec_raw, list):
        sec_raw = []

    finalized = finalize_vision_anchors(primary, sec_raw, policy)
    if not finalized or str(finalized[0].get("relation") or "") != "target" or not str(
        finalized[0].get("element") or ""
    ).strip():
        raise VisionAnchorGenerationError("vision_llm_invalid_primary_phrase", step_index=step_index)

    cache[cache_key] = {"anchors": finalized}
    _write_cache(cache)
    return finalized

