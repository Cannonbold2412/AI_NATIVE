"""Extract 4 video frames per event for LLM-native selector verification.

For each event at timestamp T (in ms since video start), extract:
- T-500ms → frames/evt_NNNN_before_far.png
- T-100ms → frames/evt_NNNN_before_near.png
- T+100ms → frames/evt_NNNN_after_near.png
- T+500ms → frames/evt_NNNN_after_far.png

Updates events.jsonl in place: each event's visual.frames dict gets the 4 paths.
Uses ffmpeg (from Playwright's bundled binary, or PATH).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _find_ffmpeg() -> str | None:
    """Locate ffmpeg binary. Prefers Playwright's bundled ffmpeg, falls back to PATH."""
    try:
        import playwright
        pw_dir = Path(playwright.__file__).parent
        for candidate in pw_dir.rglob("ffmpeg*"):
            if candidate.is_file() and candidate.stat().st_mode & 0o111:
                return str(candidate)
    except ImportError:
        pass
    return shutil.which("ffmpeg")


def _extract_frame(
    ffmpeg: str,
    video_path: Path,
    out_path: Path,
    timestamp_ms: int,
) -> bool:
    """Extract a single frame at the given timestamp. Returns True on success."""
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
        if result.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0:
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def extract_frames_for_session(session_dir: Path) -> dict[str, Any]:
    """Extract 4 frames per event from recording.webm into session_dir/frames/.

    Returns a summary dict: {extracted_count, skipped_count, missing_video, error}
    """
    summary = {
        "extracted_count": 0,
        "skipped_count": 0,
        "missing_video": False,
        "error": "",
    }

    video_path = session_dir / "recording.webm"
    events_path = session_dir / "events.jsonl"

    if not video_path.is_file():
        summary["missing_video"] = True
        return summary

    if not events_path.is_file():
        summary["error"] = "events.jsonl not found"
        return summary

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        summary["error"] = "ffmpeg not found (install playwright or add ffmpeg to PATH)"
        return summary

    frames_dir = session_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    offsets = [
        ("before_far", -500),
        ("before_near", -100),
        ("after_near", 100),
        ("after_far", 500),
    ]

    events: list[dict[str, Any]] = []
    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    for i, ev in enumerate(events):
        visual = ev.setdefault("visual", {})
        ts_ms = visual.get("timestamp_ms")
        if ts_ms is None:
            summary["skipped_count"] += 1
            continue

        frames: dict[str, str] = {}
        for label, offset_ms in offsets:
            frame_path = frames_dir / f"evt_{i + 1:04d}_{label}.png"
            target_ms = int(ts_ms) + offset_ms
            if _extract_frame(ffmpeg, video_path, frame_path, target_ms):
                frames[label] = f"frames/evt_{i + 1:04d}_{label}.png"
                summary["extracted_count"] += 1

        if frames:
            visual["frames"] = frames

    with open(events_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    return summary
