from __future__ import annotations

from conxa_core import db
from conxa_core.config import settings
from conxa_core.storage import selector_cache


def test_selector_cache_keys_do_not_become_raw_windows_filenames(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "")
    monkeypatch.setattr(settings, "selector_cache_enabled", True)
    monkeypatch.setattr(db, "_engine", None)

    dom_hash = "cea88108de4a696aee0f0857533bc67e14fbb0d66ff897f8f612a1fc93e5bbc7"
    bbox = {"x": 880, "y": 421, "w": 172, "h": 36}
    model = "default"
    candidates = [{"selector": "button:has-text('Continue')"}]

    assert selector_cache.get(dom_hash, bbox, model) is None

    selector_cache.set(dom_hash, bbox, model, candidates)

    assert selector_cache.get(dom_hash, bbox, model) == candidates

    written_files = list(tmp_path.rglob("*.json"))
    assert written_files
    assert all(":" not in path.name for path in written_files)
    assert all("," not in path.name for path in written_files)
