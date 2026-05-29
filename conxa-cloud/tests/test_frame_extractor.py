from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from conxa_compile.recorder import frame_extractor


def test_find_ffmpeg_uses_imageio_ffmpeg_fallback(monkeypatch, tmp_path) -> None:
    executable = tmp_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    executable.write_bytes(b"fake")
    executable.chmod(0o755)

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(frame_extractor.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        SimpleNamespace(get_ffmpeg_exe=lambda: str(executable)),
    )
    monkeypatch.setattr(frame_extractor.shutil, "which", lambda _name: None)

    assert frame_extractor._find_ffmpeg() == str(executable)
