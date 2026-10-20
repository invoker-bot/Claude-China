import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from unittest.mock import Mock

import pytest

from src.claude_china.desktop import app as app_mod
from src.claude_china.desktop import single_instance as instance_mod


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.shown = threading.Event()

    def restore(self):
        self.calls.append("restore")

    def show(self):
        self.calls.append("show")
        self.shown.set()


def start_listener(instance, window):
    thread = threading.Thread(target=instance.listen, args=(window,), daemon=True)
    thread.start()
    return thread


@pytest.fixture
def migrated_instance_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    current = tmp_path / ".claudec" / "desktop.lock"
    legacy = tmp_path / ".code-ai" / "desktop.lock"
    monkeypatch.setattr(instance_mod.cfg, "DESKTOP_CONFIG_FILE", current.with_name("desktop.yaml"))
    return current, legacy


def test_new_install_locks_claudec_without_creating_legacy_directory(migrated_instance_home):
    current, legacy = migrated_instance_home
    with instance_mod.DesktopInstance() as instance:
        assert instance.acquire_or_activate()
        assert current.is_file()
        assert not legacy.parent.exists()


@pytest.mark.parametrize("alias_directory", [False, True])
def test_aliased_legacy_path_is_not_locked_twice(migrated_instance_home, alias_directory):
    current, legacy = migrated_instance_home
    legacy.parent.mkdir()
    try:
        if alias_directory:
            current.parent.symlink_to(legacy.parent, target_is_directory=True)
        else:
            current.parent.mkdir()
            legacy.touch()
            current.symlink_to(legacy)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable")
    with instance_mod.DesktopInstance() as owner:
        assert owner.acquire_or_activate(timeout=0.1)


def test_new_launcher_activates_running_legacy_launcher(migrated_instance_home):
    current, legacy = migrated_instance_home
    window = FakeWindow()
    with instance_mod.DesktopInstance(legacy) as old:
        assert old.acquire_or_activate()
        listener = start_listener(old, window)
        try:
            with instance_mod.DesktopInstance() as new:
                assert not new.acquire_or_activate(timeout=1)
            assert window.calls == ["restore", "show"]
        finally:
            old.close()
            listener.join(timeout=3)
    with instance_mod.DesktopInstance() as replacement:
        assert replacement.acquire_or_activate(timeout=1)
        assert current.is_file()


@pytest.mark.parametrize("contender_path", ["current", "legacy", "default"])
def test_migrated_launcher_accepts_new_and_old_activation(migrated_instance_home, contender_path):
    current, legacy = migrated_instance_home
    legacy.parent.mkdir()
    window = FakeWindow()
    with instance_mod.DesktopInstance() as owner:
        assert owner.acquire_or_activate()
        listener = start_listener(owner, window)
        try:
            path = {"current": current, "legacy": legacy, "default": None}[contender_path]
            with instance_mod.DesktopInstance(path) as contender:
                assert not contender.acquire_or_activate(timeout=1)
            assert window.calls == ["restore", "show"]
        finally:
            owner.close()
            listener.join(timeout=3)
    for path in (current, legacy):
        with instance_mod.DesktopInstance(path) as replacement:
            assert replacement.acquire_or_activate(timeout=1)


def test_unresponsive_legacy_launcher_never_creates_second_gui(migrated_instance_home):
    current, legacy = migrated_instance_home
    with instance_mod.DesktopInstance(legacy) as old:
        assert old.acquire_or_activate()
        with instance_mod.DesktopInstance() as new:
            with pytest.raises(RuntimeError, match="already running"):
                new.acquire_or_activate(timeout=0.1)
        # The failed attempt must also release the new directory's lock.
        with instance_mod.DesktopInstance(current) as replacement:
            assert replacement.acquire_or_activate(timeout=1)


@pytest.mark.parametrize("explicit_path", [False, True])
def test_custom_lock_path_does_not_activate_user_launcher(
    migrated_instance_home, tmp_path, monkeypatch, explicit_path,
):
    _, legacy = migrated_instance_home
    path = tmp_path / "smoke" / "desktop.lock"
    monkeypatch.setattr(instance_mod.cfg, "DESKTOP_CONFIG_FILE", path.with_name("desktop.yaml"))
    with instance_mod.DesktopInstance(legacy) as old:
        assert old.acquire_or_activate()
        with instance_mod.DesktopInstance(path if explicit_path else None) as isolated:
            assert isolated.acquire_or_activate(timeout=0.1)


def test_second_instance_restores_and_shows_existing_window(tmp_path, monkeypatch):
    path = tmp_path / "desktop.lock"
    allow_foreground = Mock()
    monkeypatch.setattr(instance_mod, "_allow_foreground", allow_foreground)
    window = FakeWindow()
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
        thread = start_listener(first, window)
        try:
            with instance_mod.DesktopInstance(path) as second:
                assert not second.acquire_or_activate()
            assert window.calls == ["restore", "show"]
            allow_foreground.assert_called_once_with(os.getpid())
        finally:
            first.close()
            thread.join(timeout=3)
    assert not thread.is_alive()


