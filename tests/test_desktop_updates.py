import hashlib
import io
import json
import threading
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import updates


def release(version="0.4.0", suffix="windows-x64-setup.exe", payload=b"installer"):
    name = f"Claude-China-{version}-{suffix}"
    url = f"{updates.REPOSITORY}/releases/download/v{version}/{name}"
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "tag_name": "v" + version, "draft": False, "prerelease": False,
        "assets": [
            {"name": name, "browser_download_url": url, "size": len(payload),
             "digest": "sha256:" + digest},
            {"name": name + ".sha256", "browser_download_url": url + ".sha256",
             "size": 150},
        ],
    }


def test_versions_compare_numerically_and_never_offer_downgrades():
    assert updates.parse_release(release("0.10.0"), "0.9.0", "windows-x64-setup.exe")
    assert updates.parse_release(release("0.3.0"), "0.3.0", "windows-x64-setup.exe") is None
    assert updates.parse_release(release("0.2.0"), "0.3.0", "windows-x64-setup.exe") is None


@pytest.mark.parametrize("change", [
    {"draft": True}, {"prerelease": True}, {"tag_name": "v0.4.0-rc1"},
    {"tag_name": "../0.4.0"}, {"assets": []},
])
def test_incomplete_or_nonstable_releases_cannot_be_installed(change):
    data = release()
    data.update(change)
    with pytest.raises(updates.UpdateError):
        updates.parse_release(data, "0.3.0", "windows-x64-setup.exe")


@pytest.mark.parametrize("url", [
    "http://github.com/invoker-bot/Claude-China/releases/download/v0.4.0/a.exe",
    "https://evil.example/installer.exe",
    "https://github.com/other/repo/releases/download/v0.4.0/a.exe",
])
def test_release_cannot_supply_an_arbitrary_download_url(url):
    data = release()
    data["assets"][0]["browser_download_url"] = url
    with pytest.raises(updates.UpdateError):
        updates.parse_release(data, "0.3.0", "windows-x64-setup.exe")


def test_exact_platform_asset_selected_without_cross_arch_fallback():
    with pytest.raises(updates.UpdateError, match="安装包"):
        updates.parse_release(release(suffix="macos-x64.dmg"), "0.3.0", "macos-arm64.dmg")


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {}


def mock_download(monkeypatch, data, payload, checksum=None):
    asset = updates.parse_release(data, "0.3.0", "windows-x64-setup.exe")
    checksum = checksum or f"{hashlib.sha256(payload).hexdigest()}  {asset.name}\n"
    monkeypatch.setattr(updates, "_open", lambda url: Response(
        checksum.encode() if url.endswith(".sha256") else payload,
    ))
    return asset


def test_download_verifies_size_and_digest_before_atomic_promotion(monkeypatch, tmp_path):
    asset = mock_download(monkeypatch, release(), b"installer")
    progress = Mock()
    path = updates.download(asset, tmp_path, threading.Event(), progress)
    assert path.read_bytes() == b"installer"
    assert not list(tmp_path.glob("*.part"))
    assert progress.call_args.args == (9, 9)


@pytest.mark.parametrize("payload,checksum", [
    (b"tampered!", None),
    (b"installer", "0" * 64 + "  different.exe\n"),
    (b"short", None),
    (b"installer-overlong", None),
])
def test_invalid_download_is_removed(monkeypatch, tmp_path, payload, checksum):
    asset = mock_download(monkeypatch, release(), payload, checksum)
    with pytest.raises(updates.UpdateError):
        updates.download(asset, tmp_path, threading.Event(), Mock())
    assert not list(tmp_path.iterdir())


def test_cancelled_download_never_becomes_ready(monkeypatch, tmp_path):
    asset = mock_download(monkeypatch, release(), b"installer")
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(updates.UpdateCancelled):
        updates.download(asset, tmp_path, cancelled, Mock())
    assert not list(tmp_path.iterdir())


def test_network_interrupt_does_not_leave_partial_installer(monkeypatch, tmp_path):
    asset = mock_download(monkeypatch, release(), b"installer")
    original_open = updates._open

    class BrokenResponse(Response):
        def read(self, *args):
            raise OSError("connection reset")

    monkeypatch.setattr(updates, "_open", lambda url: (
        original_open(url) if url.endswith(".sha256") else BrokenResponse(b"")
    ))
    with pytest.raises(OSError):
        updates.download(asset, tmp_path, threading.Event(), Mock())
    assert not list(tmp_path.iterdir())


