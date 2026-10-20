import json
from pathlib import Path
import threading
from unittest.mock import Mock
import uuid

import pytest

from src.claude_china.desktop import update_install as install


@pytest.fixture
def job(tmp_path):
    directory = tmp_path / "updates" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    target = tmp_path / "installed"
    target.mkdir()
    package = directory / "Claude-China-0.4.0-windows-x64-setup.exe"
    package.write_bytes(b"verified")
    plan = directory / "plan.json"
    install.write_json(plan, {
        "kind": "windows", "target": str(target.resolve()), "suffix": "windows-x64-setup.exe",
        "package": package.name, "version": "0.4.0", "sha256": install.file_digest(package),
        "previous": "0.3.0", "parent_pid": 123, "parent_created": 1.0,
    })
    return plan, package, target


def test_helper_waits_for_parent_before_installing_then_restarts(job, monkeypatch):
    plan, _, target = job
    calls = []
    monkeypatch.setattr(install, "_wait_for_parent", lambda *args: calls.append("exited"))
    monkeypatch.setattr(install.Installation, "installed_version", lambda self: "0.3.0")
    monkeypatch.setattr(install.Installation, "apply",
                        lambda *args: calls.append("installed"))
    monkeypatch.setattr(install, "_spawn", lambda *args, **kwargs: calls.append("restarted"))
    assert install.apply_update(plan) == 0
    assert calls == ["exited", "installed", "restarted"]
    result = json.loads((plan.parent.parent / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] and "0.4.0" in result["message"]


def test_installer_failure_reopens_launcher_and_persists_failure(job, monkeypatch):
    plan, _, target = job
    monkeypatch.setattr(install, "_wait_for_parent", Mock())
    monkeypatch.setattr(install.Installation, "installed_version", lambda self: "0.3.0")
    monkeypatch.setattr(install.Installation, "apply", Mock(side_effect=RuntimeError("cancelled")))
    spawn = Mock()
    monkeypatch.setattr(install, "_spawn", spawn)
    assert install.apply_update(plan) == 1
    assert spawn.call_args.args[0] == [target / "claude-china-desktop.exe"]
    result = json.loads((plan.parent.parent / "result.json").read_text(encoding="utf-8"))
    assert not result["ok"] and "cancelled" in result["message"]


def test_restart_failure_is_not_reported_as_a_successful_update(job, monkeypatch):
    plan, _, _ = job
    monkeypatch.setattr(install, "_wait_for_parent", Mock())
    monkeypatch.setattr(install.Installation, "installed_version", lambda self: "0.3.0")
    monkeypatch.setattr(install.Installation, "apply", Mock())
    monkeypatch.setattr(install, "_spawn", Mock(side_effect=OSError("could not start")))
    assert install.apply_update(plan) == 1
    result = json.loads((plan.parent.parent / "result.json").read_text(encoding="utf-8"))
    assert not result["ok"] and "手动启动" in result["message"]


def test_parent_that_does_not_exit_prevents_install_and_restart(job, monkeypatch):
    plan, _, _ = job
    monkeypatch.setattr(install, "_wait_for_parent", Mock(side_effect=TimeoutError("still running")))
    apply = Mock()
    spawn = Mock()
    monkeypatch.setattr(install.Installation, "apply", apply)
    monkeypatch.setattr(install, "_spawn", spawn)
    assert install.apply_update(plan) == 1
    apply.assert_not_called()
    spawn.assert_not_called()


def test_changed_installer_cannot_trigger_exit_handshake_or_install(job, monkeypatch):
    plan, package, _ = job
    package.write_bytes(b"changed")
    apply = Mock()
    monkeypatch.setattr(install.Installation, "apply", apply)
    assert install.apply_update(plan) == 1
    assert not (plan.parent / "ready.json").exists()
    apply.assert_not_called()


def test_installer_changed_while_waiting_is_checked_again(job, monkeypatch):
    plan, package, _ = job
    monkeypatch.setattr(install, "_wait_for_parent", lambda *args: package.write_bytes(b"changed"))
    apply = Mock()
    monkeypatch.setattr(install.Installation, "apply", apply)
    monkeypatch.setattr(install, "_spawn", Mock())
    assert install.apply_update(plan) == 1
    apply.assert_not_called()


def test_cleanup_only_removes_inactive_job_directories(tmp_path, monkeypatch):
    import psutil
    inactive = tmp_path / uuid.uuid4().hex
    inactive.mkdir()
    (inactive / ".claude-china-update").touch()
    active = tmp_path / uuid.uuid4().hex
    active.mkdir()
    (active / ".claude-china-update").touch()
    unrelated = tmp_path / uuid.uuid4().hex
    unrelated.mkdir()
    install.write_json(active / "ready.json", {"pid": 123})
    settings = tmp_path / "desktop.yaml"
    settings.write_text("keep")
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 123)
    install.cleanup_jobs(tmp_path)
    assert not inactive.exists()
    assert active.exists()
    assert unrelated.exists()
    assert settings.read_text() == "keep"


def test_update_staging_cannot_be_inside_installation(tmp_path, monkeypatch):
    job = tmp_path / "updates" / uuid.uuid4().hex
    job.mkdir(parents=True)
    package = job / "Claude-China-0.4.0-windows-x64-setup.exe"
    package.write_bytes(b"package")
    instance = install.Installation("windows", tmp_path, "windows-x64-setup.exe")
    verify = Mock()
    monkeypatch.setattr(instance, "verify_package", verify)
    copy = Mock()
    monkeypatch.setattr(install.shutil, "copytree", copy)
    with pytest.raises(RuntimeError, match="暂存"):
        instance.prepare(package, "0.4.0", threading.Event())
    verify.assert_not_called()
    copy.assert_not_called()