@pytest.mark.parametrize("animation_error", [None, OSError("tray unavailable")])
def test_activation_notifies_animation_without_blocking_ack(tmp_path, animation_error):
    window = FakeWindow()
    activity = Mock(side_effect=animation_error)
    path = tmp_path / "desktop.lock"
    with instance_mod.DesktopInstance(path) as owner:
        assert owner.acquire_or_activate()
        listener = threading.Thread(target=owner.listen, args=(window, activity), daemon=True)
        listener.start()
        try:
            with instance_mod.DesktopInstance(path) as duplicate:
                assert not duplicate.acquire_or_activate(timeout=1)
            assert window.calls == ["restore", "show"]
            activity.assert_called_once_with()
        finally:
            owner.close()
            listener.join(timeout=3)
    assert not listener.is_alive()


def test_duplicate_launch_waits_for_first_window_to_be_ready(tmp_path, monkeypatch):
    path = tmp_path / "desktop.lock"
    window = FakeWindow()
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
        with instance_mod.DesktopInstance(path) as second:
            result = []
            errors = []
            requested = threading.Event()
            activate_existing = second._activate_existing

            def request_activation(timeout):
                requested.set()
                return activate_existing(timeout)

            monkeypatch.setattr(second, "_activate_existing", request_activation)

            def activate():
                try:
                    result.append(second.acquire_or_activate(timeout=3))
                except Exception as exc:
                    errors.append(exc)

            duplicate = threading.Thread(target=activate)
            duplicate.start()
            assert requested.wait(timeout=1)
            listener = start_listener(first, window)
            try:
                duplicate.join(timeout=5)
                assert not duplicate.is_alive()
                assert errors == []
                assert result == [False]
                assert window.shown.is_set()
            finally:
                first.close()
                listener.join(timeout=3)
                duplicate.join(timeout=5)


@pytest.mark.parametrize("legacy_directory", [False, True])
def test_concurrent_launches_choose_one_owner(tmp_path, monkeypatch, legacy_directory):
    path = tmp_path / "desktop.lock"
    if legacy_directory:
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / ".code-ai").mkdir()
        monkeypatch.setattr(
            instance_mod.cfg, "DESKTOP_CONFIG_FILE", tmp_path / ".claudec" / "desktop.yaml",
        )
        path = None
    barrier = threading.Barrier(4)
    release_owner = threading.Event()
    launches_finished = threading.Event()
    results = []
    errors = []
    window = FakeWindow()

    def launch():
        listener = None
        try:
            with instance_mod.DesktopInstance(path) as instance:
                barrier.wait(timeout=5)
                primary = instance.acquire_or_activate(timeout=5)
                results.append(primary)
                if len(results) == 4:
                    launches_finished.set()
                if primary:
                    listener = start_listener(instance, window)
                    release_owner.wait(timeout=10)
        except Exception as exc:
            errors.append(exc)
        finally:
            if listener is not None:
                listener.join(timeout=3)

    threads = [threading.Thread(target=launch) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        # All three secondary launches must finish while the owner holds its lock.
        assert launches_finished.wait(timeout=7)
        assert errors == []
        assert sorted(results) == [False, False, False, True]
        assert window.calls == ["restore", "show"] * 3
    finally:
        release_owner.set()
        for thread in threads:
            thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)


def test_waiting_launch_takes_over_if_owner_exits(tmp_path, monkeypatch):
    path = tmp_path / "desktop.lock"
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
        with instance_mod.DesktopInstance(path) as second:
            def owner_exits(timeout):
                first.close()
                return False

            monkeypatch.setattr(second, "_activate_existing", owner_exits)

            assert second.acquire_or_activate(timeout=1)


def test_relaunch_after_close_reuses_lock_file(tmp_path):
    path = tmp_path / "desktop.lock"
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
    assert path.exists()  # Unlinking a lock file would let racers lock different files.
    with instance_mod.DesktopInstance(path) as next_instance:
        assert next_instance.acquire_or_activate()


def test_stale_metadata_does_not_prevent_launch(tmp_path):
    path = tmp_path / "desktop.lock"
    path.write_bytes(b"\0" + b'{"pid":99999999,"port":1,"token":"stale"}')
    with instance_mod.DesktopInstance(path) as instance:
        assert instance.acquire_or_activate()


def test_unresponsive_instance_never_creates_second_launcher(tmp_path):
    path = tmp_path / "desktop.lock"
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
        with instance_mod.DesktopInstance(path) as second:
            with pytest.raises(RuntimeError, match="already running"):
                second.acquire_or_activate(timeout=0.1)


def test_lock_is_released_if_listener_setup_fails(tmp_path, monkeypatch):
    path = tmp_path / "desktop.lock"
    with monkeypatch.context() as patch:
        patch.setattr(instance_mod.socket, "socket", Mock(side_effect=OSError("no sockets")))
        with pytest.raises(OSError, match="no sockets"):
            with instance_mod.DesktopInstance(path) as instance:
                instance.acquire_or_activate()
    with instance_mod.DesktopInstance(path) as instance:
        assert instance.acquire_or_activate()


