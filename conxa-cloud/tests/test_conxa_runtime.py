"""Tests for conxa_compile/conxa_runtime.py (runtime dir resolution + skill-pack sync)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ─── resolve_runtime_dir ───────────────────────────────────────────────────────

class TestResolveRuntimeDir:
    def test_env_override_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "server.js").touch()
        (tmp_path / "package.json").touch()
        monkeypatch.setenv("CONXA_DIR", str(tmp_path))
        monkeypatch.delenv("CONXA_RUNTIME_LOCAL_DIR", raising=False)

        from conxa_compile.conxa_runtime import resolve_runtime_dir

        result = resolve_runtime_dir()

        assert result == tmp_path

    def test_env_override_ignored_if_invalid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONXA_DIR", str(tmp_path))
        monkeypatch.delenv("CONXA_RUNTIME_LOCAL_DIR", raising=False)
        monkeypatch.setenv("SKILL_DATA_DIR", str(tmp_path / "data"))

        from conxa_compile.conxa_runtime import resolve_runtime_dir

        result = resolve_runtime_dir()

        assert result is None

    def test_runtime_local_dir_takes_priority(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        invalid_env = tmp_path / "invalid"
        runtime_dir = tmp_path / "runtime-v1.2.3"
        runtime_dir.mkdir()
        (runtime_dir / "runtime-win.exe").touch()
        monkeypatch.setenv("CONXA_DIR", str(invalid_env))
        monkeypatch.setenv("CONXA_RUNTIME_LOCAL_DIR", str(runtime_dir))

        from conxa_compile.conxa_runtime import resolve_runtime_dir

        result = resolve_runtime_dir()

        assert result == runtime_dir

    def test_deps_managed_runtime_is_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONXA_DIR", raising=False)
        monkeypatch.delenv("CONXA_RUNTIME_LOCAL_DIR", raising=False)
        monkeypatch.setenv("SKILL_DATA_DIR", str(tmp_path / "data"))
        runtime_dir = tmp_path / "data" / "deps" / "runtime" / "runtime-v1.0.0"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "runtime-win.exe").touch()

        from conxa_compile.conxa_runtime import resolve_runtime_dir

        result = resolve_runtime_dir()

        assert result == runtime_dir

    def test_returns_none_when_nothing_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONXA_DIR", raising=False)
        monkeypatch.delenv("CONXA_RUNTIME_LOCAL_DIR", raising=False)
        monkeypatch.setenv("SKILL_DATA_DIR", str(tmp_path / "data"))

        from conxa_compile.conxa_runtime import resolve_runtime_dir

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
