from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
CORE_ROOT = REPO_ROOT / "packages" / "conxa-core"
for path in (ROOT, CORE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("SKILL_GROQ_ENABLED", "true")
os.environ.setdefault("SKILL_GROQ_API_KEYS", "test-key")

from conxa_compile import installer_builder  # noqa: E402
from services import installer_builder as studio_installer_builder  # noqa: E402


def _write_runtime_cache(
    home: Path,
    version: str,
    *,
    runtime: bytes | None = b"runtime",
    keytar: bytes | None = b"keytar",
) -> Path:
    runtime_dir = home / ".conxa-build-studio" / "deps" / "runtime" / version
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if runtime is not None:
        (runtime_dir / "runtime-win.exe").write_bytes(runtime)
    if keytar is not None:
        (runtime_dir / "keytar.node").write_bytes(keytar)
    return runtime_dir


class StudioRuntimeStagingTests(unittest.TestCase):
    def test_studio_cache_stages_runtime_keytar_and_version(self) -> None:
        logs: list[str] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            _write_runtime_cache(home, "v1.0.0", runtime=b"exe", keytar=b"node")
            dest = home / "stage"
            dest.mkdir()

            with patch.object(installer_builder.Path, "home", return_value=home):
                installer_builder._stage_runtime_binary(dest, logs.append)

            self.assertEqual((dest / "runtime.exe").read_bytes(), b"exe")
            self.assertEqual((dest / "keytar.node").read_bytes(), b"node")
            self.assertEqual(
                json.loads((dest / "version.json").read_text(encoding="utf-8")),
                {"runtime_version": "v1.0.0"},
            )
            self.assertTrue(any("Build Studio runtime.exe" in line for line in logs))

    def test_studio_cache_selects_newest_valid_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            _write_runtime_cache(home, "v1.0.2", runtime=b"old", keytar=b"old-node")
            _write_runtime_cache(home, "v1.0.10", runtime=b"new", keytar=b"new-node")
            dest = home / "stage"
            dest.mkdir()

            with patch.object(installer_builder.Path, "home", return_value=home):
                installer_builder._stage_runtime_binary(dest)

            self.assertEqual((dest / "runtime.exe").read_bytes(), b"new")
            self.assertEqual(
                json.loads((dest / "version.json").read_text(encoding="utf-8"))["runtime_version"],
                "v1.0.10",
            )

    def test_studio_cache_fails_if_latest_runtime_dir_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            _write_runtime_cache(home, "v1.0.9", runtime=b"old", keytar=b"old-node")
            _write_runtime_cache(home, "v1.0.10", runtime=b"new", keytar=None)
            dest = home / "stage"
            dest.mkdir()

            with patch.object(installer_builder.Path, "home", return_value=home):
                with self.assertRaisesRegex(RuntimeError, "Latest Build Studio runtime is missing keytar.node"):
                    installer_builder._stage_runtime_binary(dest)

    def test_studio_cache_missing_runtime_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            dest = home / "stage"
            dest.mkdir()

            with patch.object(installer_builder.Path, "home", return_value=home):
                with self.assertRaisesRegex(RuntimeError, "Local Build Studio runtime not found"):
                    installer_builder._stage_runtime_binary(dest)

    def test_studio_cache_missing_keytar_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            _write_runtime_cache(home, "v1.0.0", runtime=b"exe", keytar=None)
            dest = home / "stage"
            dest.mkdir()

            with patch.object(installer_builder.Path, "home", return_value=home):
                with self.assertRaisesRegex(RuntimeError, "keytar.node"):
                    installer_builder._stage_runtime_binary(dest)


class StudioInstallerWrapperTests(unittest.TestCase):
    def test_wrapper_delegates_without_runtime_compatibility_args(self) -> None:
        with patch.dict(os.environ, {"MAKENSIS_PATH": "already-set"}), patch.object(
            installer_builder, "build_installer", return_value={"ok": True}
        ) as build:
            result = studio_installer_builder.build_installer("plugin-1", company_slug="acme")

        self.assertEqual(result, {"ok": True})
        self.assertNotIn("runtime_source", build.call_args.kwargs)
        self.assertNotIn("cloud_api", build.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
