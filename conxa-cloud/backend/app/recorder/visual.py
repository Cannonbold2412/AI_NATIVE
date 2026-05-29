"""Viewport screenshots + compressed element crops (paths only in events)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image


def _dpr_from_page(page) -> float:
    dpr = page.evaluate("() => window.devicePixelRatio || 1")
    try:
        return float(dpr)
    except (TypeError, ValueError):
        return 1.0


def save_action_images(
    page,
    session_dir: Path,
    seq: int,
    bbox: dict[str, Any],
    *,
    jpeg_quality: int,
) -> tuple[str | None, str | None]:
    """
    Writes full viewport JPEG and optional element crop.
    Returns relative paths from session_dir (posix-style for JSON portability).
    """
    images_dir = session_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    stem = f"evt_{seq:04d}"
    full_name = f"{stem}_full.jpg"
    full_path = images_dir / full_name
    raw = page.screenshot(type="jpeg", quality=jpeg_quality, full_page=False)
    full_path.write_bytes(raw)

    w = int(bbox.get("w") or 0)
    h = int(bbox.get("h") or 0)
    if w < 2 or h < 2:
        return f"images/{full_name}", None

    dpr = _dpr_from_page(page)
    x = max(0, int(round(float(bbox["x"]) * dpr)))
    y = max(0, int(round(float(bbox["y"]) * dpr)))
    x2 = x + max(1, int(round(float(w) * dpr)))
    y2 = y + max(1, int(round(float(h) * dpr)))

    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        W, H = im.size
        x2 = min(W, x2)
        y2 = min(H, y2)
        if x2 <= x or y2 <= y:
            return f"images/{full_name}", None
        crop = im.crop((x, y, x2, y2))
        el_name = f"{stem}_element.jpg"
        el_path = images_dir / el_name
        crop.save(el_path, format="JPEG", quality=jpeg_quality, optimize=True)
        return f"images/{full_name}", f"images/{el_name}"
