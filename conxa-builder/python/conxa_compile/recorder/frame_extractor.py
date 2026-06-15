"""Extract 5 video frames per event for LLM-native selector verification.

For each event at timestamp T (in ms since video start), extract:
- T-500ms → frames/evt_NNNN_before_far.png
- T-250ms → frames/evt_NNNN_before_near.png  (default representative)
- T+0ms   → frames/evt_NNNN_at.png
- T+250ms → frames/evt_NNNN_after_near.png
- T+500ms → frames/evt_NNNN_after_far.png

After extraction, sets visual["full_screenshot"] to the before_near frame path
and visual["element_snapshot"] to a JPEG element crop from that frame (or None
when bbox w/h < 2). This replaces the old synchronous page.screenshot() capture.

Updates events.jsonl in place: each event's visual.frames dict gets the 5 paths.
Uses ffmpeg (from Playwright's bundled binary, imageio-ffmpeg, or PATH).

Raises on any failure (missing video, missing ffmpeg, per-frame failure,
missing event timestamp) — silent degradation is not allowed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from conxa_core.config import settings
from conxa_compile.recorder.visual import crop_element_from_frame


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt" and path.suffix.lower() in {".exe", ".cmd", ".bat"}:
        return True
    return bool(path.stat().st_mode & 0o111)


def _find_ffmpeg() -> str | None:
    """Locate ffmpeg binary. Prefers Playwright, then imageio-ffmpeg, then PATH."""
    # Search the Playwright browsers path (where ffmpeg is actually installed in
    # production deployments — driven by PLAYWRIGHT_BROWSERS_PATH env var, often /opt/pw-browsers).
    candidate_roots: list[Path] = []
    pw_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if pw_env and pw_env != "0":
        candidate_roots.append(Path(pw_env))
    # Common default locations
    for default in ("/opt/pw-browsers", str(Path.home() / ".cache" / "ms-playwright")):
        p = Path(default)
        if p.is_dir() and p not in candidate_roots:
            candidate_roots.append(p)
    # Playwright package dir (for in-package bundled ffmpeg in older versions)
    try:
        import playwright
        candidate_roots.append(Path(playwright.__file__).parent)
    except ImportError:
        pass
    for root in candidate_roots:
        try:
            for candidate in root.rglob("ffmpeg*"):
                if _is_executable_file(candidate):
                    return str(candidate)
        except OSError:
            continue

    try:
        import imageio_ffmpeg

        candidate = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if candidate.is_file():
            return str(candidate)
    except (ImportError, OSError, RuntimeError):
        pass

    return shutil.which("ffmpeg")


def _extract_frame(
    ffmpeg: str,
    video_path: Path,
    out_path: Path,
    timestamp_ms: int,
) -> None:
    """Extract a single frame at the given timestamp. Raises on failure."""
    if timestamp_ms < 0:
        timestamp_ms = 0
    seconds = timestamp_ms / 1000.0
    cmd = [
        ffmpeg,
        "-y",  # overwrite
        "-ss", f"{seconds:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        "-loglevel", "error",
        str(out_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"ffmpeg invocation failed: {exc!s} (cmd={' '.join(cmd)})") from exc

    if result.returncode != 0:
        stderr_snippet = result.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"ffmpeg exited {result.returncode} extracting {out_path.name}: {stderr_snippet}"
        )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg produced empty/missing frame: {out_path}")


def extract_frames_for_session(session_dir: Path) -> dict[int, dict[str, str]]:
    """Extract 4 frames per event from recording.webm into session_dir/frames/.

    Returns {event_index: {label: relative_path}} on success. Raises on any
    failure — missing video, missing ffmpeg, missing events.jsonl, event
    without timestamp_ms, or per-frame failure.
    """
    video_path = session_dir / "recording.webm"
    events_path = session_dir / "events.jsonl"

    if not video_path.is_file():
        raise FileNotFoundError(f"recording.webm not found in {session_dir}")
    if not events_path.is_file():
        raise FileNotFoundError(f"events.jsonl not found in {session_dir}")

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not available; install Playwright browsers (which bundles ffmpeg) "
            "or install imageio-ffmpeg, or add ffmpeg to PATH. Searched "
            "PLAYWRIGHT_BROWSERS_PATH, /opt/pw-browsers, ~/.cache/ms-playwright, "
            "the playwright package directory, imageio-ffmpeg, and PATH."
        )

    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    offsets = [
        ("before_far", -500),
        ("before_near", -250),
        ("at", 0),
        ("after_near", 250),
        ("after_far", 500),
    ]

    events: list[dict[str, Any]] = []
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))  # raises on invalid JSON — by design

    result: dict[int, dict[str, str]] = {}
    for i, ev in enumerate(events):
        visual = ev.setdefault("visual", {})
        ts_ms = visual.get("timestamp_ms")
        if ts_ms is None:
            raise ValueError(
                f"event index {i} has no visual.timestamp_ms; non-auth events must have one"
            )

        frames: dict[str, str] = {}
        for label, offset_ms in offsets:
            frame_path = frames_dir / f"evt_{i + 1:04d}_{label}.png"
            target_ms = int(ts_ms) + offset_ms
            _extract_frame(ffmpeg, video_path, frame_path, target_ms)
            frames[label] = f"frames/evt_{i + 1:04d}_{label}.png"

        visual["frames"] = frames

        # Set the default representative: before_near frame (T-250ms).
        # This is after the user initiated the action but before any page reaction/navigation,
        # so the target element is still present and the bbox is valid.
        representative_rel = frames["before_near"]
        visual["full_screenshot"] = representative_rel

        # Derive the element crop from the representative frame.
        representative_abs = session_dir / representative_rel
        bbox = visual.get("bbox") if isinstance(visual.get("bbox"), dict) else {}
        images_dir = session_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        el_out = images_dir / f"evt_{i + 1:04d}_element.jpg"
        el_rel = crop_element_from_frame(
            representative_abs,
            bbox,
            el_out,
            jpeg_quality=settings.screenshot_jpeg_quality,
        )
        visual["element_snapshot"] = el_rel

        result[i] = frames

    with open(events_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    return result
