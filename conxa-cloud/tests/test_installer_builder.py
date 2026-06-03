from conxa_compile.installer_builder import _render_nsis_script


def test_rendered_nsis_uses_skill_packs_paths(tmp_path):
    nsi_path = _render_nsis_script(tmp_path, "render", "Render", "v1.0.0")
    rendered = nsi_path.read_text(encoding="utf-8")

    assert r"${INSTALL_DIR}\skill-packs\${COMPANY_SLUG}" in rendered
    assert r"${STAGING_DIR}\skill-packs\${COMPANY_SLUG}\*.*" in rendered
    assert r"${INSTALL_DIR}\plugins\*.*" not in rendered
    assert r"${STAGING_DIR}\plugins\${COMPANY_SLUG}\*.*" not in rendered


def test_build_installer_packages_existing_skill_pack_without_rebuild(tmp_path, monkeypatch):
    import subprocess

    from conxa_core.config import settings
    from conxa_core.models.plugin import Plugin, PluginBuild
    from conxa_compile import installer_builder
    from conxa_compile import plugin_builder
    from conxa_core.storage import plugin_store

    skill_pack = tmp_path / "skill-packs" / "render"
    skill_pack.mkdir(parents=True)
    (skill_pack / "pack.json").write_text(
        '{"skill_pack_version":"v9.9.9","skills":["delete-a-service","create-a-service"],"sync_token":"sync-token"}',
        encoding="utf-8",
    )

    plugin = Plugin(
        id="plugin-1",
        slug="render",
        name="Render",
        workspace_id="ws-1",
        target_url="https://dashboard.render.com/login",
        status="ready",
        build=PluginBuild(last_built_at=1.0, output_path=str(tmp_path / "out"), version="v9.9.9"),
    )

    def fail_rebuild(*args, **kwargs):
        raise AssertionError("build_installer must not rebuild the plugin")

    studio_runtime_dir = tmp_path / ".conxa-build-studio" / "deps" / "runtime" / "runtime-v-local"
    studio_runtime_dir.mkdir(parents=True)

    def fake_stage_runtime(dest, log=None, *, studio_runtime_dir=None):
        (dest / "runtime.exe").write_bytes(b"runtime")
        (dest / "keytar.node").write_bytes(b"keytar")
        (dest / "version.json").write_text('{"runtime_version":"runtime-v-local"}', encoding="utf-8")

    def fake_run(args, **kwargs):
        output_arg = next(arg for arg in args if str(arg).startswith("/DOUTPUT_PATH="))
        output_path = output_arg.split("=", 1)[1]
        with open(output_path, "wb") as f:
            f.write(b"installer")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(plugin_builder, "build_plugin", fail_rebuild)
    monkeypatch.setattr(plugin_store, "get_plugin", lambda plugin_id: plugin)
    monkeypatch.setattr(plugin_store, "set_installer", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer_builder, "_find_makensis", lambda: "makensis")
    monkeypatch.setattr(installer_builder, "_find_studio_cache_runtime_dir", lambda: studio_runtime_dir)
    monkeypatch.setattr(installer_builder, "_stage_runtime_binary", fake_stage_runtime)
    monkeypatch.setattr(installer_builder.subprocess, "run", fake_run)

    logs = []
    result = installer_builder.build_installer(
        plugin.id,
        company_slug="render",
        realtime_sink=lambda event: logs.append(event["message"]),
    )

    assert result["version"] == "v9.9.9"
    assert (tmp_path / "installers" / "Render-Claude-Setup.exe").is_file()
    assert any("Using existing skill pack" in message for message in logs)
    assert not any("Building skill pack" in message for message in logs)