def test_lock_permission_error_is_not_treated_as_running_instance(tmp_path):
    path = tmp_path / "desktop.lock"
    path.mkdir()
    with pytest.raises(OSError):
        with instance_mod.DesktopInstance(path) as instance:
            instance.acquire_or_activate()


def test_listener_ignores_invalid_requests_and_stays_available(tmp_path):
    path = tmp_path / "desktop.lock"
    window = FakeWindow()
    with instance_mod.DesktopInstance(path) as first:
        assert first.acquire_or_activate()
        thread = start_listener(first, window)
        try:
            with path.open("rb", buffering=0) as state:
                state.seek(1)  # Windows locks only byte zero.
                metadata = json.loads(state.read())
            with socket.create_connection(("127.0.0.1", metadata["port"]), timeout=1) as client:
                client.sendall(b"not-the-token\n")
                assert client.recv(3) == b""
            assert window.calls == []
            with instance_mod.DesktopInstance(path) as second:
                assert not second.acquire_or_activate()
            assert window.calls == ["restore", "show"]
        finally:
            first.close()
            thread.join(timeout=3)


def test_os_releases_lock_after_process_is_killed(tmp_path):
    path = tmp_path / "desktop.lock"
    script = """
import sys
from claude_china.desktop.single_instance import DesktopInstance
with DesktopInstance(sys.argv[1]) as instance:
    assert instance.acquire_or_activate()
    print("ready", flush=True)
    sys.stdin.read()
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", script, str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ready = []
    reader = threading.Thread(target=lambda: ready.append(process.stdout.readline()), daemon=True)
    reader.start()
    try:
        reader.join(timeout=10)
        assert ready == ["ready\n"]
        with instance_mod.DesktopInstance(path) as second:
            with pytest.raises(RuntimeError, match="already running"):
                second.acquire_or_activate(timeout=0.1)
        process.kill()
        process.wait(timeout=5)
        with instance_mod.DesktopInstance(path) as next_instance:
            assert next_instance.acquire_or_activate()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
        reader.join(timeout=3)


def test_macos_lock_uses_nonblocking_flock(monkeypatch):
    flock = Mock()
    fake_fcntl = Mock(flock=flock, LOCK_EX=2, LOCK_NB=4)
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    monkeypatch.setattr(instance_mod.sys, "platform", "darwin")
    stream = Mock()
    stream.fileno.return_value = 12

    assert instance_mod._try_lock(stream)
    flock.assert_called_once_with(12, 6)
    flock.side_effect = BlockingIOError(errno.EAGAIN, "locked")
    assert not instance_mod._try_lock(stream)
    flock.side_effect = OSError(errno.EBADF, "bad descriptor")
    with pytest.raises(OSError, match="bad descriptor"):
        instance_mod._try_lock(stream)


def test_windows_foreground_permission_targets_only_owner(monkeypatch):
    import ctypes

    allow = Mock()
    monkeypatch.setattr(instance_mod.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", Mock(user32=Mock(AllowSetForegroundWindow=allow)),
                        raising=False)

    instance_mod._allow_foreground(42)

    allow.assert_called_once_with(42)


@pytest.mark.parametrize("failure_stage", ["tray", "gui"])
def test_gui_holds_lock_until_event_loop_exits_and_releases_on_error(
    monkeypatch, tmp_path, failure_stage,
):
    from tests.test_desktop_app_import import _FakeBackend, _FakeWindow

    path = tmp_path / "desktop.lock"
    monkeypatch.setattr(instance_mod.cfg, "DESKTOP_CONFIG_FILE", tmp_path / "desktop.yaml")
    monkeypatch.setattr(app_mod, "get_backend", lambda: _FakeBackend())
    tray = Mock()
    if failure_stage == "tray":
        tray.start.side_effect = RuntimeError("GUI startup failed")
    monkeypatch.setattr(app_mod, "LauncherTray", Mock(return_value=tray))
    monkeypatch.setattr(app_mod.DesktopMenu, "native_menu", lambda self: [])
    window = _FakeWindow()

    def start(**kwargs):
        assert kwargs["args"] == (window, tray.play_activity)
        assert callable(kwargs["func"])
        with instance_mod.DesktopInstance(path) as contender:
            with pytest.raises(RuntimeError, match="already running"):
                contender.acquire_or_activate(timeout=0.1)
        raise RuntimeError("GUI startup failed")

    monkeypatch.setitem(sys.modules, "webview", Mock(
        create_window=Mock(return_value=window), start=start, OPEN_DIALOG=20,
    ))

    with pytest.raises(RuntimeError, match="GUI startup failed"):
        app_mod.run_gui()

    tray.stop.assert_called_once_with()
    with instance_mod.DesktopInstance(path) as next_instance:
        assert next_instance.acquire_or_activate()
