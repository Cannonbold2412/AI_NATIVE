from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import bootstrap  # noqa: E402


class _FakeResponse:
    def __init__(self, chunks: list[bytes], total: int | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = {}
        if total is not None:
            self.headers["content-length"] = str(total)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class BootstrapDownloadTests(unittest.TestCase):
    def test_download_emits_byte_progress_speed_and_eta(self) -> None:
        events: list[dict] = []
        response = _FakeResponse([b"abc", b"def"], total=6)
        now = 100.0

        def monotonic() -> float:
            nonlocal now
            now += 0.3
            return now

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "runtime-win.exe"
            with patch.object(bootstrap.urllib.request, "urlopen", return_value=response), patch.object(
                bootstrap.time, "monotonic", side_effect=monotonic
            ):
                bootstrap._download("https://example.test/runtime-win.exe", dest, events.append, "runtime")

            self.assertEqual(dest.read_bytes(), b"abcdef")

        progress = [e for e in events if e.get("status") == "downloading"]
        self.assertGreaterEqual(len(progress), 3)
        self.assertEqual(progress[-1]["downloaded_bytes"], 6)
        self.assertEqual(progress[-1]["total_bytes"], 6)
        self.assertEqual(progress[-1]["remaining_bytes"], 0)
        self.assertEqual(progress[-1]["pct"], 100)
        self.assertEqual(progress[-1]["file_name"], "runtime-win.exe")
        self.assertGreater(progress[-1]["bytes_per_sec"], 0)
        in_progress = [e for e in progress if e.get("remaining_bytes", 0) > 0]
        self.assertTrue(any("eta_seconds" in e for e in in_progress))

    def test_download_failure_removes_temp_file_and_reports_allow_url(self) -> None:
        events: list[dict] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "nsis.zip"
            with patch.object(bootstrap.urllib.request, "urlopen", side_effect=OSError("network down")):
                with self.assertRaises(OSError):
                    bootstrap._download("https://example.test/nsis.zip", dest, events.append, "nsis")

            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_suffix(".zip.tmp").exists())

        self.assertEqual(events[-1]["status"], "error")
        self.assertEqual(events[-1]["url"], "https://example.test/nsis.zip")
        self.assertIn("allow", events[-1]["message"])


if __name__ == "__main__":
    unittest.main()
