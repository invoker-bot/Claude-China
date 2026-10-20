from src.claude_china.desktop.apps import get_app


def test_linux_does_not_mistake_cli_on_path_for_desktop_app():
    from src.claude_china.desktop.platforms.linux import LinuxBackend
    assert not LinuxBackend().detect(get_app("claude")).found


def test_linux_detects_only_executable_files(tmp_path, monkeypatch):
    from src.claude_china.desktop.platforms import linux
    binary = tmp_path / "Claude Desktop"
    binary.write_bytes(b"executable")
    monkeypatch.setattr(linux.os, "access", lambda path, mode: True)
    backend = linux.LinuxBackend()
    status = backend.detect(get_app("claude"), str(binary))
    assert status.found and status.direct
    assert status.launch_target == str(binary.resolve())
    # Never use /usr/bin or another shared directory as the stop-process root.
    assert status.match_root == str(binary.resolve())
    assert not backend.detect(get_app("claude"), str(tmp_path)).found
    monkeypatch.setattr(linux.os, "access", lambda path, mode: False)
    assert not backend.detect(get_app("claude"), str(binary)).found


def test_linux_launch_preserves_spaces_and_environment(monkeypatch):
    from src.claude_china.desktop.platforms import linux
    from src.claude_china.desktop.platforms.base import AppStatus
    calls = []
    monkeypatch.setattr(linux.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    status = AppStatus("claude", True, True, "/opt/Claude Desktop/claude")
    linux.LinuxBackend().launch(status, {"HTTPS_PROXY": "http://localhost:7890"})
    assert calls == [((["/opt/Claude Desktop/claude"],), {
        "env": {"HTTPS_PROXY": "http://localhost:7890"}, "start_new_session": True,
    })]


def test_linux_stop_and_monitor_use_exact_executable(monkeypatch):
    from src.claude_china.desktop.platforms import linux
    from src.claude_china.desktop.platforms.base import AppStatus
    calls = []
    monkeypatch.setattr(linux.base, "any_process_under", lambda roots: calls.append(roots) or True)
    monkeypatch.setattr(linux.base, "stop_processes_under", lambda roots: calls.append(roots))
    backend = linux.LinuxBackend()
    status = AppStatus("claude", True, True, "/usr/bin/claude-desktop", "/usr/bin/claude-desktop")
    assert backend.is_running(status)
    backend.stop(status)
    assert calls == [["/usr/bin/claude-desktop"], ["/usr/bin/claude-desktop"]]


def test_linux_proxy_checks_environment_and_gnome(monkeypatch):
    from src.claude_china.desktop.platforms import linux
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(linux.subprocess, "check_output", lambda *a, **kw: "'none'\n")
    backend = linux.LinuxBackend()
    assert not backend.proxy_enabled()
    monkeypatch.setattr(linux.subprocess, "check_output", lambda *a, **kw: "'manual'\n")
    assert backend.proxy_enabled()
    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:7890")
    monkeypatch.setattr(linux.subprocess, "check_output", lambda *a, **kw: "'none'\n")
    assert backend.proxy_enabled()
