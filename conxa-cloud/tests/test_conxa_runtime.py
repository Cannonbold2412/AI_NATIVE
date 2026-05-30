"""Tests for conxa_compile/conxa_runtime.py (runtime dir resolution + skill-pack sync)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── resolve_runtime_dir ───────────────────────────────────────────────────────

class TestResolveRuntimeDir:
    def test_env_override_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "server.js").touch()
        monkeypatch.setenv("CONXA_DIR", str(tmp_path))
        from conxa_compile import conxa_runtime
        monkeypatch.delattr(conxa_runtime, "resolve_runtime_dir", raising=False)
        import importlib
        importlib.reload(conxa_runtime)
        result = conxa_runtime.resolve_runtime_dir()
        assert result == tmp_path

    def test_env_override_ignored_if_missing_server_js(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # tmp_path exists but has no server.js
        monkeypatch.setenv("CONXA_DIR", str(tmp_path))
        from conxa_compile.conxa_runtime import resolve_runtime_dir
        with patch.dict("os.environ", {"CONXA_DIR": str(tmp_path)}):
            result = resolve_runtime_dir()
        # Should fall through to installed or dev fallback, not return tmp_path
        assert result != tmp_path

    def test_dev_fallback_found_when_server_js_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Repo's ./runtime/ should be returned when server.js + package.json exist."""
        from conxa_compile.conxa_runtime import resolve_runtime_dir
        repo_root = Path(__file__).resolve().parent.parent
        dev = repo_root / "runtime"
        if not (dev / "server.js").is_file():
            pytest.skip("Dev runtime not present")
        with patch.dict("os.environ", {}, clear=False):
            if "CONXA_DIR" in __import__("os").environ:
                monkeypatch.delenv("CONXA_DIR", raising=False)
            result = resolve_runtime_dir()
        assert result is not None
        assert (result / "server.js").is_file()

    def test_returns_none_when_nothing_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONXA_DIR", raising=False)
        from conxa_compile.conxa_runtime import resolve_runtime_dir
        # Patch Path.home() and the repo-root lookup to point at empty tmp dirs
        with patch("conxa_compile.conxa_runtime.Path") as mock_path:
            mock_path.home.return_value = tmp_path / "fakehome"
            mock_path.return_value.__truediv__ = lambda s, o: tmp_path / o
            # This is hard to mock cleanly due to __file__ usage; just assert None is possible
            # by ensuring the installed path doesn't exist
            pass
        # Pragmatic: if runtime/ exists in repo, skip this test
        repo_root = Path(__file__).resolve().parent.parent
        if (repo_root / "runtime" / "server.js").is_file():
            pytest.skip("Dev runtime present — cannot test None case")
        if sys.platform == "win32":
            installed = Path(r"C:\Program Files\Conxa")
        else:
            installed = Path.home() / ".conxa"
        if (installed / "server.js").is_file():
            pytest.skip("Installed runtime present — cannot test None case")
        result = resolve_runtime_dir()
        assert result is None


# ─── sync_skill_pack ──────────────────────────────────────────────────────────

class TestSyncSkillPack:
    def test_copies_source_to_runtime(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / "my-plugin"
        source.mkdir(parents=True)
        (source / "pack.json").write_text('{"skills":[]}', encoding="utf-8")
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()

        from conxa_compile.conxa_runtime import sync_skill_pack
        with patch("conxa_compile.conxa_runtime.resolve_conxa_data_dir", return_value=tmp_path / "data"):
            sync_skill_pack(company="my-plugin", source_dir=source, runtime_dir=runtime_dir)

        dest = runtime_dir / "skill-packs" / "my-plugin"
        assert (dest / "pack.json").is_file()
        assert (dest / "pack.json").read_text() == '{"skills":[]}'

    def test_noop_when_source_missing(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir()
        from conxa_compile.conxa_runtime import sync_skill_pack
        with patch("conxa_compile.conxa_runtime.resolve_conxa_data_dir", return_value=tmp_path / "data"):
            sync_skill_pack(company="x", source_dir=tmp_path / "nonexistent", runtime_dir=runtime_dir)
        # No dest should be created
        assert not (runtime_dir / "skill-packs" / "x").exists()

    def test_busts_manifest_cache(self, tmp_path: Path) -> None:
        source = tmp_path / "src"
        source.mkdir()
        (source / "pack.json").write_text("{}", encoding="utf-8")
        runtime_dir = tmp_path / "rt"
        runtime_dir.mkdir()
        # Create a fake cache file
        cache_dir = tmp_path / "data" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "manifests.json"
        cache_file.write_text("{}", encoding="utf-8")

        from conxa_compile.conxa_runtime import sync_skill_pack
        with patch("conxa_compile.conxa_runtime.resolve_conxa_data_dir", return_value=tmp_path / "data"):
            sync_skill_pack(company="c", source_dir=source, runtime_dir=runtime_dir)

        assert not cache_file.exists(), "Manifest cache should be deleted after sync"

    def test_replaces_existing_files(self, tmp_path: Path) -> None:
        source = tmp_path / "src"
        source.mkdir()
        (source / "pack.json").write_text('{"v":2}', encoding="utf-8")
        runtime_dir = tmp_path / "rt"
        dest = runtime_dir / "skill-packs" / "c"
        dest.mkdir(parents=True)
        (dest / "pack.json").write_text('{"v":1}', encoding="utf-8")  # old version

        from conxa_compile.conxa_runtime import sync_skill_pack
        with patch("conxa_compile.conxa_runtime.resolve_conxa_data_dir", return_value=tmp_path / "data"):
            sync_skill_pack(company="c", source_dir=source, runtime_dir=runtime_dir)

        assert (dest / "pack.json").read_text() == '{"v":2}'