def test_redirect_rejects_https_downgrade_or_unrelated_host():
    import urllib.request
    redirect = updates.GitHubRedirect()
    request = urllib.request.Request(updates.REPOSITORY)
    for url in ("http://github.com/a", "https://example.org/a"):
        with pytest.raises(updates.UpdateError):
            redirect.redirect_request(request, None, 302, "Found", {}, url)
    result = redirect.redirect_request(request, None, 302, "Found", {},
                                       "https://release-assets.githubusercontent.com/a")
    assert result.full_url.startswith("https://release-assets.")


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def manager(monkeypatch, tmp_path):
    install = Mock(suffix="windows-x64-setup.exe", reason="")
    install.prepare.return_value = tmp_path / "job" / "plan.json"
    monkeypatch.setattr(updates, "Installation", Mock(detect=lambda: install))
    monkeypatch.setattr(updates, "latest_release", lambda: release())
    monkeypatch.setattr(updates.threading, "Thread", ImmediateThread)
    manager = updates.UpdateManager(Mock(), root=tmp_path, current="0.3.0")
    return manager


def test_failed_check_is_retryable_without_losing_configuration(manager, monkeypatch):
    monkeypatch.setattr(updates, "latest_release", Mock(side_effect=OSError("offline")))
    assert manager.check()["phase"] == "error"
    monkeypatch.setattr(updates, "latest_release", lambda: release())
    assert manager.check()["phase"] == "available"


def test_check_download_and_restart_require_separate_actions(manager, monkeypatch):
    assert manager.status()["phase"] == "idle"
    assert manager.check()["phase"] == "available"
    manager._installation.prepare.assert_not_called()
    monkeypatch.setattr(updates, "download", Mock(return_value=manager._root / "installer.exe"))
    assert manager.fetch()["phase"] == "ready"
    manager._quit.assert_not_called()
    helper = Mock()
    monkeypatch.setattr(updates, "start_helper", Mock(return_value=helper))
    assert manager.install()["phase"] == "installing"
    manager._quit.assert_called_once()


def test_helper_failure_leaves_launcher_open_and_update_retryable(manager, monkeypatch):
    manager.check()
    monkeypatch.setattr(updates, "download", Mock(return_value=manager._root / "installer.exe"))
    manager.fetch()
    monkeypatch.setattr(updates, "start_helper", Mock(side_effect=OSError("cannot start")))
    assert manager.install()["phase"] == "error"
    manager._quit.assert_not_called()


def test_installer_is_never_started_before_verified_download(manager, monkeypatch):
    helper = Mock()
    monkeypatch.setattr(updates, "start_helper", helper)
    assert manager.install()["phase"] == "idle"
    helper.assert_not_called()


def test_duplicate_check_does_not_start_two_network_requests(manager, monkeypatch):
    pending = []
    monkeypatch.setattr(updates.threading, "Thread",
                        lambda target, **kwargs: Mock(start=lambda: pending.append(target)))
    manager.check()
    manager.check()
    manager.fetch()
    assert manager.status()["phase"] == "checking"
    assert len(pending) == 1


def test_shutdown_prevents_a_preparing_worker_from_quitting_or_starting_helper(
    manager, monkeypatch,
):
    manager.check()
    monkeypatch.setattr(updates, "download", Mock(return_value=manager._root / "installer.exe"))
    manager.fetch()
    manager.shutdown()
    helper = Mock()
    monkeypatch.setattr(updates, "start_helper", helper)
    manager.install()
    helper.assert_not_called()
    manager._quit.assert_not_called()


def test_previous_install_error_is_visible_on_next_start(manager):
    (manager._root / "result.json").write_text(json.dumps({
        "ok": False, "message": "更新已取消，原版本仍可使用。",
    }), encoding="utf-8")
    reopened = updates.UpdateManager(Mock(), root=manager._root)
    assert reopened.status()["phase"] == "error"
    assert "取消" in reopened.status()["message"]