def test_newer_installation_is_not_overwritten_by_stale_update(job, monkeypatch):
    plan, _, _ = job
    monkeypatch.setattr(install, "_wait_for_parent", Mock())
    monkeypatch.setattr(install.Installation, "installed_version", lambda self: "0.5.0")
    apply = Mock()
    monkeypatch.setattr(install.Installation, "apply", apply)
    monkeypatch.setattr(install, "_spawn", Mock())
    assert install.apply_update(plan) == 1
    apply.assert_not_called()


def test_windows_install_never_reboots_os_or_closes_other_apps(job, monkeypatch):
    _, package, target = job
    instance = install.Installation("windows", target, "windows-x64-setup.exe")
    monkeypatch.setattr(install, "verify_windows_signature", Mock())
    monkeypatch.setattr(instance, "installed_version", lambda: "0.4.0")
    run = Mock()
    monkeypatch.setattr(install, "_run", run)
    instance.apply(package, "0.4.0")
    command = run.call_args.args[0]
    assert command[0] == package
    assert "/NORESTART" in command
    assert "/NOCLOSEAPPLICATIONS" in command
    assert "/NORESTARTAPPLICATIONS" in command
    assert "/RESTARTEXITCODE=3010" in command
    assert f"/DIR={target}" in command


@pytest.mark.parametrize("kind,manager", [("deb", "apt-get"), ("rpm", "dnf")])
def test_linux_update_uses_system_package_manager_and_graphical_auth(
    kind, manager, tmp_path, monkeypatch,
):
    instance = install.Installation(kind, Path("/opt/claude-china"), f"linux-x64.{kind}")
    package = tmp_path / f"installer.{kind}"
    monkeypatch.setattr(instance, "verify_package", Mock())
    monkeypatch.setattr(instance, "installed_version", lambda: "0.4.0")
    run = Mock()
    monkeypatch.setattr(install, "_run", run)
    instance.apply(package, "0.4.0")
    command = run.call_args.args[0]
    assert command[:2] == ["/usr/bin/pkexec", Path("/usr/bin") / manager]
    assert command[-1] == package
    assert "--no-remove" in command if kind == "deb" else True


@pytest.mark.parametrize("status,subject,allowed", [
    ("NotSigned", None, False), ("HashMismatch", "Publisher", False),
    ("Valid", "Other publisher", False), ("Valid", "Publisher", True),
])
def test_signed_windows_install_cannot_downgrade_publisher_trust(
    status, subject, allowed, monkeypatch, tmp_path,
):
    monkeypatch.setattr(install, "_run", Mock(return_value=json.dumps([
        {"Status": status, "Subject": subject},
        {"Status": "Valid", "Subject": "Publisher"},
    ])))
    if allowed:
        install.verify_windows_signature(tmp_path / "new.exe", tmp_path / "old.exe")
    else:
        with pytest.raises(RuntimeError):
            install.verify_windows_signature(tmp_path / "new.exe", tmp_path / "old.exe")


def test_unsigned_install_can_migrate_to_first_signed_release(monkeypatch, tmp_path):
    monkeypatch.setattr(install, "_run", Mock(return_value=json.dumps([
        {"Status": "Valid", "Subject": "SignPath Foundation"},
        {"Status": "NotSigned", "Subject": None},
    ])))
    install.verify_windows_signature(tmp_path / "new.exe", tmp_path / "old.exe")


def test_mac_failed_swap_restores_original_bundle(tmp_path, monkeypatch):
    target = tmp_path / "Claude China.app"
    target.mkdir()
    (target / "original").write_text("old version")
    job = tmp_path / "staging"
    job.mkdir()
    new = job / "new.app"
    new.mkdir()
    instance = install.Installation("macos", target, "macos-arm64.dmg")
    monkeypatch.setattr(install, "_mac_info", lambda path: {"CFBundleShortVersionString": "0.4.0"})
    monkeypatch.setattr(install, "_mac_team", lambda path: "ABCDEFGHIJ")

    def command(args, **kwargs):
        if args[0] == "/usr/bin/ditto":
            Path(args[-1]).mkdir()
    monkeypatch.setattr(install, "_run", command)
    original_rename = Path.rename

    def rename(path, destination):
        if "incoming" in path.name:
            raise OSError("cannot replace")
        return original_rename(path, destination)
    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(OSError, match="cannot replace"):
        instance._apply_mac(job, "0.4.0")
    assert (target / "original").read_text() == "old version"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Claude China.app", "staging"]


def test_restart_resets_pyinstaller_environment_and_does_not_use_shell(monkeypatch, tmp_path):
    spawn = Mock()
    monkeypatch.setattr(install.process, "Popen", spawn)
    install._spawn([tmp_path / "app.exe"], tmp_path)
    options = spawn.call_args.kwargs
    assert options["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not options.get("shell")
    assert options["cwd"] == str(tmp_path)


def test_hidden_update_entry_never_initializes_webview_or_installer_mutex(monkeypatch, tmp_path):
    from src.claude_china.desktop import entry
    run = Mock(return_value=0)
    monkeypatch.setattr(install, "apply_update", run)
    mutex = Mock(side_effect=AssertionError("updater must not hold installer mutex"))
    monkeypatch.setattr(entry, "_installer_mutex", mutex)
    assert entry.main(["--apply-update", str(tmp_path / "plan.json")]) == 0
    run.assert_called_once_with(tmp_path / "plan.json")
    mutex.assert_not_called()
