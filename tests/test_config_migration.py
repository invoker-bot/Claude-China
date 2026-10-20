from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import stat
import threading

import pytest
import yaml

from src.claude_china import config
from src.claude_china import config_paths
from src.claude_china.desktop import config as desktop_config


@pytest.fixture
def settings_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current = tmp_path / ".claudec"
    legacy = tmp_path / ".code-ai"
    monkeypatch.setattr(config, "CONFIG_DIR", current)
    monkeypatch.setattr(config, "CONFIG_FILE", current / "config.yaml")
    monkeypatch.setattr(desktop_config, "DESKTOP_CONFIG_FILE", current / "desktop.yaml")
    return current, legacy


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_new_install_only_creates_claudec(settings_home):
    current, legacy = settings_home
    assert config.load_config() == {"profiles": {}}
    assert desktop_config.load_desktop_config() == desktop_config.DEFAULTS
    assert (current / "config.yaml").is_file()
    assert (current / "desktop.yaml").is_file()
    assert not legacy.exists()


def test_import_preserves_credentials_comments_and_old_files(settings_home):
    current, legacy = settings_home
    profiles = {"profiles": {
        "接口": {"name": "接口", "type": "claude", "mode": "api", "token": "test-token"},
        "login": {"name": "login", "type": "codex", "mode": "login",
                  "credentials_path": str(legacy / "credentials")},
    }}
    desktop = {"check_system_proxy": False, "env_vars": {"TEST_KEY": "test-value"},
               "apps": {"claude": {"path": "/custom/claude", "env_vars": {"X": "Y"}}}}
    write_yaml(legacy / "config.yaml", profiles)
    write_yaml(legacy / "desktop.yaml", desktop)
    (legacy / "credentials").mkdir()
    (legacy / "credentials" / "auth.json").write_text("test auth", encoding="utf-8")
    for name in ("config.yaml", "desktop.yaml"):
        with (legacy / name).open("ab") as stream:
            stream.write(b"# Keep this comment.\n")
    original = {name: (legacy / name).read_bytes() for name in ("config.yaml", "desktop.yaml")}

    assert config.load_config() == profiles
    assert desktop_config.load_desktop_config() == desktop
    for name, content in original.items():
        assert (current / name).read_bytes() == content
        assert (legacy / name).read_bytes() == content
    assert (legacy / "credentials" / "auth.json").read_text() == "test auth"
    assert sorted(path.name for path in current.iterdir()) == ["config.yaml", "desktop.yaml"]


def test_existing_new_files_win_without_merging_old_profiles(settings_home):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {"old": {"token": "old-token"}}})
    write_yaml(legacy / "desktop.yaml", {"check_system_proxy": False})
    write_yaml(current / "config.yaml", {"profiles": {}})
    write_yaml(current / "desktop.yaml", desktop_config.DEFAULTS)
    before = {name: (current / name).read_bytes() for name in ("config.yaml", "desktop.yaml")}

    assert config.load_config() == {"profiles": {}}
    assert desktop_config.load_desktop_config() == desktop_config.DEFAULTS
    for name, content in before.items():
        assert (current / name).read_bytes() == content


@pytest.mark.parametrize("existing", ["config.yaml", "desktop.yaml"])
def test_imports_each_missing_file_independently(settings_home, existing):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}, "marker": "old"})
    write_yaml(legacy / "desktop.yaml", {"check_system_proxy": False, "env_vars": {}, "apps": {}})
    data = {"profiles": {}, "marker": "new"} if existing == "config.yaml" else desktop_config.DEFAULTS
    write_yaml(current / existing, data)

    profiles = config.load_config()
    desktop = desktop_config.load_desktop_config()
    assert profiles["marker"] == ("new" if existing == "config.yaml" else "old")
    assert desktop["check_system_proxy"] == (existing == "desktop.yaml")


def test_legacy_schema_upgrade_only_changes_new_copy(settings_home):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {"old": {"type": "claude", "token": "test"}}})
    original = (legacy / "config.yaml").read_bytes()
    data = config.load_config()
    assert data["profiles"]["old"]["name"] == "old"
    assert data["profiles"]["old"]["mode"] == "api"
    assert yaml.safe_load((current / "config.yaml").read_text()) == data
    assert (legacy / "config.yaml").read_bytes() == original


