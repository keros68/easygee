from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills" / "easygee" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import easygee_project  # noqa: E402


def load_preview_module():
    name = "serve_map_preview_persistence_test"
    path = SCRIPT_DIR / "serve_map_preview.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fail_path_replace(_source: Path, _target: Path) -> None:
    raise OSError(17, "cross-device rename")


def test_settings_write_falls_back_when_path_replace_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "nested" / "settings.json"
    monkeypatch.setattr(Path, "replace", fail_path_replace)

    easygee_project.save_settings({"earthEngineProject": "demo-project"}, target)

    assert json.loads(target.read_text(encoding="utf-8"))["earthEngineProject"] == "demo-project"
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_map_console_writes_fall_back_when_os_replace_fails(tmp_path, monkeypatch) -> None:
    preview = load_preview_module()
    profile_path = tmp_path / "nested" / "profile.json"
    preview.configure_profile_path(profile_path)
    monkeypatch.setattr(preview.os, "replace", fail_path_replace)

    preview.write_profile_unlocked({"favoriteDatasets": ["COPERNICUS/S2_SR_HARMONIZED"]})
    preview.write_secret_store_unlocked({"version": 1, "secrets": {"tianditu": "encrypted"}})

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    secrets_path = profile_path.with_name("map-console-secrets.json")
    secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
    assert profile["favoriteDatasets"] == ["COPERNICUS/S2_SR_HARMONIZED"]
    assert secrets["secrets"]["tianditu"] == "encrypted"
    assert not profile_path.with_name("profile.json.tmp").exists()
    assert not secrets_path.with_name("map-console-secrets.json.tmp").exists()
