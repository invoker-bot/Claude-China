"""Keep the experimental launch gate fail-closed and scoped to Grok Bot."""

from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from tools import windows_takeover_probe as probe
from claude_china.desktop import config, safety


@pytest.fixture
def gate(tmp_path, monkeypatch):
    target = tmp_path / "Grok Bot.exe"
    target.write_bytes(b"fixture")
    data = deepcopy(config.DEFAULTS)
    data.update(check_system_proxy=False, env_vars={"PROBE_COMMON": "common"})
    data["apps"] = {"grok-bot": {"env_vars": {"PROBE_COMMON": "app"}}}
    monkeypatch.setattr(config, "load_desktop_config", lambda: deepcopy(data))
    check = Mock(return_value={"status": "unknown", "reason": "no verified regions"})
    monkeypatch.setattr(safety, "inspect_environment", check)
    launch = Mock(return_value=12345)
    return target, data, check, launch


def test_unknown_region_never_creates_a_process(gate):
    target, _, check, launch = gate
    result = probe.gated_launch(target, [str(target)], launch=launch)
    assert not result["ok"]
    assert result["safety"]["status"] == "unknown"
    check.assert_called_once()
    launch.assert_not_called()


def test_preflight_exception_never_creates_a_process(gate):
    target, _, check, launch = gate
    check.side_effect = RuntimeError("secret credentials must not appear")
    result = probe.gated_launch(target, [str(target)], launch=launch)
    assert not result["ok"]
    assert "secret" not in str(result)
    launch.assert_not_called()


def test_invalid_automatic_proxy_is_not_ignored(gate, monkeypatch):
    target, data, check, launch = gate
    data["auto_proxy_env"] = True
    monkeypatch.setattr(probe.WindowsBackend, "system_http_proxy", Mock(side_effect=ValueError("secret")))
    result = probe.gated_launch(target, [str(target)], launch=launch)
    assert not result["ok"]
    launch.assert_not_called()
    check.assert_not_called()


def test_allowed_launch_forwards_args_cwd_and_merged_environment_without_stopping(gate, monkeypatch):
    target, _, check, launch = gate
    check.return_value = {"status": "supported", "reason": "test fixture"}
    stop = Mock(side_effect=AssertionError("External launch must not stop an existing application"))
    monkeypatch.setattr(probe.WindowsBackend, "stop", stop)
    args = [str(target), "--argument", "value with spaces", 'quote"inside', "Unicode-中文"]
    result = probe.gated_launch(target, args, launch=launch)
    assert result["ok"] and result["pid"] == 12345
    forwarded, env, cwd = launch.call_args.args
    assert forwarded == args
    assert env["PROBE_COMMON"] == "app"
    assert cwd == str(Path.cwd())
    stop.assert_not_called()


def test_target_mismatch_fails_before_checking_or_launching(gate, tmp_path):
    target, _, check, launch = gate
    with pytest.raises(ValueError, match="target"):
        probe.gated_launch(target, [str(tmp_path / "Codex.exe")], launch=launch)
    check.assert_not_called()
    launch.assert_not_called()


@pytest.mark.parametrize("name", ["Claude.exe", "Codex.exe", "Uninstall Grok Bot.exe"])
def test_probe_refuses_other_applications(tmp_path, name):
    target = tmp_path / name
    target.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="Grok"):
        probe.gated_launch(target, [str(target)], launch=Mock())


def test_launch_failure_is_closed_without_unmanaged_fallback(gate):
    target, _, check, launch = gate
    check.return_value = {"status": "supported"}
    launch.side_effect = OSError("private diagnostic")
    result = probe.gated_launch(target, [str(target)], launch=launch)
    assert not result["ok"]
    assert "private diagnostic" not in str(result)
    assert launch.call_count == 1


def test_changed_configuration_cancels_before_launch(gate, monkeypatch):
    target, data, check, launch = gate
    check.return_value = {"status": "supported"}
    initial = deepcopy(data)
    changed = deepcopy(data)
    changed["env_vars"]["PROBE_COMMON"] = "changed"
    monkeypatch.setattr(config, "load_desktop_config", Mock(side_effect=[initial, initial, changed]))
    result = probe.gated_launch(target, [str(target)], launch=launch)
    assert not result["ok"]
    launch.assert_not_called()


def test_temporary_test_override_never_saves_or_mutates_real_settings(gate, monkeypatch, tmp_path):
    target, data, check, launch = gate
    before = deepcopy(data)
    save = Mock(side_effect=AssertionError("No real config writes"))
    monkeypatch.setattr(config, "save_desktop_config", save)
    result = probe.gated_launch(target, [str(target)], launch=launch,
                                isolated_profile=tmp_path / "isolated", test_allow=True,
                                marker="test-only")
    assert result["ok"] and result["test_override"] is True
    assert data == before
    save.assert_not_called()
    check.assert_not_called()
    assert launch.call_args.args[1]["CLAUDEC_TAKEOVER_PROBE"] == "test-only"
    assert launch.call_args.args[1]["SAND_USER_DATA_DIR"] == str(tmp_path / "isolated")


def test_temporary_allow_requires_isolated_profile(gate):
    target, _, _, launch = gate
    with pytest.raises(ValueError, match="isolated"):
        probe.gated_launch(target, [str(target)], launch=launch, test_allow=True)
    launch.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows debugger API")
def test_native_debugger_launch_reaches_entrypoint_with_environment_args_and_cwd(tmp_path):
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        pytest.skip("Windows C# compiler unavailable")
    source = tmp_path / "Probe.cs"
    source.write_text('''using System;
using System.IO;
class Probe {
    static int Main(string[] args) {
        File.WriteAllLines(args[0], new string[] {
            Environment.GetEnvironmentVariable("CLAUDEC_TAKEOVER_PROBE"),
            Environment.CurrentDirectory, args[1], args[2], args[3]
        });
        return 0;
    }
}''', encoding="utf-8")
    target = tmp_path / "Native Probe.exe"
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(target), str(source)],
                   check=True, capture_output=True, timeout=30)
    report = tmp_path / "result.txt"
    env = dict(os.environ, CLAUDEC_TAKEOVER_PROBE="entrypoint-marker")
    pid = probe.launch_detached_debugger(
        [str(target), str(report), "spaces stay together", 'literal"quote', "中文"], env, str(tmp_path))
    assert pid > 0
    deadline = time.monotonic() + 10
    while not report.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert report.read_text(encoding="utf-8-sig").splitlines() == [
        "entrypoint-marker", str(tmp_path), "spaces stay together", 'literal"quote', "中文",
    ]