def test_subsequent_saves_only_update_new_directory(settings_home):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}, "marker": "old"})
    write_yaml(legacy / "desktop.yaml", {"check_system_proxy": False})
    original = {name: (legacy / name).read_bytes() for name in ("config.yaml", "desktop.yaml")}
    data = config.load_config()
    data["marker"] = "new"
    config.save_config(data)
    desktop = desktop_config.load_desktop_config()
    desktop["check_system_proxy"] = True
    desktop_config.save_desktop_config(desktop)

    assert config.load_config()["marker"] == "new"
    assert desktop_config.load_desktop_config()["check_system_proxy"] is True
    for name, content in original.items():
        assert (legacy / name).read_bytes() == content


def test_custom_paths_do_not_import_user_settings(settings_home, tmp_path, monkeypatch):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {"old": {"token": "test"}}})
    write_yaml(legacy / "desktop.yaml", {"check_system_proxy": False})
    custom = tmp_path / "smoke" / "nested"
    monkeypatch.setattr(config, "CONFIG_FILE", custom / "config.yaml")
    monkeypatch.setattr(desktop_config, "DESKTOP_CONFIG_FILE", custom / "desktop.yaml")
    assert config.load_config() == {"profiles": {}}
    assert desktop_config.load_desktop_config() == desktop_config.DEFAULTS
    assert not current.exists()
    config.save_config({"profiles": {}, "marker": "custom"})
    assert config.load_config()["marker"] == "custom"


@pytest.mark.parametrize("name,load", [
    ("config.yaml", config.load_config),
    ("desktop.yaml", desktop_config.load_desktop_config),
])
def test_unreadable_legacy_file_does_not_create_empty_replacement(settings_home, monkeypatch, name, load):
    current, legacy = settings_home
    write_yaml(legacy / name, {"profiles": {}})
    read_bytes = Path.read_bytes

    def unreadable(path):
        if path == legacy / name:
            raise PermissionError("legacy settings unreadable")
        return read_bytes(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", unreadable)
        with pytest.raises(PermissionError, match="legacy settings unreadable"):
            load()
    assert not (current / name).exists()
    assert (legacy / name).is_file()
    load()
    assert (current / name).is_file()


def test_file_created_during_import_is_not_overwritten(settings_home, monkeypatch):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}, "marker": "old"})
    read_bytes = Path.read_bytes

    def concurrent_writer(path):
        content = read_bytes(path)
        if path == legacy / "config.yaml":
            write_yaml(current / "config.yaml", {"profiles": {}, "marker": "concurrent"})
        return content

    monkeypatch.setattr(Path, "read_bytes", concurrent_writer)
    assert config.load_config()["marker"] == "concurrent"
    assert sorted(path.name for path in current.iterdir()) == ["config.yaml"]


def test_interrupted_import_leaves_no_partial_config_and_can_retry(settings_home, monkeypatch):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}, "marker": "old"})

    def disk_full(_):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(config_paths.os, "fsync", disk_full)
        with pytest.raises(OSError, match="disk full"):
            config.load_config()
    assert list(current.iterdir()) == []
    assert config.load_config()["marker"] == "old"
    assert (legacy / "config.yaml").is_file()


def test_concurrent_imports_publish_one_complete_copy(settings_home, monkeypatch):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}, "marker": "old"})
    barrier = threading.Barrier(4)
    read_bytes = Path.read_bytes

    def read_together(path):
        content = read_bytes(path)
        if path == legacy / "config.yaml":
            barrier.wait(timeout=5)
        return content

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_together)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: config.load_config(), range(4)))
    assert results == [{"profiles": {}, "marker": "old"}] * 4
    assert (current / "config.yaml").read_bytes() == (legacy / "config.yaml").read_bytes()
    assert sorted(path.name for path in current.iterdir()) == ["config.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_import_creates_private_settings_files(settings_home):
    current, legacy = settings_home
    write_yaml(legacy / "config.yaml", {"profiles": {}})
    write_yaml(legacy / "desktop.yaml", desktop_config.DEFAULTS)
    config.load_config()
    desktop_config.load_desktop_config()
    assert stat.S_IMODE(current.stat().st_mode) == 0o700
    for name in ("config.yaml", "desktop.yaml"):
        assert stat.S_IMODE((current / name).stat().st_mode) == 0o600
