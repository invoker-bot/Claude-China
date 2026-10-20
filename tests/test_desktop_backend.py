import sys

from src.claude_china.desktop.platforms import get_backend


def test_returns_windows_backend_on_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    backend = get_backend()
    assert type(backend).__name__ == "WindowsBackend"


def test_returns_mac_backend_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    backend = get_backend()
    assert type(backend).__name__ == "MacBackend"


def test_returns_linux_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    backend = get_backend()
    assert type(backend).__name__ == "LinuxBackend"


def test_returns_none_on_other(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd")
    assert get_backend() is None
